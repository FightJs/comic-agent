import asyncio,json
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from backend.tests.test_production_text import fixture,panel
from backend.production_text import generate


def test_quota_reply_saves_pause_and_original_request_instead_of_provider_failure(tmp_path):
    store,payload=fixture(tmp_path)
    class Runtime:
        async def request(self,command,**kw):
            return {'type':'error','error':{'code':'turn_limit'},'data':{'text':'部分回答','usage':None,'checkpoint':{'run_id':kw['run_id'],'session_id':kw['session_id'],'status':'paused','session_saved':True,'unreturned_models':0,'unresolved_tools':0}}}
    try:asyncio.run(generate(SimpleNamespace(state=SimpleNamespace(pi_runtime=Runtime())),store,'p','task',payload,{'url':'http://fixture','model':'fixture','secret':'not-persisted'}))
    except Exception:pass
    with store.db() as db:
        row=dict(db.execute('SELECT * FROM production_attempts').fetchone())
        assert row['status']=='paused' and row['raw']=='部分回答'
        request=json.loads(db.execute('SELECT content FROM production_requests WHERE attempt_id=?',(row['id'],)).fetchone()[0])
        assert request['session_id']=='production_'+row['id'] and request['attempt']==1
        assert 'not-persisted' not in json.dumps(request)
    assert payload['production_checkpoint']['attempt_id']==row['id']


def api_fixture(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    import backend.app as module
    monkeypatch.setattr(module.vault,'get_password',lambda *a:'synthetic-production-only')
    app=module.create_app(tmp_path);store=app.state.store;calls=[];checkpoints={}
    class Runtime:
        async def request(self,command,**kw):
            if command=='checkpoint':return {'type':'result','data':{'checkpoint':checkpoints[kw['run_id']]}}
            if command=='cancel':return {'type':'result','data':{}}
            calls.append(kw)
            if kw.get('before_dispatch'):kw['before_dispatch']()
            if not kw.get('resume_from') or getattr(app.state,'pause_again',False):
                cp={'run_id':kw['run_id'],'session_id':kw['session_id'],'status':'paused','session_saved':True,'unreturned_models':0,'unresolved_tools':0,'model_requests':20,'model_limit':20,'tool_calls':20,'tool_limit':50,'usage_complete':False,'usage':{'totalTokens':12}}
                checkpoints[kw['run_id']]=cp
                return {'type':'error','error':{'code':'turn_limit'},'data':{'text':'部分输出不能作候选','checkpoint':cp,'usage':None}}
            return {'type':'result','data':{'text':json.dumps({'patch':{'description':'续接后的完整脚本'}}),'usage':{'totalTokens':5}}}
    app.state.pi_runtime=Runtime()
    with store.db() as db:
        db.execute("INSERT INTO projects VALUES('p','生产恢复',0,'t','t')")
        db.execute('INSERT INTO settings VALUES(1,?)',(json.dumps({'text':{'url':'http://fixture/v1','model':'fixture'}}),))
        script=store.add(db,'p','script','第一格',{'episode':1,'panel':1,'description':'原稿'},'mock')
    return app,TestClient(app),script,calls,checkpoints


def submit(c,script):
    response=c.post('/api/projects/p/production-jobs',json={'operation':'rewrite','refs':[{'id':script['id'],'version':1}],'instruction':'修改描述','submission_id':'pause-test'})
    assert response.status_code==200,response.text
    return response.json()['ids'][0]


def test_production_pause_explicit_continuation_is_idempotent_and_not_retry(tmp_path,monkeypatch):
    app,client,script,calls,checkpoints=api_fixture(tmp_path,monkeypatch)
    with client as c:
        tid=submit(c,script);task=c.get('/api/projects/p/tasks').json()[0]
        assert task['status']=='paused'
        aid=task['payload']['production_checkpoint']['attempt_id']
        assert c.post(f'/api/projects/p/tasks/{tid}/retry',json={}).status_code==409
        path=f'/api/projects/p/production-jobs/{tid}/attempts/{aid}/continue'
        assert c.post(path,json={'confirm':False}).status_code==422
        assert c.post(path,json={'confirm':'yes'}).status_code==422
        response=c.post(path,json={'confirm':True});assert response.status_code==200,response.text
        again=c.post(path,json={'confirm':True});assert again.status_code==200 and again.json()['attempt_id']==response.json()['attempt_id']
        assert len(calls)==2 and calls[1]['resume_from']==aid
        assert calls[1]['session_id']==calls[0]['session_id'] and calls[1]['prompt']==calls[0]['prompt']
        final=c.get('/api/projects/p/tasks').json()[0];assert final['status']=='succeeded' and final['source']=='mock'
        output=c.get('/api/projects/p/records/'+final['output_id']).json();assert output['adopted']==0
        receipts=c.get(f'/api/projects/p/production-jobs/{tid}/attempts').json();assert [r['status'] for r in receipts]==['continued','valid']

@pytest.mark.parametrize('change',['input','preferences','provider','unknown','foreign'])
def test_production_continuation_refuses_stale_or_uncertain_state(tmp_path,monkeypatch,change):
    app,client,script,calls,cps=api_fixture(tmp_path,monkeypatch)
    with client as c:
        tid=submit(c,script);task=c.get('/api/projects/p/tasks').json()[0];assert task['status']=='paused'
        aid=task['payload']['production_checkpoint']['attempt_id'];pid='p'
        with app.state.store.db() as db:
            if change=='input':app.state.store.save(db,'p',script['id'],1,{**script['content'],'description':'已变化'})
            if change=='preferences':db.execute("INSERT INTO project_preferences VALUES('p',1,'新偏好')")
            if change=='provider':db.execute('UPDATE settings SET content=?',(json.dumps({'text':{'url':'http://fixture/v1','model':'changed'}}),))
            if change=='foreign':db.execute("INSERT INTO projects VALUES('other','其他项目',0,'t','t')");pid='other'
        if change=='unknown':cps[aid]['unreturned_models']=1
        response=c.post(f'/api/projects/{pid}/production-jobs/{tid}/attempts/{aid}/continue',json={'confirm':True})
        assert response.status_code in (404,409),response.text
        assert len(calls)==1


def test_pause_survives_restart_and_cancel_is_available(tmp_path,monkeypatch):
    import backend.app as module
    from fastapi.testclient import TestClient
    app,client,script,calls,cps=api_fixture(tmp_path,monkeypatch)
    with client as c:
        tid=submit(c,script);task=c.get('/api/projects/p/tasks').json()[0];assert task['status']=='paused'
        aid=task['payload']['production_checkpoint']['attempt_id']
    restarted=module.create_app(tmp_path);restarted.state.pi_runtime=app.state.pi_runtime
    with TestClient(restarted) as c:
        assert len(calls)==1
        assert c.get('/api/projects/p/tasks').json()[0]['status']=='paused'
        assert c.post(f'/api/projects/p/production-jobs/{tid}/cancel',json={}).status_code==200
        assert c.post(f'/api/projects/p/production-jobs/{tid}/attempts/{aid}/continue',json={'confirm':True}).status_code==409
        assert len(calls)==1


def test_repeated_pause_never_starts_another_segment_without_confirmation(tmp_path,monkeypatch):
    app,client,script,calls,cps=api_fixture(tmp_path,monkeypatch)
    with client as c:
        tid=submit(c,script);aid=c.get('/api/projects/p/tasks').json()[0]['payload']['production_checkpoint']['attempt_id']
        app.state.pause_again=True
        first=c.post(f'/api/projects/p/production-jobs/{tid}/attempts/{aid}/continue',json={'confirm':True});assert first.status_code==200,first.text
        current=c.get('/api/projects/p/tasks').json()[0];assert current['status']=='paused' and len(calls)==2
        child=current['payload']['production_checkpoint']['attempt_id'];assert child!=aid
        assert c.post(f'/api/projects/p/production-jobs/{tid}/attempts/{aid}/continue',json={'confirm':True}).json()['attempt_id']==child
        assert len(calls)==2
        app.state.pause_again=False
        assert c.post(f'/api/projects/p/production-jobs/{tid}/attempts/{child}/continue',json={'confirm':True}).status_code==200
        assert len(calls)==3 and calls[2]['resume_from']==child
        receipts=c.get(f'/api/projects/p/production-jobs/{tid}/attempts').json();assert [r['attempt'] for r in receipts]==[1,1,1]


def test_actual_pi_sdk_production_quota_restart_and_continuation(tmp_path,monkeypatch):
    import threading
    from http.server import ThreadingHTTPServer
    from scripts.pi_review_server import Provider
    from fastapi.testclient import TestClient
    import backend.app as module
    requests=[]
    class Counted(Provider):
        def log_message(self,*args):pass
        def do_POST(self):requests.append(self.path);super().do_POST()
    provider=ThreadingHTTPServer(('127.0.0.1',0),Counted);thread=threading.Thread(target=provider.serve_forever,daemon=True);thread.start()
    monkeypatch.setattr(module.vault,'get_password',lambda *args:'synthetic-sdk-production-key')
    app=module.create_app(tmp_path)
    try:
        with TestClient(app) as c:
            p=c.post('/api/projects',json={'name':'SDK生产额度'}).json()['id'];base=f'/api/projects/{p}'
            with app.state.store.db() as db:
                db.execute('INSERT INTO settings VALUES(1,?)',(json.dumps({'text':{'url':f'http://127.0.0.1:{provider.server_port}/v1','model':'fixture'}}),))
                script=app.state.store.add(db,p,'script','第一格',{'episode':1,'panel':1,'description':'不变原稿'},'mock')
            sent=c.post(base+'/production-jobs',json={'operation':'rewrite','refs':[{'id':script['id'],'version':1}],'instruction':'【生产额度暂停验收】只改本格描述','submission_id':'real-pause'});assert sent.status_code==200,sent.text
            tid=sent.json()['ids'][0];task=c.get(base+'/tasks').json()[0]
            assert task['status']=='paused',task
            aid=task['payload']['production_checkpoint']['attempt_id'];assert len(requests)==20
            assert task['payload']['production_checkpoint']['model_requests']==20
        with TestClient(module.create_app(tmp_path)) as c:
            assert c.get(base+'/tasks').json()[0]['status']=='paused' and len(requests)==20
            response=c.post(base+f'/production-jobs/{tid}/attempts/{aid}/continue',json={'confirm':True});assert response.status_code==200,response.text
            final=c.get(base+'/tasks').json()[0];assert final['status']=='succeeded',final
            assert len(requests)==21
            output=c.get(base+'/records/'+final['output_id']).json();assert not output['adopted'] and output['source']=='mock'
            assert '【隔离生产续接】' in output['content']['description']
            assert c.get(base+'/records/'+script['id']).json()['version']==1
            parent=c.get(base+f'/production-jobs/{tid}/attempts').json()[0]
            assert parent['status']=='continued' and parent['checkpoint']['session_saved']
    finally:provider.shutdown();provider.server_close();thread.join()


def test_continuing_second_structural_attempt_does_not_grant_another_repair(tmp_path):
    from backend import production_resume
    from backend.store import dump,now
    store,payload=fixture(tmp_path);calls=[]
    class Runtime:
        async def request(self,command,**kw):
            calls.append(kw)
            if len(calls)==2:
                return {'type':'error','error':{'code':'turn_limit'},'data':{'checkpoint':{'run_id':kw['run_id'],'session_id':kw['session_id'],'status':'paused','session_saved':True,'unreturned_models':0,'unresolved_tools':0}}}
            return {'type':'result','data':{'text':'invalid json','usage':None}}
    app=SimpleNamespace(state=SimpleNamespace(pi_runtime=Runtime()));config={'url':'http://fixture','model':'fixture','secret':'synthetic'}
    with pytest.raises(production_resume.ProductionPaused):asyncio.run(generate(app,store,'p','task',payload,config))
    parent=payload['production_checkpoint']['attempt_id']
    with store.db() as db:
        compiled=production_resume.request(db,parent);assert compiled['attempt']==2
        db.execute('INSERT INTO production_attempts VALUES(?,?,?,?,?,?,?)',('child','task',2,'queued','',None,now()))
        db.execute('INSERT INTO production_requests VALUES(?,?)',('child',dump(compiled)))
    payload['production_resume']={'parent_id':parent,'child_id':'child'}
    with pytest.raises(ValueError):asyncio.run(generate(app,store,'p','task',payload,config))
    assert len(calls)==3 and calls[2]['prompt']==calls[1]['prompt'] and calls[2]['system']==calls[1]['system']
    with store.db() as db:assert [r[0] for r in db.execute('SELECT attempt FROM production_attempts ORDER BY created')]==[1,2,2]


def test_revoked_reference_approval_or_adoption_blocks_resume_even_without_version_change(tmp_path):
    from backend import production_resume
    from backend.agent_tools import freeze_context
    from backend.store import uid,now
    store,payload=fixture(tmp_path)
    from backend.app import create_app
    store=create_app(tmp_path).state.store
    # A fixed asset used by text packaging must remain adopted and approved.
    with store.db() as db:
        asset=store.add(db,'p','asset','人物参考',{'description':'已核定人物'})
        db.execute('INSERT INTO reviews VALUES(?,?,?,?,?,?,?)',(uid(),asset['id'],1,'approved','合成审核','manual',now()))
        payload['assets']=[store.get(db,'p',asset['id'])];payload['frozen']=freeze_context(store,db,'p',stage='script')
        production_resume.validate(store,db,'p',payload,lambda *a:False)
        db.execute('INSERT INTO reviews VALUES(?,?,?,?,?,?,?)',(uid(),asset['id'],1,'changes','撤回批准','manual',now()))
    with store.db() as db:
        with pytest.raises(HTTPException):production_resume.validate(store,db,'p',payload,lambda *a:False)
    with store.db() as db:
        db.execute('DELETE FROM reviews WHERE record_id=? AND decision=?',(asset['id'],'changes'))
        db.execute('UPDATE records SET adopted=0 WHERE id=?',(asset['id'],))
    with store.db() as db:
        with pytest.raises(HTTPException):production_resume.validate(store,db,'p',payload,lambda *a:False)
