import json
import pytest
from fastapi import HTTPException
from backend.app import create_app
from backend.agent_tools import freeze_context
from backend.store import now,uid


def fixture(tmp_path,stage='style'):
    app=create_app(tmp_path);store=app.state.store
    with store.db() as db:
        db.execute("INSERT INTO projects VALUES('p','方案',0,'t','t')")
        record=store.add(db,'p',stage,'目标图',{'prompt':'旧提示词'})
        frozen=freeze_context(store,db,'p',[{'id':record['id'],'version':1}],stage=stage)
        frozen.update(stage=stage,write_refs=[{'id':record['id'],'version':1}],allowed_tools=['project_query','propose_changes','propose_image'])
        db.execute("INSERT INTO agent_runs VALUES('run','p','session','running','要求','','',NULL,'t','t')")
    return app,record,frozen


def test_image_plan_is_a_non_mutating_proposal_bound_to_the_attached_target(tmp_path):
    from backend.agent_image_plans import propose
    app,record,frozen=fixture(tmp_path)
    with app.state.store.db() as db:
        result=propose(app.state.store,db,'p','run',frozen,{'title':'夜景画风','prompt':'保持线条，改为夜景','target_id':record['id']})
        assert result['status']=='pending'
        assert app.state.store.get(db,'p',record['id'])['version']==1
        assert db.execute('SELECT COUNT(*) FROM image_jobs').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM image_calls').fetchone()[0]==0
        plan=json.loads(db.execute('SELECT content FROM agent_image_plans WHERE id=?',(result['id'],)).fetchone()[0])
        assert plan['target']['version']==1 and plan['prompt']=='保持线条，改为夜景'

@pytest.mark.parametrize('change',['old_tools','wrong_stage','unattached','model','key','url'])
def test_plan_cannot_expand_old_tools_targets_or_provider_permissions(tmp_path,change):
    from backend.agent_image_plans import propose
    app,r,frozen=fixture(tmp_path);body={'title':'图','prompt':'画面','target_id':r['id']}
    if change=='old_tools':frozen.pop('allowed_tools')
    if change=='wrong_stage':frozen['stage']='script'
    if change=='unattached':frozen['write_refs']=[]
    if change=='model':body['model']='arbitrary'
    if change=='key':body['api_key']='synthetic-key'
    if change=='url':body['url']='https://example.invalid/image'
    with app.state.store.db() as db:
        with pytest.raises(HTTPException):propose(app.state.store,db,'p','run',frozen,body)


def test_preview_is_explicit_idempotent_and_keeps_mock_lineage(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from backend.tests.test_image_jobs import fixture as image_fixture
    from backend.agent_image_plans import propose
    app,calls=image_fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'AI生图'}).json()['id'];b=f'/api/projects/{pid}'
        with app.state.store.db() as db:
            frozen=freeze_context(app.state.store,db,pid,stage='style');frozen.update(stage='style',write_refs=[],allowed_tools=['propose_image'],inherited_mock=True)
            db.execute('INSERT INTO agent_runs VALUES(?,?,?,?,?,?,?,?,?,?)',('plan-run',pid,'session','running','要求','','',None,'t','t'))
            result=propose(app.state.store,db,pid,'plan-run',frozen,{'title':'新画风','prompt':'夜景清晰线条'})
        path=b+'/agent/image-plans/'+result['id']
        assert c.post(path+'/preview',json={}).status_code==409 and not calls
        with app.state.store.db() as db:db.execute("UPDATE agent_runs SET status='completed' WHERE id='plan-run'")
        job=c.post(path+'/preview',json={});assert job.status_code==200,job.text
        value=job.json();assert value['status']=='preview' and not calls
        assert value['call']['manifest']['source']=='mock'
        assert c.post(path+'/preview',json={}).json()['id']==value['id']
        assert c.post(b+f"/image-jobs/{value['id']}/start",json={}).status_code==200
        current=c.get(b+f"/image-jobs/{value['id']}").json();assert current['status']=='succeeded' and len(calls)==1
        output=c.get(b+'/records/'+current['output_id']).json();assert not output['adopted'] and output['source']=='mock'
        assert c.get('/api/projects/other/agent/image-plans/'+result['id']).status_code==404
        response=c.post(b+'/image-jobs',json={'kind':'style','title':'x','prompt':'x','submission_id':'forged','agent_plan':{'source':'ai'}})
        assert response.status_code==422


def test_stale_target_plan_cannot_preview_latest_version(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from backend.tests.test_image_jobs import fixture as image_fixture
    from backend.agent_image_plans import propose
    app,calls=image_fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'旧方案'}).json()['id'];b=f'/api/projects/{pid}'
        record=c.post(b+'/records',json={'kind':'style','title':'画风','content':{'prompt':'原图'}}).json()
        with app.state.store.db() as db:
            frozen=freeze_context(app.state.store,db,pid,[{'id':record['id'],'version':1}],stage='style');frozen.update(stage='style',write_refs=[{'id':record['id'],'version':1}],allowed_tools=['propose_image'])
            db.execute('INSERT INTO agent_runs VALUES(?,?,?,?,?,?,?,?,?,?)',('plan-run',pid,'session','running','要求','','',None,'t','t'))
            plan=propose(app.state.store,db,pid,'plan-run',frozen,{'title':'修改','prompt':'新提示词','target_id':record['id']})
            db.execute("UPDATE agent_runs SET status='completed' WHERE id='plan-run'")
        assert c.put(b+'/records/'+record['id'],json={'expected_version':1,'content':{'prompt':'人已改稿'}}).status_code==200
        path=b+'/agent/image-plans/'+plan['id'];response=c.post(path+'/preview',json={})
        assert response.status_code==409 and not calls
        assert c.get(path).json()['plan']['target']['version']==1 and c.get(path).json()['status']=='pending'
        with app.state.store.db() as db:assert db.execute('SELECT COUNT(*) FROM image_calls').fetchone()[0]==0


def test_asset_plan_freezes_confirmed_approved_style(tmp_path,monkeypatch):
    import base64
    from fastapi.testclient import TestClient
    from backend.tests.test_image_jobs import fixture as image_fixture
    from backend.agent_image_plans import propose
    app,calls=image_fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'资产方案'}).json()['id'];b=f'/api/projects/{pid}'
        with app.state.store.db() as db:
            url=app.state.store.file(db,pid,'合成参考.png',base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aN1sAAAAASUVORK5CYII='),'image/png')
            style=app.state.store.add(db,pid,'style','画风',{'url':url,'width':1,'height':1})
        assert c.post(b+f"/records/{style['id']}/reviews",json={'version':1,'decision':'approved','note':'合成审核'}).status_code==200
        assert c.post(b+'/style-selection',json={'record_id':style['id'],'version':1}).status_code==200
        with app.state.store.db() as db:
            frozen=freeze_context(app.state.store,db,pid,stage='asset');frozen.update(stage='asset',write_refs=[],allowed_tools=['propose_image'])
            db.execute('INSERT INTO agent_runs VALUES(?,?,?,?,?,?,?,?,?,?)',('plan-run',pid,'session','running','要求','','',None,'t','t'))
            plan=propose(app.state.store,db,pid,'plan-run',frozen,{'title':'人物','prompt':'人物当前衣装','category':'人物'})
            db.execute("UPDATE agent_runs SET status='completed' WHERE id='plan-run'")
        assert c.post(b+f"/records/{style['id']}/reviews",json={'version':1,'decision':'changes','note':'撤回'}).status_code==200
        assert c.post(b+'/agent/image-plans/'+plan['id']+'/preview',json={}).status_code==409 and not calls


@pytest.mark.parametrize('read_mock_after',[False,True])
def test_real_pi_sdk_proposes_plan_without_image_call_then_human_previews_and_starts(tmp_path,monkeypatch,read_mock_after):
    import threading,time
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    from fastapi.testclient import TestClient
    from backend.tests.test_image_jobs import fixture as image_fixture
    app,image_calls=image_fixture(tmp_path,monkeypatch);model_calls=[];target={}
    class Provider(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));model_calls.append(body)
            receipts=[m for m in body['messages'] if m['role']=='tool'];tool=not receipts
            delta={'role':'assistant','tool_calls':[{'index':0,'id':'plan','type':'function','function':{'name':'propose_image','arguments':json.dumps({'title':'夜景画风','prompt':'保留线条与主体，改为夜景','target_id':target['id']})}}]} if tool else {'role':'assistant','content':'生图方案已保存，未修改原图，尚未调用图像模型。请先核对预览。'}
            if read_mock_after and len(receipts)==1:
                delta={'role':'assistant','tool_calls':[{'index':0,'id':'later-mock','type':'function','function':{'name':'project_query','arguments':json.dumps({'action':'record','id':target['mock_id']})}}]};tool=True
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
            for data,finish in [(delta,None),({},'tool_calls' if tool else 'stop')]:
                chunk={'id':'fixture','object':'chat.completion.chunk','created':1,'model':'fixture','choices':[{'index':0,'delta':data,'finish_reason':finish}]}
                self.wfile.write(('data: '+json.dumps(chunk)+'\n\n').encode())
            self.wfile.write(b'data: [DONE]\n\n')
    server=ThreadingHTTPServer(('127.0.0.1',0),Provider);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with TestClient(app) as c:
            pid=c.post('/api/projects',json={'name':'实际SDK方案'}).json()['id'];b=f'/api/projects/{pid}'
            with app.state.store.db() as db:
                target.update(app.state.store.add(db,pid,'style','原画风',{'prompt':'原提示词'},'manual' if read_mock_after else 'mock'))
                target['mock_id']=app.state.store.add(db,pid,'outline','模拟资料',{'text':'隔离模拟线索'},'mock')['id']
                profiles=json.loads(db.execute('SELECT content FROM settings').fetchone()[0]);profiles['text']={'url':f'http://127.0.0.1:{server.server_port}/v1','model':'fixture'};db.execute('UPDATE settings SET content=?',(json.dumps(profiles),))
            sid=c.post(b+'/agent/sessions',json={'stage':'style','refs':[{'id':target['id'],'version':1}]}).json()['id']
            sent=c.post(b+f'/agent/sessions/{sid}/messages',json={'message':'请按夜景要求重生成原画风，先给方案','expected_version':0});assert sent.status_code==200,sent.text
            deadline=time.monotonic()+15
            while time.monotonic()<deadline:
                run=c.get(b+'/agent/runs/'+sent.json()['id']).json()
                if run['status'] not in ('queued','running'):break
                time.sleep(.03)
            assert run['status']=='completed',run
            assert len(run['image_plans'])==1 and not image_calls
            assert run['checkpoint']['tool_calls']==(2 if read_mock_after else 1)
            assert run['image_plans'][0]['source']=='mock'
            if read_mock_after:assert json.loads([m for m in model_calls[1]['messages'] if m['role']=='tool'][0]['content'])['source']=='ai'
            assert 'propose_image' in [t['function']['name'] for t in model_calls[0]['tools']]
            with app.state.store.db() as db:assert db.execute('SELECT COUNT(*) FROM image_jobs').fetchone()[0]==0
            plan_id=run['image_plans'][0]['id'];job=c.post(b+f'/agent/image-plans/{plan_id}/preview',json={});assert job.status_code==200,job.text
            assert not image_calls and c.get(b+'/records/'+target['id']).json()['version']==1
            jid=job.json()['id'];assert c.post(b+f'/image-jobs/{jid}/start',json={}).status_code==200
            result=c.get(b+f'/image-jobs/{jid}').json();assert result['status']=='succeeded' and len(image_calls)==1
            assert c.get(b+'/records/'+result['output_id']).json()['adopted']==0
            assert c.get(b+'/records/'+result['output_id']).json()['source']=='mock'
    finally:server.shutdown();server.server_close();thread.join()


def test_same_session_mock_history_taints_new_image_plan(tmp_path):
    from backend.agent_image_plans import propose
    app,r,frozen=fixture(tmp_path)
    with app.state.store.db() as db:
        db.execute("INSERT INTO agent_runs VALUES('old','p','session','completed','旧讨论','','',NULL,'s','s')")
        db.execute('INSERT INTO agent_tool_calls VALUES(?,?,?,?,?,?)',('old','read','project_query','hash',json.dumps({'source':'mock'}),'s'))
        plan=propose(app.state.store,db,'p','run',frozen,{'title':'新图','prompt':'从历史讨论继续'})
        assert db.execute('SELECT source FROM agent_image_plans WHERE id=?',(plan['id'],)).fetchone()[0]=='mock'


def test_target_review_change_without_version_change_refuses_preview(tmp_path):
    from backend.agent_image_plans import propose
    from fastapi.testclient import TestClient
    app,r,frozen=fixture(tmp_path)
    with app.state.store.db() as db:
        db.execute('INSERT INTO reviews VALUES(?,?,?,?,?,?,?)',(uid(),r['id'],1,'approved','原批准','manual',now()))
        plan=propose(app.state.store,db,'p','run',frozen,{'title':'重生成','prompt':'夜景','target_id':r['id']})
        db.execute("UPDATE agent_runs SET status='completed' WHERE id='run'")
        db.execute('INSERT INTO reviews VALUES(?,?,?,?,?,?,?)',(uid(),r['id'],1,'changes','已撤回','manual',now()))
    prepared=[]
    def preview(*args,**kwargs):prepared.append(kwargs);return {'id':'should-not-prepare'}
    app.state.image_jobs.preview=preview
    with TestClient(app) as c:
        response=c.post('/api/projects/p/agent/image-plans/'+plan['id']+'/preview',json={})
        assert response.status_code==409,response.text
        assert prepared==[]
    with app.state.store.db() as db:assert db.execute('SELECT COUNT(*) FROM image_jobs').fetchone()[0]==0
