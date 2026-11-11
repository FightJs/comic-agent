import json
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.store import dump


def fixture(tmp_path):
    app=create_app(tmp_path);c=TestClient(app)
    pid=c.post('/api/projects',json={'name':'选段隔离'}).json()['id'];b=f'/api/projects/{pid}'
    r=c.post(b+'/records',json={'kind':'outline','title':'选段正文','content':{'html':'<h2>开头😀</h2><p>重复<b>文字</b>，重复文字。</p>','keep':'不得改变'}}).json()
    return c,b,r


def session(c,b,r,**overrides):
    body={'stage':'outline','refs':[{'id':r['id'],'version':1}],'selection':{'start':9,'end':13,'text':'重复文字'}}
    body.update(overrides)
    return c.post(b+'/agent/sessions',json=body)


def proposal(c,b,r):
    from backend.agent_changes import propose
    s=session(c,b,r);assert s.status_code==200,s.text
    sid=s.json()['id'];store=c.app.state.store
    with store.db() as db:
        frozen={'stage':'outline','write_refs':[{'id':r['id'],'version':1}],'text_selection':s.json()['selection']}
        db.execute('INSERT INTO agent_runs VALUES(?,?,?,?,?,?,?,?,?,?)',('selection-run',r['project_id'],sid,'running','局部改写','','',None,'now','now'))
        value=propose(store,db,r['project_id'],'selection-run',frozen,{'title':'只改第二处','changes':[{'target':'record','id':r['id'],'patch':{'text':'新的😀词'}}]})
        db.execute("UPDATE agent_runs SET status='completed',reply='只提出候选' WHERE id='selection-run'")
    return value['id'],frozen


def test_selection_is_exact_utf16_range_and_hidden_from_whole_document_sessions(tmp_path):
    c,b,r=fixture(tmp_path)
    response=session(c,b,r);assert response.status_code==200,response.text
    value=response.json();assert value['selection']=={'start':9,'end':13,'text':'重复文字'}
    assert c.get(b+'/agent/sessions?stage=outline').json()==[]
    assert c.get(b+'/agent/sessions?stage=outline&selection=true').json()[0]['id']==value['id']
    assert c.put(b+f"/agent/sessions/{value['id']}/refs",json={'expected_version':0,'refs':[]}).status_code==409


@pytest.mark.parametrize('selection',[{'start':10,'end':14,'text':'重复文字'},{'start':3,'end':4,'text':'😀'},{'start':9,'end':13,'text':'不是原文'},{'start':9,'end':True,'text':'重复文字'},{'start':9,'end':13,'text':'重复文字','html':'<p>任意</p>'}])
def test_invalid_selection_cannot_be_frozen(tmp_path,selection):
    c,b,r=fixture(tmp_path)
    assert session(c,b,r,selection=selection).status_code==422


def test_model_cannot_escape_selection_scope_and_generic_adoption_is_blocked(tmp_path):
    from backend.agent_changes import propose
    c,b,r=fixture(tmp_path);pid=r['project_id'];proposal_id,frozen=proposal(c,b,r)
    with c.app.state.store.db() as db:
        db.execute("UPDATE agent_runs SET status='running' WHERE id='selection-run'")
        for patch in [{'text':'候选','html':'额外字段'},{'description':'绕开正文'}]:
            with pytest.raises(HTTPException):propose(c.app.state.store,db,pid,'selection-run',frozen,{'title':'不允许','changes':[{'target':'record','id':r['id'],'patch':patch}]})
        db.execute("UPDATE agent_runs SET status='completed' WHERE id='selection-run'")
    assert c.post(b+f'/agent/proposals/{proposal_id}/adopt',json={}).status_code==409
    assert c.get(b+'/records/'+r['id']).json()['version']==1


def test_explicit_selection_adoption_preserves_outside_text_and_metadata_and_is_idempotent(tmp_path):
    c,b,r=fixture(tmp_path);p,_=proposal(c,b,r)
    html='<h2>开头😀</h2><p>重复<strong>文字</strong>，<mark>新的😀词</mark>。</p>'
    url=b+f'/agent/proposals/{p}/apply-selection'
    response=c.post(url,json={'expected_version':1,'html':html});assert response.status_code==200,response.text
    saved=response.json();assert saved['version']==2 and saved['source']=='ai' and saved['review']=='pending'
    assert saved['content']['html']==html and saved['content']['keep']=='不得改变'
    assert saved['content']['ai_run_id']=='selection-run'
    assert c.post(url,json={'expected_version':1,'html':html}).json()['version']==2
    assert len(c.get(b+'/records/'+r['id']+'/versions').json())==2


@pytest.mark.parametrize('change',['outside','version','run'])
def test_stale_or_outside_selection_change_never_writes(tmp_path,change):
    c,b,r=fixture(tmp_path);p,_=proposal(c,b,r)
    html='<h2>开头😀</h2><p>重复<b>文字</b>，新的😀词。</p>'
    if change=='outside':html=html.replace('开头','偷偷改外部')
    if change=='version':c.put(b+'/records/'+r['id'],json={'expected_version':1,'content':{'html':'<p>人工新版</p>'}})
    if change=='run':
        with c.app.state.store.db() as db:db.execute("UPDATE agent_runs SET status='cancelled' WHERE id='selection-run'")
    response=c.post(b+f'/agent/proposals/{p}/apply-selection',json={'expected_version':1,'html':html})
    assert response.status_code==409,response.text
    assert c.get(b+'/records/'+r['id']).json()['version']==(2 if change=='version' else 1)


def test_actual_pi_sdk_selection_proposal_and_explicit_adoption(tmp_path,monkeypatch):
    import threading
    from http.server import ThreadingHTTPServer
    import backend.app as module
    from scripts.pi_review_server import Provider
    from backend.tests.test_agent_continue import wait
    server=ThreadingHTTPServer(('127.0.0.1',0),Provider);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    monkeypatch.setattr(module.vault,'get_password',lambda *args:'synthetic-selection-key')
    try:
        with TestClient(create_app(tmp_path)) as c:
            pid=c.post('/api/projects',json={'name':'SDK选段'}).json()['id'];b=f'/api/projects/{pid}'
            r=c.post(b+'/records',json={'kind':'outline','title':'重复文本','source':'mock','content':{'html':'<h2>开头😀</h2><p>重复<b>文字</b>，重复文字。</p>'}}).json()
            with c.app.state.store.db() as db:db.execute('INSERT INTO settings VALUES(1,?)',(dump({'text':{'url':f'http://127.0.0.1:{server.server_port}/v1','model':'fixture'}}),))
            sid=session(c,b,r).json()['id']
            sent=c.post(b+f'/agent/sessions/{sid}/messages',json={'expected_version':0,'message':'【选段验收】只改第二处'});assert sent.status_code==200,sent.text
            result=wait(c,b,sent.json()['id']);assert result['status']=='completed',result
            assert len(result['proposals'])==1 and result['proposals'][0]['source']=='mock'
            assert c.get(b+'/records/'+r['id']).json()['version']==1
            p=result['proposals'][0]['id']
            detail=c.get(b+f'/agent/proposals/{p}').json();assert detail['changes'][0]['before']=={'text':'重复文字'}
            html='<h2>开头😀</h2><p>重复<strong>文字</strong>，【隔离选段候选】保留动机😀。</p>'
            applied=c.post(b+f'/agent/proposals/{p}/apply-selection',json={'expected_version':1,'html':html})
            assert applied.status_code==200,applied.text
            assert applied.json()['source']=='mock' and applied.json()['version']==2
            assert c.get(b+'/tasks').json()==[]
    finally:server.shutdown();server.server_close();thread.join()


@pytest.mark.parametrize('change',[None,'not-an-object',{'target':'record','id':'ignored','patch':None}])
def test_malformed_selection_tool_changes_are_rejected_without_host_crash(tmp_path,change):
    from backend.agent_changes import propose
    c,b,r=fixture(tmp_path);_,frozen=proposal(c,b,r)
    if isinstance(change,dict):change['id']=r['id']
    with c.app.state.store.db() as db:
        db.execute("UPDATE agent_runs SET status='running' WHERE id='selection-run'")
        with pytest.raises(HTTPException):propose(c.app.state.store,db,r['project_id'],'selection-run',frozen,{'title':'畸形输入','changes':[change]})


def test_actual_pi_sdk_selection_quota_continuation_keeps_the_same_scope(tmp_path,monkeypatch):
    import threading
    from http.server import ThreadingHTTPServer
    import backend.app as module
    from scripts.pi_review_server import Provider
    from backend.tests.test_agent_continue import wait
    server=ThreadingHTTPServer(('127.0.0.1',0),Provider);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    monkeypatch.setattr(module.vault,'get_password',lambda *args:'synthetic-selection-continue-key')
    try:
        with TestClient(create_app(tmp_path)) as c:
            pid=c.post('/api/projects',json={'name':'SDK选段续接'}).json()['id'];b=f'/api/projects/{pid}'
            r=c.post(b+'/records',json={'kind':'outline','title':'重复文本','content':{'html':'<h2>开头😀</h2><p>重复<b>文字</b>，重复文字。</p>'}}).json()
            with c.app.state.store.db() as db:db.execute('INSERT INTO settings VALUES(1,?)',(dump({'text':{'url':f'http://127.0.0.1:{server.server_port}/v1','model':'fixture'}}),))
            sid=session(c,b,r).json()['id']
            parent=c.post(b+f'/agent/sessions/{sid}/messages',json={'expected_version':0,'message':'【额度暂停验收】只询问选段'}).json()['id']
            assert wait(c,b,parent)['status']=='paused'
            response=c.post(b+f'/agent/runs/{parent}/continue',json={'expected_version':1,'confirm':True});assert response.status_code==200,response.text
            child=response.json()['id'];final=wait(c,b,child)
            assert final['status']=='completed' and final['checkpoint']['parent_run_id']==parent
            assert final['checkpoint']['model_requests']==1
            with c.app.state.store.db() as db:
                fixed=[json.loads(db.execute('SELECT manifest FROM agent_inputs WHERE run_id=?',(rid,)).fetchone()[0]) for rid in (parent,child)]
                assert fixed[0]['text_selection']==fixed[1]['text_selection']=={'start':9,'end':13,'text':'重复文字'}
                assert fixed[0]['write_refs']==fixed[1]['write_refs']==[{'id':r['id'],'version':1}]
            assert c.get(b+'/records/'+r['id']).json()['version']==1
            assert c.get(b+'/tasks').json()==[]
    finally:server.shutdown();server.server_close();thread.join()
