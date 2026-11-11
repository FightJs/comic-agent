"""Supervised, private JSONL transport. Business writes stay in Python."""
import asyncio
import json
import os
import inspect
from pathlib import Path
from uuid import uuid4
from .capacity import CapacityManager,CapacityCancelled


class RuntimeUnavailable(RuntimeError):
    pass


class PiRuntime:
    def __init__(self, data_dir, node='node',capacity=None):
        self.data_dir = Path(data_dir).resolve()
        self.node = node
        self.process = None
        self.status = 'stopped'
        self.error = None
        self.pending = {}
        self.reader = None
        self.write_lock = asyncio.Lock()
        self.tool_tasks = set()
        self.capacity=capacity or CapacityManager()
        self.model_runs={}
        self.closing=False

    async def start(self):
        self.closing=False
        if self.status == 'ready':
            return
        runtime_dir = Path(__file__).resolve().parents[1] / 'agent-runtime'
        # Do not inherit provider keys, personal Pi settings or shell startup hooks.
        env = {k: os.environ[k] for k in ('PATH', 'SYSTEMROOT', 'TMPDIR') if k in os.environ}
        env.update(COMIC_AGENT_DATA=str(self.data_dir / 'agent'), PI_OFFLINE='1')
        try:
            self.process = await asyncio.create_subprocess_exec(
                self.node, str(runtime_dir / 'src/server.mjs'), cwd=runtime_dir,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, env=env, limit=2**21)
            self.status = 'starting'
            self.reader = asyncio.create_task(self._read())
            reply = await self.request('health', timeout=15)
            if reply.get('v') != 1 or reply.get('data', {}).get('protocol') != 1:
                raise RuntimeUnavailable('protocol_mismatch')
            self.status = 'ready'
            self.error = None
        except Exception:
            await self.close()
            self.status = 'unavailable'
            self.error = 'Pi 运行层不可用；请检查 Node ≥22.19 及 agent-runtime 依赖'

    async def _read(self):
        try:
            while line := await self.process.stdout.readline():
                message = json.loads(line)
                if message.get('v') != 1:
                    raise RuntimeUnavailable('protocol_mismatch')
                entry = self.pending.get(message.get('request_id'))
                if not entry:
                    continue
                future, on_event, on_tool, run_id = entry
                if message.get('type') == 'tool_request':
                    if future.done() or message.get('run_id') != run_id or not on_tool:
                        await self._send(dict(v=1,type='tool_result',run_id=message.get('run_id'),tool_call_id=message.get('tool_call_id'),error='tool_denied'))
                    else:
                        task=asyncio.create_task(self._tool(message,on_tool))
                        self.tool_tasks.add(task)
                        task.add_done_callback(self.tool_tasks.discard)
                    continue
                if message.get('type') == 'event':
                    if on_event:
                        await on_event(message)
                elif not future.done():
                    future.set_result(message)
        except Exception:
            pass
        finally:
            if self.status != 'stopped':
                self.status = 'unavailable'
                self.error = 'Pi 运行层已退出；基础编辑仍可使用'
            for future, *_ in self.pending.values():
                if not future.done():
                    future.set_exception(RuntimeUnavailable('runtime_exited'))

    async def _send(self,message):
        async with self.write_lock:
            self.process.stdin.write((json.dumps(message,ensure_ascii=False)+'\n').encode())
            await self.process.stdin.drain()

    async def _tool(self,message,on_tool):
        result=dict(v=1,type='tool_result',run_id=message['run_id'],tool_call_id=message.get('tool_call_id'))
        try:
            result['data']=await on_tool(message)
            result['result_json']=json.dumps(result['data'],ensure_ascii=False)
        except Exception:
            result['error']='tool_denied'
        try: await self._send(result)
        except (BrokenPipeError,ConnectionResetError): pass

    def cancel_queued(self,run_id):
        for pool in self.capacity.pools.values():pool.cancel(run_id)

    async def request(self, command, timeout=300, on_event=None, on_tool=None, before_dispatch=None,capacity_lease=None, **payload):
        if command=='pause':
            entry=self.model_runs.get(payload.get('run_id'))
            if entry:
                if not entry['pausable']:raise RuntimeUnavailable('pause_not_supported')
                entry['pause_requested']=True
                if not entry['sent']:
                    self.cancel_queued(payload.get('run_id'))
                    return {'v':1,'type':'result','data':{'pause_requested':True,'queued':True}}
        if command=='cancel':
            entry=self.model_runs.get(payload.get('run_id'))
            if entry and not entry['sent']:
                entry['cancelled']=True;self.cancel_queued(payload.get('run_id'))
                return {'v':1,'type':'result','data':{'cancelled':True,'queued':True}}
        if command not in ('run','setup','complete'):
            return await self._exchange(command,timeout,on_event,on_tool,**payload)
        if self.closing:raise RuntimeUnavailable('runtime_closing')
        run_id=payload.get('run_id') or uuid4().hex
        if run_id in self.model_runs:raise RuntimeUnavailable('run_busy')
        role='vision' if command=='complete' and payload.get('images') else 'text'
        pool=self.capacity.pools[role];entry={'cancelled':False,'sent':False,'pausable':command=='run','pause_requested':command=='run' and payload.get('start_paused') is True};self.model_runs[run_id]=entry
        async def dispatch():
            if self.closing or entry['cancelled']:raise RuntimeUnavailable('cancelled_before_dispatch')
            if before_dispatch:
                result=before_dispatch()
                if inspect.isawaitable(result):result=await result
                if result is not None:
                    if not isinstance(result,dict) or set(result)-{'secret'}:raise RuntimeUnavailable('dispatch_guard_invalid')
                    payload.update(result)
            if self.closing or entry['cancelled']:raise RuntimeUnavailable('cancelled_before_dispatch')
            if entry['pause_requested']:payload['start_paused']=True
            entry['sent']=True
            return await self._exchange(command,timeout,on_event,on_tool,**payload)
        try:
            if entry['pause_requested']:return await dispatch()
            if capacity_lease is not None:
                if not pool.owns(capacity_lease):raise RuntimeUnavailable('capacity_lease_invalid')
                return await dispatch()
            async with pool.hold(run_id):return await dispatch()
        except CapacityCancelled as exc:
            if entry['pause_requested'] and not entry['cancelled'] and not self.closing:return await dispatch()
            raise RuntimeUnavailable('cancelled_before_dispatch') from exc
        finally:self.model_runs.pop(run_id,None)

    async def _exchange(self, command, timeout=300, on_event=None, on_tool=None, **payload):
        if self.status not in ('ready', 'starting') or self.process.returncode is not None:
            raise RuntimeUnavailable('runtime_unavailable')
        request_id = uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self.pending[request_id] = (future, on_event, on_tool, payload.get('run_id'))
        try:
            message = dict(payload, v=1, type=command, request_id=request_id)
            await self._send(message)
            return await asyncio.wait_for(future, timeout)
        except (TimeoutError,asyncio.CancelledError):
            if command in ('run','complete','setup') and payload.get('run_id'):
                try: await self.request('cancel',run_id=payload['run_id'],timeout=3)
                except Exception: pass
            raise
        except (BrokenPipeError, ConnectionResetError) as exc:
            raise RuntimeUnavailable('runtime_exited') from exc
        finally:
            self.pending.pop(request_id, None)

    async def close(self):
        self.closing=True
        for run_id,entry in list(self.model_runs.items()):
            if not entry['sent']:entry['cancelled']=True;self.cancel_queued(run_id)
        if self.process and self.process.returncode is None:
            try:
                await self.request('shutdown', timeout=3)
                await asyncio.wait_for(self.process.wait(), 3)
            except Exception:
                self.process.kill()
                await self.process.wait()
        for task in self.tool_tasks: task.cancel()
        await asyncio.gather(*self.tool_tasks,return_exceptions=True)
        self.status = 'stopped'
        if self.reader:
            await self.reader
