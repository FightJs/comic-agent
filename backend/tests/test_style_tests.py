import json
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from backend.agent_tools import freeze_context
from backend.graph_documents import import_document
from backend.store import now,uid,dump
from backend.tests.test_image_jobs import fixture as image_fixture


def setup(app):
    store=app.state.store
    with store.db() as db:
        db.execute("INSERT INTO projects VALUES('p','三套画风隔离',0,'t','t')")
        doc=import_document(store,db,'p','合成小说.txt','第一章\n林秋在故乡街头遇见沈宁，并接过密信。'.encode())
        outline=store.add(db,'p','outline','已审核细纲',{'text':'林秋在故乡街头接过密信。'})
        db.execute('INSERT INTO reviews VALUES(?,?,?,?,?,?,?)',(uid(),outline['id'],1,'approved','合成批准','manual',now()))
        frozen=freeze_context(store,db,'p',stage='style');frozen.update(stage='style',write_refs=[],allowed_tools=['project_query','propose_changes','propose_image','propose_style_tests'],original_selection=None)
        db.execute("INSERT INTO agent_runs VALUES('run','p','session','running','三套要求','','',NULL,'t','t')")
        db.execute('INSERT INTO agent_inputs VALUES(?,?)',('run',dump(frozen)))
    body={'title':'归乡画风测试','outline_id':outline['id'],'representative':{'character':'林秋','appearance':'成年，深色外套','scene':'故乡街头','setting':'雨夜，街灯照亮石板路','action':'接过密信并望向沈宁'},'source_ranges':[{'document_id':doc['id'],'parse_version':doc['parse_version'],'start':0,'end':len('第一章\n林秋在故乡街头遇见沈宁，并接过密信。')}], 'directions':[{'name':name,'line':line,'proportions':'自然人体比例','color':'低饱和配色','shadow':'简化平涂阴影'} for name,line in [('清晰线条','均匀清晰线条'),('细腻线条','细线与局部排线'),('粗犷线条','粗细变化与大块明暗')]]}
    return frozen,body,outline


def test_fixed_trio_is_atomic_data_only_and_previews_keep_shared_input(tmp_path,monkeypatch):
    from backend.style_tests import propose
    app,calls=image_fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        frozen,body,outline=setup(app)
        with app.state.store.db() as db:
            result=propose(app.state.store,db,'p','run',frozen,body)
            assert db.execute('SELECT COUNT(*) FROM agent_image_plans').fetchone()[0]==3
            assert db.execute('SELECT COUNT(*) FROM image_calls').fetchone()[0]==0
            db.execute("UPDATE agent_runs SET status='completed' WHERE id='run'")
        group=c.get('/api/projects/p/agent/style-tests/'+result['id']).json()
        assert len(group['plans'])==3 and group['test']['representative']==body['representative']
        assert not calls
        assert c.get('/api/projects/other/agent/style-tests/'+result['id']).status_code==404
        for index,plan in enumerate(group['plans']):
            prompt=plan['plan']['prompt']
            assert all(value in prompt for value in body['representative'].values())
            assert all(value in prompt for value in body['directions'][index].values())
            assert '多视角' in prompt and '表情' in prompt and '二维' in prompt
            path='/api/projects/p/agent/image-plans/'+plan['id']+'/preview'
            preview=c.post(path,json={});assert preview.status_code==200,preview.text
            job=preview.json();assert job['status']=='preview' and not calls
            assert c.post(path,json={}).json()['id']==job['id']
        first=group['plans'][0]
        job=c.post('/api/projects/p/agent/image-plans/'+first['id']+'/preview',json={}).json()
        assert c.post('/api/projects/p/image-jobs/'+job['id']+'/start',json={}).status_code==200
        result=c.get('/api/projects/p/image-jobs/'+job['id']).json()
        output=c.get('/api/projects/p/records/'+result['output_id']).json()
        assert len(calls)==1 and output['adopted']==0
        assert output['content']['style_test_id']==group['id']
        assert output['content']['style_option']=='A'
        assert output['content']['representative_set']==body['representative']
        assert output['content']['style_features']==body['directions'][0]


@pytest.mark.parametrize('change',['old_tools','stage','outline_unapproved','bad_character','foreign_source','duplicate_direction','extra_key'])
def test_trio_rejects_unproven_or_expanded_inputs_without_partial_plans(tmp_path,monkeypatch,change):
    from backend.style_tests import propose
    app,_=image_fixture(tmp_path,monkeypatch);frozen,body,outline=setup(app)
    if change=='old_tools':frozen['allowed_tools']=True
    if change=='stage':frozen['stage']='asset'
    if change=='outline_unapproved':
        with app.state.store.db() as db:db.execute('DELETE FROM reviews WHERE record_id=?',(outline['id'],))
    if change=='bad_character':body['representative']['character']='无原文人物'
    if change=='foreign_source':body['source_ranges'][0]['document_id']='other'
    if change=='duplicate_direction':body['directions'][1]=body['directions'][0]
    if change=='extra_key':body['api_key']='synthetic-key'
    with app.state.store.db() as db:
        with pytest.raises(HTTPException):propose(app.state.store,db,'p','run',frozen,body)
        assert db.execute('SELECT COUNT(*) FROM agent_image_plans').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM image_calls').fetchone()[0]==0


@pytest.mark.parametrize('change',['outline','review','preferences','source_selection'])
def test_fixed_sources_are_rechecked_after_preview_and_block_payment(tmp_path,monkeypatch,change):
    from backend.style_tests import propose
    app,calls=image_fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        frozen,body,outline=setup(app)
        with app.state.store.db() as db:
            group=propose(app.state.store,db,'p','run',frozen,body)
            db.execute("UPDATE agent_runs SET status='completed' WHERE id='run'")
        plans=c.get('/api/projects/p/agent/style-tests/'+group['id']).json()['plans']
        job=c.post('/api/projects/p/agent/image-plans/'+plans[0]['id']+'/preview',json={}).json()
        if change=='outline':c.put('/api/projects/p/records/'+outline['id'],json={'expected_version':1,'content':{'text':'新细纲'}})
        elif change=='review':c.post('/api/projects/p/records/'+outline['id']+'/reviews',json={'version':1,'decision':'changes','note':'撤回合成审核'})
        elif change=='preferences':c.put('/api/projects/p/preferences',json={'expected_revision':0,'text':'新创作偏好'})
        else:
            with app.state.store.db() as db:db.execute("INSERT INTO graph_source VALUES('p','changed',1,1)")
        response=c.post('/api/projects/p/image-jobs/'+job['id']+'/start',json={})
        assert response.status_code==409,response.text
        assert not calls
        assert c.post('/api/projects/p/agent/image-plans/'+plans[1]['id']+'/preview',json={}).status_code==409
        assert c.get('/api/projects/p/agent/style-tests/'+group['id']).json()['stale'] is True


@pytest.mark.parametrize('late_mock',[False,True])
def test_real_sdk_proposes_a_trio_from_source_without_image_calls(tmp_path,monkeypatch,late_mock):
    import threading,time
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    app,calls=image_fixture(tmp_path,monkeypatch);requests=[];expected={}
    class Provider(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))));n=len(requests)
            actions=[('project_query',{'action':'source','id':expected['source_ranges'][0]['document_id']}),('project_query',{'action':'record','id':expected['outline_id']}),('propose_style_tests',expected)]
            if late_mock:actions.append(('project_query',{'action':'record','id':mock_record['id']}))
            delta={'role':'assistant','tool_calls':[{'index':0,'id':'style-test-'+str(n),'type':'function','function':{'name':actions[n-1][0],'arguments':json.dumps(actions[n-1][1],ensure_ascii=False)}}]} if n<=len(actions) else {'role':'assistant','content':'三套测试方案已保存，尚未生图，请核对。'}
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
            for chunk in [{'choices':[{'index':0,'delta':delta,'finish_reason':None}]},{'choices':[{'index':0,'delta':{},'finish_reason':'tool_calls' if n<=len(actions) else 'stop'}]}]:
                self.wfile.write(('data: '+json.dumps({'id':'fixture','object':'chat.completion.chunk','created':1,'model':'fixture',**chunk})+'\n\n').encode())
            self.wfile.write(b'data: [DONE]\n\n')
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Provider);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with TestClient(app) as c:
            frozen,body,outline=setup(app);expected.update(body)
            with app.state.store.db() as db:mock_record=app.state.store.add(db,'p','style','模拟参考',{'prompt':'模拟风格'},'mock')
            with app.state.store.db() as db:
                settings=json.loads(db.execute('SELECT content FROM settings WHERE id=1').fetchone()[0]);settings['text']={'url':f'http://127.0.0.1:{server.server_port}/v1','model':'fixture'};db.execute('UPDATE settings SET content=? WHERE id=1',(dump(settings),))
            sid=c.post('/api/projects/p/agent/sessions',json={'stage':'style'}).json()['id']
            result=c.post('/api/projects/p/agent/sessions/'+sid+'/messages',json={'expected_version':0,'message':'请提出同主角同场景三套画风方案'});assert result.status_code==200,result.text
            rid=result.json()['id'];deadline=time.monotonic()+15
            while time.monotonic()<deadline:
                run=c.get('/api/projects/p/agent/runs/'+rid).json()
                if run['status'] not in ('queued','running'):break
                time.sleep(.02)
            assert run['status']=='completed',run
            assert len(run['style_tests'])==1,run
            assert run['image_plans']==[] and not calls
            assert run['checkpoint']['tool_calls']==(4 if late_mock else 3) and run['checkpoint']['unresolved_tools']==0
            assert run['checkpoint']['model_requests']==(5 if late_mock else 4)
            group=c.get('/api/projects/p/agent/style-tests/'+run['style_tests'][0]['id']).json()
            assert len(group['plans'])==3
            assert group['source']==('mock' if late_mock else 'ai')
            assert all(p['source']==group['source'] for p in group['plans'])
            assert all('propose_style_tests' in [t['function']['name'] for t in request['tools']] for request in requests)
            assert '故乡街头' in json.dumps(requests[-1],ensure_ascii=False)
    finally:server.shutdown();server.server_close();thread.join()


def test_partial_trio_failure_rolls_back_all_three_plans(tmp_path,monkeypatch):
    from backend import style_tests,agent_image_plans
    app,_=image_fixture(tmp_path,monkeypatch);frozen,body,_=setup(app)
    original=agent_image_plans.propose;count=0
    def fail_second(*args,**kwargs):
        nonlocal count
        count+=1
        if count==2:raise HTTPException(422,'合成第二套失败')
        return original(*args,**kwargs)
    monkeypatch.setattr(agent_image_plans,'propose',fail_second)
    with app.state.store.db() as db:
        with pytest.raises(HTTPException):style_tests.propose(app.state.store,db,'p','run',frozen,body)
        assert db.execute('SELECT COUNT(*) FROM agent_image_plans').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM style_test_sets').fetchone()[0]==0


def test_late_return_preserves_pixels_but_cannot_adopt_under_changed_basis(tmp_path,monkeypatch):
    from backend.style_tests import propose
    import httpx
    app,calls=image_fixture(tmp_path,monkeypatch);original=app.state.image_provider.transport
    with TestClient(app) as c:
        frozen,body,outline=setup(app)
        with app.state.store.db() as db:
            result=propose(app.state.store,db,'p','run',frozen,body);db.execute("UPDATE agent_runs SET status='completed' WHERE id='run'")
        group=c.get('/api/projects/p/agent/style-tests/'+result['id']).json()
        job=c.post('/api/projects/p/agent/image-plans/'+group['plans'][0]['id']+'/preview',json={}).json()
        def changed(request):
            with app.state.store.db() as db:app.state.store.save(db,'p',outline['id'],1,{'text':'合成晚到前改稿'})
            return original.handle_request(request)
        app.state.image_provider.transport=httpx.MockTransport(changed)
        assert c.post('/api/projects/p/image-jobs/'+job['id']+'/start',json={}).status_code==200
        result=c.get('/api/projects/p/image-jobs/'+job['id']).json()
        assert result['status']=='succeeded' and len(calls)==1 and result['call']['result']['url']
        output=c.get('/api/projects/p/records/'+result['output_id']).json()
        assert output['content']['input_stale'] and not output['adopted']
        assert c.post('/api/projects/p/candidates/'+output['id']+'/adopt',json={}).status_code==409
        assert c.post('/api/projects/p/image-jobs/'+job['id']+'/recover',json={}).json()['id']==job['id']
        assert len(calls)==1


def test_basis_change_while_waiting_for_image_capacity_blocks_supplier_dispatch(tmp_path,monkeypatch):
    from backend.style_tests import propose
    import threading,time
    app,calls=image_fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        frozen,body,outline=setup(app)
        with app.state.store.db() as db:
            group=propose(app.state.store,db,'p','run',frozen,body);db.execute("UPDATE agent_runs SET status='completed' WHERE id='run'")
        plan=c.get('/api/projects/p/agent/style-tests/'+group['id']).json()['plans'][0]
        job=c.post('/api/projects/p/agent/image-plans/'+plan['id']+'/preview',json={}).json()
        pool=app.state.capacity.pools['image'];c.portal.call(pool.acquire)
        responses=[]
        thread=threading.Thread(target=lambda:responses.append(c.post('/api/projects/p/image-jobs/'+job['id']+'/start',json={})))
        thread.start()
        try:
            deadline=time.monotonic()+10
            while time.monotonic()<deadline:
                if c.get('/api/runtime/limits').json()['usage']['image']['waiting']==1:break
                time.sleep(.02)
            else:pytest.fail('style image did not wait for shared capacity')
            assert not calls
            assert c.post('/api/projects/p/records/'+outline['id']+'/reviews',json={'version':1,'decision':'changes','note':'排队期间撤销合成审核'}).status_code==200
        finally:c.portal.call(pool.release)
        thread.join(timeout=10);assert not thread.is_alive()
        assert responses[0].status_code==200
        assert c.get('/api/projects/p/image-jobs/'+job['id']).json()['status']=='blocked'
        assert not calls


def test_ordinary_regeneration_does_not_claim_the_old_style_test_group(tmp_path,monkeypatch):
    from backend.style_tests import propose
    app,calls=image_fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        frozen,body,outline=setup(app)
        with app.state.store.db() as db:
            group=propose(app.state.store,db,'p','run',frozen,body);db.execute("UPDATE agent_runs SET status='completed' WHERE id='run'")
        plan=c.get('/api/projects/p/agent/style-tests/'+group['id']).json()['plans'][0]
        job=c.post('/api/projects/p/agent/image-plans/'+plan['id']+'/preview',json={}).json()
        c.post('/api/projects/p/image-jobs/'+job['id']+'/start',json={})
        result=c.get('/api/projects/p/image-jobs/'+job['id']).json()
        target=c.post('/api/projects/p/candidates/'+result['output_id']+'/adopt',json={}).json()
        ordinary=c.post('/api/projects/p/image-jobs',json={'kind':'style','title':'自由重生成','prompt':'全新单图，不是旧三套试验板','target':{'id':target['id'],'version':target['version']},'submission_id':'ordinary-regenerate'}).json()
        c.post('/api/projects/p/image-jobs/'+ordinary['id']+'/start',json={})
        value=c.get('/api/projects/p/image-jobs/'+ordinary['id']).json()
        output=c.get('/api/projects/p/records/'+value['output_id']).json()
        assert len(calls)==2
        assert not any(k in output['content'] for k in ('style_test_id','style_option','style_features','representative_set'))


def test_source_reparse_after_discussion_freeze_cannot_be_rebound_during_proposal(tmp_path,monkeypatch):
    from backend.style_tests import propose
    from backend.graph_documents import get_document,save_parse
    app,_=image_fixture(tmp_path,monkeypatch);frozen,body,_=setup(app)
    with app.state.store.db() as db:
        ref=body['source_ranges'][0];doc=get_document(app.state.store,db,'p',ref['document_id'],include_text=True)
        save_parse(app.state.store,db,'p',doc['id'],doc['_text'],doc['chapters'],[])
        with pytest.raises(HTTPException):propose(app.state.store,db,'p','run',frozen,body)
        assert db.execute('SELECT COUNT(*) FROM agent_image_plans').fetchone()[0]==0
