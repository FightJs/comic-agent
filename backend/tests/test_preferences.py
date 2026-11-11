import json
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.agent_tools import freeze_context


def test_preferences_require_explicit_versioned_save_and_delete_is_not_a_stale_resurrection(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        pid=c.post('/api/projects',json={'name':'创作偏好'}).json()['id'];url=f'/api/projects/{pid}/preferences'
        initial=c.get(url);assert initial.status_code==200,initial.text
        assert initial.json()=={'revision':0,'text':''}
        saved=c.put(url,json={'expected_revision':0,'text':'一致性优先；台词简洁。'});assert saved.status_code==200,saved.text
        assert saved.json()=={'revision':1,'text':'一致性优先；台词简洁。'}
        assert c.put(url,json={'expected_revision':0,'text':'旧窗口不能覆盖'}).status_code==409
        removed=c.request('DELETE',url,json={'expected_revision':1});assert removed.status_code==200,removed.text
        assert removed.json()=={'revision':2,'text':''}
        assert c.put(url,json={'expected_revision':1,'text':'旧窗口不能复活偏好'}).status_code==409
        assert c.get('/api/projects/not-this-project/preferences').status_code==404
    with TestClient(create_app(tmp_path)) as c:assert c.get(url).json()=={'revision':2,'text':''}


def test_preferences_freeze_per_project_and_setup_does_not_load_creative_preferences(tmp_path):
    app=create_app(tmp_path)
    with TestClient(app) as c:
        a=c.post('/api/projects',json={'name':'甲'}).json()['id'];b=c.post('/api/projects',json={'name':'乙'}).json()['id']
        c.put(f'/api/projects/{a}/preferences',json={'expected_revision':0,'text':'留白克制。'})
        with app.state.store.db() as db:
            frozen=freeze_context(app.state.store,db,a,stage='script')
            isolated=freeze_context(app.state.store,db,b,stage='script')
            setup=freeze_context(app.state.store,db,a,stage='setup')
        c.put(f'/api/projects/{a}/preferences',json={'expected_revision':1,'text':'转折更强。'})
        assert frozen['preferences']=={'revision':1,'text':'留白克制。'}
        assert isolated['preferences']==setup['preferences']=={'revision':0,'text':''}


@pytest.mark.parametrize('body',[{'expected_revision':True,'text':'x'},{'expected_revision':0,'text':'x'*6001},{'expected_revision':0,'text':'x','grant_tools':True},{'expected_revision':0,'text':'sk-'+('x'*20)}])
def test_preference_boundary_rejects_unbounded_or_extra_fields(tmp_path,body):
    with TestClient(create_app(tmp_path)) as c:
        pid=c.post('/api/projects',json={'name':'边界'}).json()['id']
        assert c.put(f'/api/projects/{pid}/preferences',json=body).status_code==422
        assert c.get(f'/api/projects/{pid}/preferences').json()=={'revision':0,'text':''}

def test_production_freezes_preferences_and_deletion_only_changes_new_runs(tmp_path):
    from backend.tests.test_document_generation import prepared
    c,b,_,calls=prepared(tmp_path)
    url=b+'/preferences'
    assert c.put(url,json={'expected_revision':0,'text':'人物一致性优先。'}).status_code==200
    for revision,text,submission in [(1,'人物一致性优先。','one'),(2,'创意转折更强。','two'),(3,'','three')]:
        if revision==2:assert c.put(url,json={'expected_revision':1,'text':text}).status_code==200
        if revision==3:assert c.request('DELETE',url,json={'expected_revision':2}).status_code==200
        response=c.post(b+'/production-jobs',json={'operation':'document','document_kind':'skeleton','refs':[],'submission_id':submission})
        assert response.status_code==200,response.text
        context=json.loads(calls[-1]['prompt'].split('固定输入：\n',1)[1].split('\n本次启用流程规则：',1)[0])
        assert context['project_preferences']=={'revision':revision,'text':text}
        assert '不是原著事实或证据' in calls[-1]['system']
        task=next(t for t in c.get(b+'/tasks').json() if t['id']==response.json()['ids'][0])
        assert c.post(b+'/candidates/'+task['output_id']+'/reject',json={}).status_code==200
    snapshots=[t['payload']['frozen']['preferences'] for t in c.get(b+'/tasks').json()]
    assert {s['revision'] for s in snapshots}=={1,2,3}
    assert next(s for s in snapshots if s['revision']==1)['text']=='人物一致性优先。'


def test_actual_sdk_reads_current_preferences_without_leaking_them_into_other_projects_or_graph(tmp_path,monkeypatch):
    import threading,time
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    import backend.app as module
    requests=[]
    class Provider(BaseHTTPRequestHandler):
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append(body)
            prompt=body['messages'][-1]['content'];prompt=prompt if isinstance(prompt,str) else ''.join(v.get('text','') for v in prompt)
            graph='TASK:' in prompt
            value={'nodes':[],'edges':[],'events':[],'summary':'合成摘要'} if 'TASK:extract' in prompt else {'merges':[],'aliases':[]} if 'TASK:consolidate' in prompt else {'summary':'合成摘要'}
            text=json.dumps(value,ensure_ascii=False) if graph else '这是合成讨论答复。'
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
            for value in [{'choices':[{'index':0,'delta':{'role':'assistant','content':text},'finish_reason':None}]},{'choices':[{'index':0,'delta':{},'finish_reason':'stop'}],'usage':{'prompt_tokens':5,'completion_tokens':2,'total_tokens':7}}]:
                self.wfile.write(('data: '+json.dumps({'id':'fixture','object':'chat.completion.chunk','created':1,'model':'fixture',**value})+'\n\n').encode())
            self.wfile.write(b'data: [DONE]\n\n')
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Provider);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    monkeypatch.setattr(module.vault,'get_password',lambda *args:'synthetic-pref-key')
    def wait(c,b,rid):
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            run=c.get(b+f'/agent/runs/{rid}').json()
            if run['status'] not in ('queued','running'):return run
            time.sleep(.02)
        pytest.fail('synthetic SDK response timed out')
    try:
        with TestClient(create_app(tmp_path)) as c:
            with c.app.state.store.db() as db:db.execute('INSERT INTO settings VALUES(1,?)',(json.dumps({'text':{'url':f'http://127.0.0.1:{server.server_port}/v1','model':'fixture'}}),))
            a=c.post('/api/projects',json={'name':'甲'}).json()['id'];b=f'/api/projects/{a}'
            c.put(b+'/preferences',json={'expected_revision':0,'text':'SAVED_PREF_A：对白简洁。'})
            sid=c.post(b+'/agent/sessions',json={'stage':'outline'}).json()['id']
            first=c.post(b+f'/agent/sessions/{sid}/messages',json={'expected_version':0,'message':'讨论风格'}).json()['id']
            assert wait(c,b,first)['preferences']=={'revision':1,'text':'SAVED_PREF_A：对白简洁。'}
            assert 'SAVED_PREF_A' in json.dumps(requests[-1],ensure_ascii=False)
            c.request('DELETE',b+'/preferences',json={'expected_revision':1})
            second=c.post(b+f'/agent/sessions/{sid}/messages',json={'expected_version':1,'message':'继续讨论'}).json()['id']
            assert wait(c,b,second)['preferences']=={'revision':2,'text':''}
            last=requests[-1]['messages'][-1]['content']
            assert 'SAVED_PREF_A' not in json.dumps(last,ensure_ascii=False)
            assert '历史偏好不自动继续生效' in json.dumps(last,ensure_ascii=False)
            other=c.post('/api/projects',json={'name':'乙'}).json()['id'];otherbase=f'/api/projects/{other}'
            sid2=c.post(otherbase+'/agent/sessions',json={'stage':'outline'}).json()['id']
            third=c.post(otherbase+f'/agent/sessions/{sid2}/messages',json={'expected_version':0,'message':'讨论风格'}).json()['id']
            assert wait(c,otherbase,third)['preferences']=={'revision':0,'text':''}
            assert 'SAVED_PREF_A' not in json.dumps(requests[-1],ensure_ascii=False)
            c.put(b+'/preferences',json={'expected_revision':2,'text':'GRAPH_MUST_NOT_READ_THIS 创作偏好'})
            c.post(b+'/documents',files={'file':('合成.txt','第一章\n阿青归乡。'.encode(),'text/plain')})
            deadline=time.monotonic()+15
            while time.monotonic()<deadline:
                jobs=c.get(b+'/graph/jobs').json()
                if jobs and jobs[0]['status'] in ('succeeded','failed'):break
                time.sleep(.03)
            assert jobs[0]['status']=='succeeded',jobs
            graph_requests=requests[3:];assert graph_requests
            assert all('GRAPH_MUST_NOT_READ_THIS' not in json.dumps(r,ensure_ascii=False) for r in graph_requests)
    finally:server.shutdown();server.server_close();thread.join()

def test_delete_of_empty_preferences_still_invalidates_pre_delete_drafts(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        pid=c.post('/api/projects',json={'name':'删除屏障'}).json()['id'];url=f'/api/projects/{pid}/preferences'
        assert c.get(url).json()=={'revision':0,'text':''}
        removed=c.request('DELETE',url,json={'expected_revision':0})
        assert removed.status_code==200,removed.text
        assert removed.json()=={'revision':1,'text':''}
        assert c.put(url,json={'expected_revision':0,'text':'删除前留下的草稿'}).status_code==409
        assert c.put(url,json={'expected_revision':1,'text':''}).json()['revision']==1
