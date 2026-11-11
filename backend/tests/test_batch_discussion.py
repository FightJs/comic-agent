import json
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.agent_tools import freeze_context


def fixture(tmp_path):
    app=create_app(tmp_path);store=app.state.store
    with store.db() as db:
        db.execute("INSERT INTO projects VALUES('p','项目',0,'t','t')")
        record=store.add(db,'p','script','当前格',{'episode':1,'panel':1,'description':'画面'})
        refs=[{'id':record['id'],'version':1}]
        frozen=freeze_context(store,db,'p',refs,stage='script');frozen.update(stage='script',write_refs=refs)
        db.execute('INSERT INTO agent_sessions VALUES(?,?,?,?,?,?)',('s','p','script',json.dumps(refs),1,'t'))
        db.execute("INSERT INTO agent_runs VALUES('r','p','s','completed','建议','完成的建议','',NULL,'t','t')")
        db.execute('INSERT INTO agent_inputs VALUES(?,?)',('r',json.dumps(frozen)))
    return app,store,record,refs


def test_plan_receipt_is_bound_to_project_completed_run_and_exact_versions(tmp_path):
    from backend.agent import plan_receipt
    _,store,record,refs=fixture(tmp_path)
    with store.db() as db:
        receipt=plan_receipt(store,db,'p','r',refs)
        assert receipt['run_id']=='r' and receipt['reply']=='完成的建议' and receipt['source']=='ai'
        with pytest.raises(HTTPException):plan_receipt(store,db,'p','missing',refs)
        with pytest.raises(HTTPException):plan_receipt(store,db,'p','r',[{'id':record['id'],'version':2}])
        db.execute("UPDATE agent_runs SET status='cancelled' WHERE id='r'")
        with pytest.raises(HTTPException):plan_receipt(store,db,'p','r',refs)


def test_plan_receipt_inherits_mock_tool_reads(tmp_path):
    from backend.agent import plan_receipt
    _,store,_,refs=fixture(tmp_path)
    with store.db() as db:
        db.execute('INSERT INTO agent_tool_calls VALUES(?,?,?,?,?,?)',('r','call','project_query','hash',json.dumps({'source':'mock'}),'t'))
        assert plan_receipt(store,db,'p','r',refs)['source']=='mock'


def test_batch_session_filter_selects_exact_refs_before_limit(tmp_path):
    app,store,record,refs=fixture(tmp_path)
    with store.db() as db:
        for n in range(101):db.execute('INSERT INTO agent_sessions VALUES(?,?,?,?,?,?)',(f'other{n}','p','script','[]',0,'z'))
    with TestClient(app) as client:
        response=client.get('/api/projects/p/agent/sessions',params={'stage':'script','refs':json.dumps(refs)})
        assert response.status_code==200
        assert [r['id'] for r in response.json()]==['s']


def test_batch_sessions_accept_full_300_panel_selection(tmp_path):
    app,store,_,_=fixture(tmp_path)
    with store.db() as db:
        refs=[{'id':store.add(db,'p','script',str(n),{'episode':1,'panel':n+2})['id'],'version':1} for n in range(300)]
    with TestClient(app) as client:
        response=client.post('/api/projects/p/agent/sessions',json={'stage':'script','refs':refs})
        assert response.status_code==200
        assert len(response.json()['refs'])==300
        assert len(client.get('/api/projects/p/agent/sessions',params={'stage':'script','refs':json.dumps(refs)}).json())==1


def test_generation_freezes_ai_discussion_receipts_and_mock_lineage(tmp_path,monkeypatch):
    app,store,_,refs=fixture(tmp_path)
    monkeypatch.setattr(app.state.graph_engine,'config',lambda db:{'url':'http://fixture','model':'fixture','secret':'fixture'})
    async def request(*args,**kwargs):return {'type':'result','data':{'text':json.dumps({'patch':{'description':'候选画面'}})}}
    monkeypatch.setattr(app.state.pi_runtime,'request',request)
    with store.db() as db:db.execute('INSERT INTO agent_tool_calls VALUES(?,?,?,?,?,?)',('r','read','project_query','hash',json.dumps({'source':'mock'}),'t'))
    with TestClient(app) as client:
        assert client.get('/api/projects/p/tasks').json()==[]
        response=client.post('/api/projects/p/production-jobs',json={'operation':'rewrite','refs':refs,'instruction':'完成的建议','agent_run_ids':['r'],'submission_id':'from-reply'})
        assert response.status_code==200,response.text
        tasks=client.get('/api/projects/p/tasks').json()
        assert len(tasks)==1 and tasks[0]['status']=='succeeded'
        assert tasks[0]['payload']['agent_discussions'][0]['run_id']=='r'
        assert tasks[0]['payload']['source']=='mock'
        output=client.get('/api/projects/p/records/'+tasks[0]['output_id']).json()
        assert output['source']=='mock' and output['content']['candidate_for']==refs[0]['id']


def test_batch_package_rewrite_preserves_legacy_manual_full_prompt(tmp_path,monkeypatch):
    app,store,_,_=fixture(tmp_path)
    monkeypatch.setattr(app.state.graph_engine,'config',lambda db:{'url':'http://fixture','model':'fixture','secret':'fixture'})
    async def request(*args,**kwargs):return {'type':'result','data':{'text':json.dumps({'patch':{'shot_prompt':'新分镜段'}})}}
    monkeypatch.setattr(app.state.pi_runtime,'request',request)
    with store.db() as db:package=store.add(db,'p','package','旧生图包',{'episode':1,'panel':1,'batch':1,'prompt':'人工完整提示词','shot_prompt':'旧分镜段'})
    with TestClient(app) as client:
        response=client.post('/api/projects/p/production-jobs',json={'operation':'rewrite','refs':[{'id':package['id'],'version':1}],'instruction':'只优化分镜','submission_id':'legacy-prompt'})
        assert response.status_code==200,response.text
        task=client.get('/api/projects/p/tasks').json()[0]
        assert task['status']=='succeeded',task
        output=client.get('/api/projects/p/records/'+task['output_id']).json()['content']
        assert output['shot_prompt']=='新分镜段'
        assert output['prompt']=='人工完整提示词'
        assert output['prompt_mode']=='override'
