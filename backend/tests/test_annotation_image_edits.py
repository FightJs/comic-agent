"""Annotation edits reuse authorized image jobs; no live provider requests."""
import io,json
import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from backend.tests.test_image_jobs import fixture


def base_image(app,c):
    pid=c.post('/api/projects',json={'name':'批注修图'}).json()['id'];b=f'/api/projects/{pid}'
    with app.state.store.db() as db:
        buf=io.BytesIO();Image.new('RGB',(8,8),'blue').save(buf,format='PNG')
        url=app.state.store.file(db,pid,'base.png',buf.getvalue(),'image/png')
        image=app.state.store.add(db,pid,'image','原图',{'url':url,'width':8,'height':8,'episode':2,'panel':3,'batch':1,'package_id':'original-package','package_version':4},'manual')
    ann={'image_version':1,'expected_version':0,'items':[{'id':'eye','type':'rect','x':1,'y':2,'width':3,'height':2,'note':'修改眼睛'},{'id':'face','type':'protect','x':0,'y':0,'width':1,'height':1,'note':'保留脸型'}]}
    assert c.put(b+'/records/'+image['id']+'/annotations',json=ann).status_code==200
    body={'kind':'image','title':'局部修改','prompt':'修正眼神','target':{'id':image['id'],'version':1},'annotation_edit':{'annotation_version':1,'preserve':'保持画风'},'submission_id':'ann-edit'}
    return b,image,body


def test_annotation_preview_freezes_base_and_intents_and_starts_independent_candidate(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        b,image,body=base_image(app,c)
        response=c.post(b+'/image-jobs',json=body);assert response.status_code==200,response.text
        job=response.json();assert not calls
        assert job['call']['manifest']['operation']=='edit'
        assert job['call']['manifest']['mask'] is None
        assert job['call']['manifest']['references'][0]['id']==image['id']
        assert '修改眼睛' in job['call']['manifest']['prompt'] and '保留脸型' in job['call']['manifest']['prompt']
        assert '不是硬蒙版' in job['call']['manifest']['prompt']
        assert job['payload']['annotation_edit']['items'][0]['id']=='eye'
        assert c.post(b+'/image-jobs/'+job['id']+'/start').status_code==200
        done=c.get(b+'/image-jobs/'+job['id']).json();assert done['status']=='succeeded' and len(calls)==1
        output=done['output'];assert output['adopted']==0 and output['content']['candidate_for']==image['id']
        assert output['content']['episode']==2 and output['content']['package_version']==4
        assert c.get(b+'/records/'+image['id']).json()['version']==1
        assert c.post(b+'/image-jobs/'+job['id']+'/start').status_code==200 and len(calls)==1
        adopted=c.post(b+'/candidates/'+output['id']+'/adopt',json={})
        assert adopted.status_code==200,adopted.text
        assert adopted.json()['adopted']==2


def test_annotation_change_or_same_version_tampering_blocks_before_paid_call(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        b,image,body=base_image(app,c)
        r=c.post(b+'/image-jobs',json=body);assert r.status_code==200,r.text
        with app.state.store.db() as db:db.execute('UPDATE annotations SET items=? WHERE record_id=?',(json.dumps([]),image['id']))
        assert c.post(b+'/image-jobs/'+r.json()['id']+'/start').status_code==409
        assert not calls


def test_annotation_inputs_are_strict_scoped_and_do_not_relax_package_generation(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        b,image,body=base_image(app,c)
        for edit in [{'annotation_version':True,'preserve':''},{'annotation_version':-1,'preserve':''},{'annotation_version':1,'preserve':'','mask':'text'},{'annotation_version':1,'preserve':'x'*4001}]:
            assert c.post(b+'/image-jobs',json={**body,'annotation_edit':edit}).status_code==422
        for changed in [{'kind':'asset'},{'target':None},{'basis':{'id':'package','version':1}},{'annotation_edit':{'annotation_version':0,'preserve':''}}]:
            assert c.post(b+'/image-jobs',json={**body,**changed}).status_code in (409,422)
        ordinary=dict(body);ordinary.pop('annotation_edit')
        assert c.post(b+'/image-jobs',json=ordinary).status_code==422
        assert not calls


def test_annotation_unknown_cannot_repost_and_stale_return_stays_candidate(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch)
    def uncertain(request):calls.append(request);raise httpx.ReadTimeout('fixture',request=request)
    app.state.image_provider.transport=httpx.MockTransport(uncertain)
    with TestClient(app) as c:
        b,image,body=base_image(app,c)
        r=c.post(b+'/image-jobs',json=body);assert r.status_code==200,r.text
        jid=r.json()['id'];c.post(b+'/image-jobs/'+jid+'/start')
        assert c.get(b+'/image-jobs/'+jid).json()['status']=='unknown'
        assert c.post(b+'/image-jobs/'+jid+'/recover').status_code==409
        assert c.post(b+'/image-jobs',json={**body,'submission_id':'another'}).status_code==409
        assert len(calls)==1


def test_late_annotation_change_keeps_paid_return_as_stale_candidate(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch)
    original=app.state.image_provider.transport.handler;state={}
    def changed(request):
        with app.state.store.db() as db:db.execute('UPDATE annotations SET version=version+1 WHERE record_id=?',(state['rid'],))
        return original(request)
    app.state.image_provider.transport=httpx.MockTransport(changed)
    with TestClient(app) as c:
        b,image,body=base_image(app,c);state['rid']=image['id']
        r=c.post(b+'/image-jobs',json=body);assert r.status_code==200,r.text
        assert c.post(b+'/image-jobs/'+r.json()['id']+'/start').status_code==200
        result=c.get(b+'/image-jobs/'+r.json()['id']).json()
        assert result['status']=='succeeded' and result['output']['content']['input_stale'] is True
        assert result['output']['adopted']==0 and len(calls)==1
        assert c.post(b+"/candidates/"+result['output_id']+'/adopt',json={}).status_code==409


def test_annotation_branch_cannot_be_composed_with_batch_or_agent_authority(tmp_path,monkeypatch):
    from backend.image_jobs import PreviewIn
    from fastapi import HTTPException
    app,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        b,image,body=base_image(app,c);pid=b.split('/')[-1]
        for extra in [{'batch_id':'batch'},{'dependency_plan':{}},{'postprocess_plan':{}},{'agent_plan':{}}]:
            with pytest.raises(HTTPException) as error:app.state.image_jobs.preview(pid,PreviewIn.model_validate(body),**extra)
            assert error.value.status_code==422
        assert not calls


def test_history_or_unadopted_base_is_not_silently_replaced(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        b,image,body=base_image(app,c)
        with app.state.store.db() as db:db.execute('UPDATE records SET adopted=0 WHERE id=?',(image['id'],))
        assert c.post(b+'/image-jobs',json=body).status_code==409
        with app.state.store.db() as db:
            db.execute('UPDATE records SET adopted=1 WHERE id=?',(image['id'],))
            app.state.store.save(db,b.split('/')[-1],image['id'],1,image['content'])
        assert c.post(b+'/image-jobs',json=body).status_code==409
        assert not calls
