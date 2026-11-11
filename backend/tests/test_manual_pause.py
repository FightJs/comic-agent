import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import pytest
from backend.agent_runtime import PiRuntime,RuntimeUnavailable

@pytest.fixture
def provider():
    requests=[]
    class Provider(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
            for delta,reason in [({'role':'assistant','content':'Synthetic complete result.'},None),({},'stop')]:
                self.wfile.write(('data: '+json.dumps({'id':'fixture','object':'chat.completion.chunk','created':1,'model':'fixture','choices':[{'index':0,'delta':delta,'finish_reason':reason}],'usage':{'prompt_tokens':5,'completion_tokens':2,'total_tokens':7}})+'\n\n').encode())
            self.wfile.write(b'data: [DONE]\n\n')
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Provider);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:yield {'url':f'http://127.0.0.1:{server.server_port}/v1','model':'fixture'},requests
    finally:server.shutdown();server.server_close();thread.join()


def test_runtime_pause_capacity_wait_makes_zero_call_checkpoint_and_explicit_child_uses_original_task(tmp_path,provider):
    async def scenario():
        config,calls=provider;runtime=PiRuntime(tmp_path)
        await runtime.start();pool=runtime.capacity.pools['text'];pool.limit=1;held=await pool.enter('occupied')
        args=dict(run_id='queued-parent',project_id='p',session_id='s',prompt='固定原任务',config=config,secret='synthetic-key',tools=[])
        try:
            task=asyncio.create_task(runtime.request('run',**args))
            for _ in range(200):
                if pool.snapshot()['waiting']==1:break
                await asyncio.sleep(.01)
            else:pytest.fail('model did not wait for shared capacity')
            paused=await runtime.request('pause',run_id='queued-parent')
            assert paused['data']['pause_requested'] and paused['data']['queued']
            reply=await asyncio.wait_for(task,10)
            assert reply['error']['code']=='manual_pause'
            assert reply['data']['checkpoint']['model_requests']==0 and reply['data']['checkpoint']['session_saved']
            assert calls==[] and pool.snapshot()=={'limit':1,'active':1,'waiting':0}
            pool.leave(held)
            child=await runtime.request('run',**{**args,'run_id':'queued-child','resume_from':'queued-parent'})
            assert child['type']=='result' and child['data']['checkpoint']['parent_run_id']=='queued-parent'
            assert len(calls)==1 and '固定原任务' in json.dumps(calls[0],ensure_ascii=False)
        finally:
            pool.leave(held);await runtime.close()
            if 'task' in locals():await asyncio.gather(task,return_exceptions=True)
    asyncio.run(scenario())


@pytest.fixture
def slow_provider():
    entered=threading.Event();release=threading.Event();requests=[]
    class Provider(BaseHTTPRequestHandler):
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append(body)
            first=len(requests)==1
            if first:entered.set();release.wait(20)
            delta={'role':'assistant','tool_calls':[{'index':0,'id':'undispatched','type':'function','function':{'name':'project_query','arguments':'{"action":"catalog"}'}}]} if first else {'role':'assistant','content':json.dumps({'patch':{'description':'明确续接后的生产候选'}}) if '固定输入：' in json.dumps(body,ensure_ascii=False) else '明确续接后完整回复'}
            try:
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
                for value,reason in [(delta,None),({},'tool_calls' if first else 'stop')]:
                    self.wfile.write(('data: '+json.dumps({'id':'fixture','object':'chat.completion.chunk','created':1,'model':'fixture','choices':[{'index':0,'delta':value,'finish_reason':reason}],'usage':{'prompt_tokens':5,'completion_tokens':2,'total_tokens':7}})+'\n\n').encode())
                self.wfile.write(b'data: [DONE]\n\n')
            except (BrokenPipeError,ConnectionResetError):pass
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Provider);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:yield {'url':f'http://127.0.0.1:{server.server_port}/v1','model':'fixture'},requests,entered,release
    finally:release.set();server.shutdown();server.server_close();thread.join()


def test_discussion_manual_pause_is_persistent_and_continuation_requires_explicit_grant(tmp_path,monkeypatch,slow_provider):
    from fastapi.testclient import TestClient
    import backend.app as module
    from backend.tests.test_agent_continue import wait
    config,calls,entered,release=slow_provider
    monkeypatch.setattr(module.vault,'get_password',lambda *args:'synthetic-pause-key')
    with TestClient(module.create_app(tmp_path)) as c:
        pid=c.post('/api/projects',json={'name':'手动暂停讨论'}).json()['id'];b=f'/api/projects/{pid}'
        with c.app.state.store.db() as db:db.execute('INSERT INTO settings VALUES(1,?)',(json.dumps({'text':config}),))
        sid=c.post(b+'/agent/sessions',json={'stage':'script'}).json()['id']
        rid=c.post(b+f'/agent/sessions/{sid}/messages',json={'expected_version':0,'message':'只讨论，不写稿'}).json()['id']
        assert entered.wait(10)
        response=c.post(b+f'/agent/runs/{rid}/pause',json={});assert response.status_code==200,response.text
        assert response.json()['pause_requested'] is True
        assert c.post(b+f'/agent/runs/{rid}/pause',json={'confirm':True}).status_code==422
        assert c.post('/api/projects/foreign/agent/runs/'+rid+'/pause',json={}).status_code==404
        release.set();paused=wait(c,b,rid)
        assert paused['status']=='paused' and paused['checkpoint']['reason']=='manual_pause'
        assert len(calls)==1 and paused['checkpoint']['model_requests']==1 and paused['checkpoint']['tool_calls']==0
        assert c.post(b+f'/agent/sessions/{sid}/messages',json={'expected_version':1,'message':'不能绕暂停'}).status_code==409
        assert c.post(b+f'/agent/runs/{rid}/continue',json={'expected_version':1,'confirm':False}).status_code==422
        child=c.post(b+f'/agent/runs/{rid}/continue',json={'expected_version':1,'confirm':True}).json()['id']
        assert wait(c,b,child)['status']=='completed' and len(calls)==2
        assert c.get(b+'/tasks').json()==[]


def test_production_manual_pause_preserves_original_and_structural_attempt_on_continuation(tmp_path,monkeypatch,slow_provider):
    from concurrent.futures import ThreadPoolExecutor
    from fastapi.testclient import TestClient
    import backend.app as module
    config,calls,entered,release=slow_provider
    monkeypatch.setattr(module.vault,'get_password',lambda *args:'synthetic-pause-key')
    with TestClient(module.create_app(tmp_path)) as c,ThreadPoolExecutor(max_workers=1) as executor:
        pid=c.post('/api/projects',json={'name':'手动暂停生产'}).json()['id'];b=f'/api/projects/{pid}'
        with c.app.state.store.db() as db:db.execute('INSERT INTO settings VALUES(1,?)',(json.dumps({'text':config}),))
        script=c.post(b+'/records',json={'kind':'script','title':'第1格','content':{'episode':1,'panel':1,'description':'原稿不变'}}).json()
        future=executor.submit(c.post,b+'/production-jobs',json={'operation':'rewrite','refs':[{'id':script['id'],'version':1}],'instruction':'只改描述','submission_id':'manual-pause'})
        assert entered.wait(10)
        task=c.get(b+'/tasks').json()[0];tid=task['id']
        response=c.post(b+f'/production-jobs/{tid}/pause',json={});assert response.status_code==200,response.text
        assert c.get(b+'/tasks?compact=true').json()[0]['pause_requested'] is True
        release.set();assert future.result(timeout=15).status_code==200
        paused=c.get(b+'/tasks').json()[0];assert paused['status']=='paused',paused
        checkpoint=paused['payload']['production_checkpoint'];assert checkpoint['reason']=='manual_pause'
        aid=checkpoint['attempt_id'];assert len(calls)==1
        assert c.post(b+f'/production-jobs/{tid}/attempts/{aid}/continue',json={'confirm':True}).status_code==200
        final=c.get(b+'/tasks').json()[0];assert final['status']=='succeeded',final
        assert final['pause_requested'] is False
        assert len(calls)==2
        out=c.get(b+'/records/'+final['output_id']).json();assert not out['adopted']
        assert c.get(b+'/records/'+script['id']).json()['version']==1
        assert [r['attempt'] for r in c.get(b+f'/production-jobs/{tid}/attempts').json()]==[1,1]


def test_cancel_wins_over_a_queued_pause_without_creating_or_sending_a_run(tmp_path,provider):
    async def scenario():
        config,calls=provider;runtime=PiRuntime(tmp_path);await runtime.start()
        pool=runtime.capacity.pools['text'];pool.limit=1;held=await pool.enter('occupied')
        task=asyncio.create_task(runtime.request('run',run_id='cancel-parent',project_id='p',session_id='s',prompt='固定任务',config=config,secret='synthetic-key',tools=[]))
        try:
            for _ in range(200):
                if pool.snapshot()['waiting']==1:break
                await asyncio.sleep(.01)
            else:pytest.fail('model did not queue')
            assert (await runtime.request('pause',run_id='cancel-parent'))['data']['queued']
            assert (await runtime.request('cancel',run_id='cancel-parent'))['data']['cancelled']
            with pytest.raises(RuntimeUnavailable,match='cancelled_before_dispatch'):await task
            assert calls==[] and pool.snapshot()['waiting']==0
            assert not (tmp_path/'agent/p/checkpoints/cancel-parent.json').exists()
        finally:pool.leave(held);await runtime.close();await asyncio.gather(task,return_exceptions=True)
    asyncio.run(scenario())


def test_public_discussion_pause_while_waiting_capacity_persists_without_a_provider_call(tmp_path,monkeypatch,provider):
    from fastapi.testclient import TestClient
    import backend.app as module
    from backend.tests.test_agent_continue import wait
    import time
    config,calls=provider;monkeypatch.setattr(module.vault,'get_password',lambda *args:'synthetic-pause-key')
    with TestClient(module.create_app(tmp_path)) as c:
        pid=c.post('/api/projects',json={'name':'排队暂停'}).json()['id'];b=f'/api/projects/{pid}'
        with c.app.state.store.db() as db:db.execute('INSERT INTO settings VALUES(1,?)',(json.dumps({'text':config}),))
        assert c.put('/api/runtime/limits',json={'expected_revision':0,'limits':{'text':1,'image':1,'vision':1}}).status_code==200
        pool=c.app.state.capacity.pools['text'];c.portal.call(pool.acquire)
        try:
            sid=c.post(b+'/agent/sessions',json={'stage':'script'}).json()['id']
            rid=c.post(b+f'/agent/sessions/{sid}/messages',json={'expected_version':0,'message':'排队原任务'}).json()['id']
            for _ in range(200):
                if pool.snapshot()['waiting']==1:break
                time.sleep(.01)
            else:pytest.fail('discussion did not queue')
            assert c.post(b+f'/agent/runs/{rid}/pause',json={}).status_code==200
            paused=wait(c,b,rid);assert paused['status']=='paused' and paused['checkpoint']['model_requests']==0
            assert calls==[] and pool.snapshot()['active']==1 and pool.snapshot()['waiting']==0
        finally:c.portal.call(pool.release)
    with TestClient(module.create_app(tmp_path)) as c:
        assert c.get(b+f'/agent/runs/{rid}').json()['status']=='paused' and calls==[]
        child=c.post(b+f'/agent/runs/{rid}/continue',json={'expected_version':1,'confirm':True})
        assert child.status_code==200,child.text
        assert wait(c,b,child.json()['id'])['status']=='completed' and len(calls)==1


def test_pause_api_rejects_non_pi_production_and_other_projects(tmp_path):
    from fastapi.testclient import TestClient
    from backend.app import create_app
    from backend.store import now
    with TestClient(create_app(tmp_path)) as c:
        pid=c.post('/api/projects',json={'name':'暂停边界'}).json()['id']
        with c.app.state.store.db() as db:
            db.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?)',('mock-job',pid,'queued',json.dumps({'operation':'image','source':'mock'}),None,'',now(),now()))
        assert c.post(f'/api/projects/{pid}/production-jobs/mock-job/pause',json={}).status_code==409
        assert c.post('/api/projects/foreign/production-jobs/mock-job/pause',json={}).status_code==404
        assert c.post(f'/api/projects/{pid}/production-jobs/mock-job/pause',json={'start_paused':True}).status_code==422
