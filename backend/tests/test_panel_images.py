import pytest
import io
from PIL import Image
from fastapi.testclient import TestClient
from backend.tests.test_image_jobs import fixture


def package(c,b,source='manual',references=None):
    r=c.post(b+'/records',json={'kind':'package','title':'第7话第3格','content':{'episode':7,'panel':3,'batch':1,'prompt':'完整人工覆盖提示词','prompt_mode':'override','references':references or []}}).json()
    if source=='mock':
        with c.app.state.store.db() as db:db.execute("UPDATE versions SET source='mock' WHERE record_id=?",(r['id'],))
    return r


def body(pkg,token='image'):
    return {'kind':'image','title':'第7话第3格图片','prompt':pkg['content']['prompt'],'basis':{'id':pkg['id'],'version':pkg['version']},'submission_id':token}


def test_package_image_keeps_identity_and_requires_explicit_candidate_adoption(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'逐格'}).json()['id'];b=f'/api/projects/{pid}';pkg=package(c,b)
        preview=c.post(b+'/image-jobs',json=body(pkg));assert preview.status_code==200,preview.text
        job=preview.json();assert not calls and job['payload']['basis']['version']==1
        c.post(b+'/image-jobs/'+job['id']+'/start',json={})
        output=c.get(b+'/image-jobs/'+job['id']).json()['output']
        assert output['kind']=='image' and output['adopted']==0
        assert {k:output['content'][k] for k in ('episode','panel','batch','package_id','package_version')}=={'episode':7,'panel':3,'batch':1,'package_id':pkg['id'],'package_version':1}
        adopted=c.post(b+'/candidates/'+output['id']+'/adopt',json={})
        assert adopted.status_code==200,adopted.text
        assert adopted.json()['adopted']==2 and len(calls)==1


def test_image_prompt_is_the_frozen_package_and_stale_input_never_submits(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'冻结'}).json()['id'];b=f'/api/projects/{pid}';pkg=package(c,b)
        assert c.post(b+'/image-jobs',json={**body(pkg),'prompt':'私自换掉完整提示词'}).status_code==422
        job=c.post(b+'/image-jobs',json=body(pkg)).json()
        c.put(b+'/records/'+pkg['id'],json={'expected_version':1,'content':{**pkg['content'],'prompt':'新版提示词'}})
        assert c.post(b+'/image-jobs/'+job['id']+'/start',json={}).status_code==409 and not calls


def test_package_references_are_real_approved_images_and_mock_source_is_inherited(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'参考'}).json()['id'];b=f'/api/projects/{pid}'
        buf=io.BytesIO();Image.new('RGB',(8,8),'blue').save(buf,format='PNG')
        with app.state.store.db() as db:
            url=app.state.store.file(db,pid,'person.png',buf.getvalue(),'image/png');asset=app.state.store.add(db,pid,'asset','主角',{'url':url},'import')
        pkg=package(c,b,'mock',[{'id':asset['id'],'version':1,'purpose':'人物'}])
        assert c.post(b+'/image-jobs',json=body(pkg)).status_code==409
        c.post(b+'/records/'+asset['id']+'/reviews',json={'version':1,'decision':'approved','note':'准确参考'})
        job=c.post(b+'/image-jobs',json=body(pkg)).json()
        assert job['call']['manifest']['references'][0]['id']==asset['id']
        assert job['call']['manifest']['source']=='mock'
        c.post(b+'/image-jobs/'+job['id']+'/start',json={})
        result=c.get(b+'/image-jobs/'+job['id']).json()
        assert result['output']['source']=='mock' and calls[0].url.path.endswith('/images/edits')


def test_a_newly_adopted_image_invalidates_older_empty_slot_preview(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'并发首图'}).json()['id'];b=f'/api/projects/{pid}';pkg=package(c,b)
        first=c.post(b+'/image-jobs',json=body(pkg,'one')).json();second=c.post(b+'/image-jobs',json=body(pkg,'two')).json()
        c.post(b+'/image-jobs/'+first['id']+'/start',json={});out=c.get(b+'/image-jobs/'+first['id']).json()['output_id']
        assert c.post(b+'/candidates/'+out+'/adopt',json={}).status_code==200
        assert c.post(b+'/image-jobs/'+second['id']+'/start',json={}).status_code==409
        assert len(calls)==1


def test_existing_panel_is_replaced_only_after_adoption_and_original_picture_is_not_a_hidden_reference(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'重生成逐格'}).json()['id'];b=f'/api/projects/{pid}';pkg=package(c,b)
        buf=io.BytesIO();Image.new('RGB',(8,8),'blue').save(buf,format='PNG')
        with app.state.store.db() as db:
            url=app.state.store.file(db,pid,'old.png',buf.getvalue(),'image/png');old=app.state.store.add(db,pid,'image','旧图',{'url':url,'episode':7,'panel':3,'batch':1,'applied_instruction':'旧修图要求'},'import')
        job=c.post(b+'/image-jobs',json=body(pkg)).json()
        assert job['payload']['target']=={'id':old['id'],'version':1} and job['call']['manifest']['references']==[]
        c.post(b+'/image-jobs/'+job['id']+'/start',json={});result=c.get(b+'/image-jobs/'+job['id']).json()
        assert c.get(b+'/records/'+old['id']).json()['content']['url']==url
        assert result['output']['content']['candidate_for']==old['id'] and 'applied_instruction' not in result['output']['content']
        assert calls[0].url.path.endswith('/images/generations')
        adopted=c.post(b+'/candidates/'+result['output_id']+'/adopt',json={})
        assert adopted.status_code==200 and adopted.json()['id']==old['id'] and adopted.json()['source']=='ai'
        assert c.get(b+'/records/'+old['id']+'?version=1').json()['content']['url']==url


def test_changed_adopted_image_pointer_invalidates_preview_without_new_head_version(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'图片采用指针'}).json()['id'];b=f'/api/projects/{pid}';pkg=package(c,b)
        with app.state.store.db() as db:
            old=app.state.store.add(db,pid,'image','图',{'episode':7,'panel':3})
            app.state.store.save(db,pid,old['id'],1,{'episode':7,'panel':3,'note':'第二版'})
            db.execute('UPDATE records SET adopted=2 WHERE id=?',(old['id'],))
        job=c.post(b+'/image-jobs',json=body(pkg)).json()
        c.post(b+'/records/'+old['id']+'/adopt',json={'version':1})
        assert c.post(b+'/image-jobs/'+job['id']+'/start',json={}).status_code==409 and not calls


@pytest.mark.parametrize('action,expected',[('change','blocked'),('cancel','cancelled')])
def test_waiting_for_image_capacity_rechecks_package_before_actual_submission(tmp_path,monkeypatch,action,expected):
    import time
    from concurrent.futures import ThreadPoolExecutor
    app,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'排队输入变化'}).json()['id'];b=f'/api/projects/{pid}';pkg=package(c,b)
        job=c.post(b+'/image-jobs',json=body(pkg)).json()
        c.portal.call(app.state.image_provider.slot.acquire)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending=pool.submit(c.post,b+'/image-jobs/'+job['id']+'/start',json={})
            try:
                deadline=time.monotonic()+5
                while time.monotonic()<deadline:
                    if c.get(b+'/image-jobs/'+job['id']).json()['status']=='running':break
                    time.sleep(.01)
                else:raise AssertionError('任务未进入容量等待')
                if action=='change':c.put(b+'/records/'+pkg['id'],json={'expected_version':1,'content':{**pkg['content'],'prompt':'容量等待时已更新'}})
                else:c.post(b+'/image-jobs/'+job['id']+'/cancel',json={})
            finally:c.portal.call(app.state.image_provider.slot.release)
            assert pending.result(timeout=5).status_code==200
        result=c.get(b+'/image-jobs/'+job['id']).json()
        assert result['status']==expected and not calls


@pytest.mark.parametrize('field,value',[
    ('generation_dependencies',[{'id':'predecessor','version':1}]),
    ('previous_image_dependencies',[{'episode':7,'panel':2}]),
    ('generation_dependencies',{}),
    ('previous_image_dependencies',False),
])
def test_single_panel_cannot_silently_drop_declared_or_malformed_dependencies(tmp_path,monkeypatch,field,value):
    app,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'依赖不可绕过'}).json()['id'];b=f'/api/projects/{pid}';pkg=package(c,b)
        pkg=c.put(b+'/records/'+pkg['id'],json={'expected_version':1,'content':{**pkg['content'],field:value}}).json()
        response=c.post(b+'/image-jobs',json=body(pkg))
        assert response.status_code==422,response.text
        assert not calls and c.get(b+'/image-jobs?kind=image').json()==[]


@pytest.mark.parametrize('status,operation',[('preview','start'),('interrupted','recover')])
def test_legacy_prepared_single_job_with_dependencies_is_fenced_before_dispatch(tmp_path,monkeypatch,status,operation):
    import json
    app,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'旧预览依赖保护'}).json()['id'];b=f'/api/projects/{pid}';pkg=package(c,b)
        job=c.post(b+'/image-jobs',json=body(pkg)).json()
        # Reproduce a preview made by the older code which ignored this declaration.
        with app.state.store.db() as db:
            content={**pkg['content'],'generation_dependencies':[{'id':'predecessor','version':1}]}
            db.execute('UPDATE versions SET content=? WHERE record_id=? AND version=1',(json.dumps(content),pkg['id']))
            db.execute('UPDATE image_jobs SET status=? WHERE id=?',(status,job['id']))
        response=c.post(b+'/image-jobs/'+job['id']+'/'+operation,json={})
        assert response.status_code==409,response.text
        assert not calls and c.get(b+'/image-jobs/'+job['id']).json()['call']['status']=='prepared'


def test_dependency_fence_keeps_already_paid_return_recoverable_without_resubmitting(tmp_path,monkeypatch):
    import json
    app,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'依赖旧返回保全'}).json()['id'];b=f'/api/projects/{pid}';pkg=package(c,b)
        job=c.post(b+'/image-jobs',json=body(pkg)).json()
        from functools import partial
        paid=c.portal.call(partial(app.state.image_provider.execute,pid,job['call_id'],authorization_hash=job['input_hash']))
        assert paid['status']=='completed' and len(calls)==1
        with app.state.store.db() as db:
            content={**pkg['content'],'generation_dependencies':[{'id':'predecessor','version':1}]}
            db.execute('UPDATE versions SET content=? WHERE record_id=? AND version=1',(json.dumps(content),pkg['id']))
            db.execute("UPDATE image_jobs SET status='interrupted' WHERE id=?",(job['id'],))
        response=c.post(b+'/image-jobs/'+job['id']+'/recover',json={})
        assert response.status_code==200,response.text
        result=c.get(b+'/image-jobs/'+job['id']).json()
        assert len(calls)==1 and result['status']=='succeeded'
        assert result['output']['adopted']==0 and result['output']['content']['input_stale'] is True
        assert result['call']['result']==paid['result']
