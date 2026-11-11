import asyncio
import pytest
from backend.agent_runtime import PiRuntime, RuntimeUnavailable


def test_runtime_health_and_shutdown(tmp_path):
    async def check():
        runtime = PiRuntime(tmp_path)
        await runtime.start()
        assert runtime.status == 'ready'
        result = await runtime.request('health')
        assert result['data']['sdk'] == '1.5.0'
        await runtime.close()
        assert runtime.status == 'stopped'
    asyncio.run(check())


def test_missing_executable_does_not_crash_host(tmp_path):
    async def check():
        runtime = PiRuntime(tmp_path, node='/missing/comic-node')
        await runtime.start()
        assert runtime.status == 'unavailable'
        with pytest.raises(RuntimeUnavailable):
            await runtime.request('health')
        await runtime.close()
    asyncio.run(check())


def test_child_exit_resolves_pending_requests(tmp_path):
    async def check():
        runtime = PiRuntime(tmp_path)
        await runtime.start()
        runtime.process.kill()
        await runtime.process.wait()
        await asyncio.sleep(.05)
        assert runtime.status == 'unavailable'
        with pytest.raises(RuntimeUnavailable):
            await runtime.request('health')
        await runtime.close()
    asyncio.run(check())


def test_app_manages_runtime_without_claiming_provider_connected(tmp_path):
    from fastapi.testclient import TestClient
    from backend.app import create_app
    app = create_app(tmp_path)
    with TestClient(app) as client:
        response = client.get('/api/agent/health')
        assert response.status_code == 200
        assert response.json()['status'] == 'ready'
        assert response.json()['provider_verified'] is False
    assert app.state.pi_runtime.status == 'stopped'


def test_incompatible_child_is_stopped_and_reported(tmp_path):
    async def check():
        script = tmp_path / 'wrong-node'
        script.write_text('#!/usr/bin/env python3\nimport sys,json\nfor line in sys.stdin:\n m=json.loads(line); print(json.dumps({"v":9,"request_id":m["request_id"],"type":"result","data":{"protocol":9}}),flush=True)\n')
        script.chmod(0o700)
        runtime = PiRuntime(tmp_path, node=str(script))
        await runtime.start()
        assert runtime.status == 'unavailable'
        assert runtime.process.returncode is not None
    asyncio.run(check())


def test_agent_sessions_are_project_scoped_and_preserve_frozen_refs(tmp_path):
    from fastapi.testclient import TestClient
    from backend.app import create_app
    with TestClient(create_app(tmp_path)) as c:
        p = c.post('/api/projects', json={'name':'甲'}).json()['id']
        other = c.post('/api/projects', json={'name':'乙'}).json()['id']
        base = f'/api/projects/{p}'
        record = c.post(base+'/records', json={'kind':'outline','title':'细纲','content':{'text':'第一话'}}).json()
        result = c.post(base+'/agent/sessions', json={'stage':'outline','refs':[{'id':record['id'],'version':1}]})
        assert result.status_code == 200, result.text
        sid = result.json()['id']
        assert c.get(f'/api/projects/{other}/agent/sessions/{sid}').status_code == 404
        assert c.get(base+f'/agent/sessions/{sid}').json()['refs'][0]['version'] == 1
        missing = c.post(base+f'/agent/sessions/{sid}/messages', json={'message':'修改细纲','expected_version':0})
        assert missing.status_code == 409
        assert c.get(base+'/tasks').json() == []
        assert c.get(base+f'/agent/sessions/{sid}').json()['version'] == 0


def test_discussion_persists_real_sdk_reply_without_production_writes(tmp_path, monkeypatch):
    import json
    import time
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from fastapi.testclient import TestClient
    from backend.app import create_app
    import backend.app as module

    requests=[]
    class Provider(BaseHTTPRequestHandler):
        def do_POST(self):
            request=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append(request)
            self.send_response(200)
            self.send_header('Content-Type','text/event-stream')
            self.end_headers()
            chunks = [
                {'id':'fixture','object':'chat.completion.chunk','created':1,'model':'fixture','choices':[{'index':0,'delta':{'role':'assistant','content':'可以调整第二话节奏'},'finish_reason':None}]},
                {'id':'fixture','object':'chat.completion.chunk','created':1,'model':'fixture','choices':[{'index':0,'delta':{},'finish_reason':'stop'}]},
            ]
            if not any(m['role']=='tool' for m in request['messages']):
                chunks=[{'id':'fixture','object':'chat.completion.chunk','created':1,'model':'fixture','choices':[{'index':0,'delta':{'role':'assistant','tool_calls':[{'index':0,'id':'query1','type':'function','function':{'name':'project_query','arguments':json.dumps({'action':'skill','id':skill['hash'],'query':'references/rules.md'})}}]},'finish_reason':None}]},{'id':'fixture','object':'chat.completion.chunk','created':1,'model':'fixture','choices':[{'index':0,'delta':{},'finish_reason':'tool_calls'}]}]
            for chunk in chunks: self.wfile.write(('data: '+json.dumps(chunk)+'\n\n').encode())
            self.wfile.write(b'data: [DONE]\n\n')
        def log_message(self,*args): pass
    server = ThreadingHTTPServer(('127.0.0.1',0),Provider)
    thread = threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    monkeypatch.setattr(module.vault,'get_password',lambda *args:'test-secret-not-persisted')
    try:
        with TestClient(create_app(tmp_path)) as c:
            pid = c.post('/api/projects',json={'name':'隔离对话'}).json()['id']
            base = f'/api/projects/{pid}'
            from backend.tests.test_skills import pack,install
            skill=install(c,pack()).json()
            c.put(base+'/skills',json={'expected_revision':0,'hashes':[skill['hash']]})
            with c.app.state.store.db() as db:
                db.execute('INSERT INTO settings VALUES(1,?)',(json.dumps({'text':{'url':f'http://127.0.0.1:{server.server_port}/v1','model':'fixture','purpose':'text'}}),))
            sid = c.post(base+'/agent/sessions',json={'stage':'outline'}).json()['id']
            sent = c.post(base+f'/agent/sessions/{sid}/messages',json={'message':'优化节奏','expected_version':0})
            assert sent.status_code == 200,sent.text
            rid = sent.json()['id']
            deadline = time.monotonic()+15
            while time.monotonic()<deadline:
                result = c.get(base+f'/agent/runs/{rid}').json()
                if result['status'] not in ('queued','running'): break
                time.sleep(.05)
            assert result['status'] == 'completed',result
            assert result['reply'] == '可以调整第二话节奏'
            assert result['events'][0]['delta'] == '可以调整第二话节奏'
            seq = result['events'][-1]['seq']
            assert c.get(base+f'/agent/runs/{rid}?after={seq}').json()['events'] == []
            assert c.get(base+'/tasks').json() == []
            assert c.get(base+'/records').json() == []
            with c.app.state.store.db() as db:
                receipt=db.execute('SELECT result FROM agent_tool_calls WHERE run_id=?',(rid,)).fetchone()
                assert json.loads(receipt['result'])['text']=='不得为追求戏剧性伪造原著事实。'
            count=len(requests)
            checked=c.get(base+f'/agent/runs/{rid}/tool-receipts')
            assert checked.status_code==200,checked.text
            assert checked.json()['receipts'][0]['state']=='matched'
            assert checked.json()['recovery_available'] is False
            assert '不得为追求' not in checked.text and 'session_file' not in checked.text
            other=c.post('/api/projects',json={'name':'隔离回执'}).json()['id']
            assert c.get(f'/api/projects/{other}/agent/runs/{rid}/tool-receipts').status_code==404
            assert len(requests)==count

            assert '先核对人物动机' in json.dumps(requests[0],ensure_ascii=False)
            assert '不得为追求戏剧性伪造原著事实' in json.dumps(requests[-1],ensure_ascii=False)
            assert result['skills'][0]['hash']==skill['hash']
            assert c.get(base+f'/agent/sessions/{sid}').json()['version'] == 1
            listed=c.get(base+'/agent/sessions?stage=outline')
            assert listed.status_code==200 and listed.json()[0]['id']==sid
            checkpoint=c.get(base+f'/agent/runs/{rid}/checkpoint')
            assert checkpoint.status_code==200,checkpoint.text
            value=checkpoint.json()['checkpoint']
            assert value['status']=='completed' and value['model_requests']==2 and value['tool_calls']==1
            assert value['unknown_usage_requests']==2 and value['session_saved']
            other=c.post('/api/projects',json={'name':'其他项目'}).json()['id']
            assert c.get(f'/api/projects/{other}/agent/runs/{rid}/checkpoint').status_code==404
            assert len(requests)==2
        with TestClient(create_app(tmp_path)) as c:
            recovered=c.get(base+f'/agent/runs/{rid}/checkpoint')
            assert recovered.status_code==200,recovered.text
            assert recovered.json()['checkpoint']==value
            assert len(requests)==2
        assert b'test-secret-not-persisted' not in (tmp_path/'workbench.sqlite').read_bytes()
    finally:
        server.shutdown(); server.server_close(); thread.join()


def test_runtime_routes_tool_calls_without_blocking_health(tmp_path):
    import json
    async def check():
        script=tmp_path/'bridge-node'
        script.write_text('''#!/usr/bin/env python3
import sys,json
for line in sys.stdin:
 m=json.loads(line)
 if m['type']=='run':
  print(json.dumps(dict(v=1,type='tool_request',request_id=m['request_id'],run_id=m['run_id'],tool_call_id='call1',name='project_query',arguments={'action':'catalog'})),flush=True)
  original=m
 elif m['type']=='tool_result':
  print(json.dumps(dict(v=1,type='result',request_id=original['request_id'],data=m['data'])),flush=True)
 elif m['type']=='shutdown':
  print(json.dumps(dict(v=1,type='result',request_id=m['request_id'])),flush=True); break
 else: print(json.dumps(dict(v=1,type='result',request_id=m['request_id'],data={'protocol':1})),flush=True)
''')
        script.chmod(0o700)
        runtime=PiRuntime(tmp_path,node=str(script))
        await runtime.start()
        async def tool(message):
            health=await runtime.request('health',timeout=1)
            assert health['data']['protocol']==1
            return {'records':[{'id':'safe'}]}
        try:
            response=await runtime.request('run',run_id='r',on_tool=tool,timeout=3)
            assert response['data']['records']==[{'id':'safe'}]
        finally: await runtime.close()
    asyncio.run(check())


@pytest.mark.parametrize('command',['run','complete'])
def test_timeout_cancels_the_same_run_before_releasing_transport(tmp_path,command):
    import json
    async def check():
        script=tmp_path/'timeout-node';trace=tmp_path/'trace'
        script.write_text('''#!/usr/bin/env python3
import sys,json
from pathlib import Path
trace=Path(__file__).parent/'trace'
for line in sys.stdin:
 m=json.loads(line)
 with trace.open('a') as f: f.write(json.dumps(m)+'\\n')
 if m['type'] in ('run','complete'): continue
 print(json.dumps(dict(v=1,type='result',request_id=m['request_id'],data={'protocol':1})),flush=True)
 if m['type']=='shutdown': break
''');script.chmod(0o700)
        runtime=PiRuntime(tmp_path,node=str(script));await runtime.start()
        try:
            with pytest.raises(TimeoutError): await runtime.request(command,run_id='slow',timeout=.1)
            messages=[json.loads(line) for line in trace.read_text().splitlines()]
            assert any(m['type']=='cancel' and m['run_id']=='slow' for m in messages)
            assert (await runtime.request('health'))['data']['protocol']==1
        finally: await runtime.close()
    asyncio.run(check())


def test_cancel_preserves_received_text_and_never_turns_into_completed(tmp_path):
    from fastapi.testclient import TestClient
    from backend.app import create_app
    from backend.store import dump
    with TestClient(create_app(tmp_path)) as c:
        pid=c.post('/api/projects',json={'name':'取消测试'}).json()['id'];base=f'/api/projects/{pid}'
        sid=c.post(base+'/agent/sessions',json={'stage':'memory'}).json()['id']
        with c.app.state.store.db() as db:
            db.execute('INSERT INTO agent_runs VALUES(?,?,?,?,?,?,?,?,?,?)',('r',pid,sid,'running','问题','','',None,'t','t'))
            db.execute('INSERT INTO agent_events VALUES(?,?,?)',('r',1,dump({'event':'text_delta','delta':'已经收到的答复'})))
        result=c.post(base+'/agent/runs/r/cancel',json={}).json()
        assert result['status']=='cancelled'
        assert result['reply']=='已经收到的答复'
        assert c.get(base+'/agent/runs/r').json()['status']=='cancelled'


def test_long_documents_are_available_by_tools_without_stuffing_prompt(tmp_path,monkeypatch):
    import json
    import time
    from fastapi.testclient import TestClient
    from backend.app import create_app
    import backend.app as module
    monkeypatch.setattr(module.vault,'get_password',lambda *args:'fixture-only')
    app=create_app(tmp_path);captured=[];original=app.state.pi_runtime.request
    async def request(command,**kwargs):
        if command!='run': return await original(command,**kwargs)
        captured.append(kwargs['prompt'])
        return {'type':'result','data':{'text':'已按需读取'}}
    monkeypatch.setattr(app.state.pi_runtime,'request',request)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'长篇讨论'}).json()['id'];base=f'/api/projects/{pid}'
        from backend.tests.test_skills import pack,install
        skill=install(c,pack()).json()
        c.put(base+'/skills',json={'expected_revision':0,'hashes':[skill['hash']]})
        record=c.post(base+'/records',json={'kind':'outline','title':'长篇细纲','content':{'text':'长篇正文'*50000}}).json()
        with app.state.store.db() as db: db.execute('INSERT INTO settings VALUES(1,?)',(json.dumps({'text':{'url':'http://127.0.0.1/fixture','model':'fixture'}}),))
        sid=c.post(base+'/agent/sessions',json={'stage':'outline','refs':[{'id':record['id'],'version':1}]}).json()['id']
        sent=c.post(base+f'/agent/sessions/{sid}/messages',json={'message':'总结转折','expected_version':0})
        assert sent.status_code==200,sent.text
        deadline=time.monotonic()+3
        while not captured and time.monotonic()<deadline: time.sleep(.01)
        assert len(captured[0])<10000
        assert record['id'] in captured[0]
        assert '先核对人物动机' in captured[0]
        assert skill['hash'] in captured[0]


def test_legacy_checkpoint_lookup_is_explicitly_missing_and_never_creates_a_ledger(tmp_path):
    from fastapi.testclient import TestClient
    from backend.app import create_app
    with TestClient(create_app(tmp_path)) as c:
        pid=c.post('/api/projects',json={'name':'旧记录'}).json()['id'];base=f'/api/projects/{pid}'
        sid=c.post(base+'/agent/sessions',json={'stage':'outline'}).json()['id']
        with c.app.state.store.db() as db:
            db.execute('INSERT INTO agent_runs VALUES(?,?,?,?,?,?,?,?,?,?)',('legacy',pid,sid,'completed','旧请求','旧回复','',None,'then','then'))
        response=c.get(base+'/agent/runs/legacy/checkpoint')
        assert response.status_code==404,response.text
        assert '没有持久调用检查点' in response.json()['detail']
        assert not (tmp_path/'agent'/pid).exists()
        assert c.get(base+'/agent/runs/missing/checkpoint').status_code==404


def test_checkpoint_lookup_runtime_failure_is_bounded_and_does_not_request_a_model(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from backend.app import create_app
    with TestClient(create_app(tmp_path)) as c:
        pid=c.post('/api/projects',json={'name':'只读核对'}).json()['id'];base=f'/api/projects/{pid}'
        sid=c.post(base+'/agent/sessions',json={'stage':'outline'}).json()['id']
        with c.app.state.store.db() as db:
            db.execute('INSERT INTO agent_runs VALUES(?,?,?,?,?,?,?,?,?,?)',('unavailable',pid,sid,'interrupted','旧请求','','',None,'then','then'))
        calls=[];original=c.app.state.pi_runtime.request
        async def broken(command,**payload):
            if command!='checkpoint':return await original(command,**payload)
            calls.append(command);raise RuntimeError('synthetic-private-secret')
        monkeypatch.setattr(c.app.state.pi_runtime,'request',broken)
        response=c.get(base+'/agent/runs/unavailable/checkpoint')
        assert response.status_code==503 and calls==['checkpoint']
        assert 'synthetic-private-secret' not in response.text
        assert not (tmp_path/'agent'/pid).exists()
