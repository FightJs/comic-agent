import json
import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from backend.image_jobs import PreviewIn
from backend.image_batches import BatchIn
from backend.tests.test_image_jobs import fixture


def test_retry_fields_are_strict_and_bounded():
    for model,fields in ((PreviewIn,{'kind':'style','title':'测试','prompt':'合成','submission_id':'x'}),(BatchIn,{'packages':[{'id':'x','version':1}],'submission_id':'x'})):
        assert model(**fields).max_not_sent_retries==0
        for value in (-1,5,True,'1',1.0):
            with pytest.raises(ValidationError):model(**fields,max_not_sent_retries=value)


def test_authorized_not_sent_retry_is_orchestrated_without_extra_logical_call(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch);success=app.state.image_provider.transport.handler
    def transport(request):
        if not calls:
            calls.append(request);raise httpx.ConnectError('synthetic not sent',request=request)
        return success(request)
    app.state.image_provider.transport=httpx.MockTransport(transport)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'retry synthetic'}).json()['id'];base=f'/api/projects/{pid}/image-jobs'
        response=c.post(base,json={'kind':'style','title':'合成方向','prompt':'合成提示','submission_id':'one','max_not_sent_retries':1})
        assert response.status_code==200,response.text
        job=response.json();assert job['payload']['retry_policy']=={'version':1,'max_not_sent_retries':1}
        assert job['call']['manifest']['retry_policy']==job['payload']['retry_policy']
        assert c.post(base+'/'+job['id']+'/start').status_code==200
        final=c.get(base+'/'+job['id']).json()
        assert final['status']=='succeeded' and len(calls)==2,final
        history=final['call']['attempts'];assert len(history['attempts'])==2 and history['remaining_attempts']==0
        assert history['attempts'][0]['evidence']['outcome']=='not_sent'
        assert history['attempts'][0]['authorization_hash']==job['input_hash']
        assert c.post(base+'/'+job['id']+'/recover').status_code==200 and len(calls)==2

@pytest.mark.parametrize('retries,outcome,expected',[(0,'connect',1),(2,'connect',3),(4,'read',1),(4,'reject',1),(4,'bad_response',1)])
def test_retry_stops_at_original_limit_or_any_response(tmp_path,monkeypatch,retries,outcome,expected):
    app,calls=fixture(tmp_path,monkeypatch)
    def transport(request):
        calls.append(request)
        if outcome=='connect':raise httpx.ConnectTimeout('synthetic',request=request)
        if outcome=='read':raise httpx.ReadTimeout('synthetic',request=request)
        if outcome=='reject':return httpx.Response(429,json={'error':'synthetic'})
        return httpx.Response(200,json={'data':[]})
    app.state.image_provider.transport=httpx.MockTransport(transport)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'bounded synthetic'}).json()['id'];base=f'/api/projects/{pid}/image-jobs'
        job=c.post(base,json={'kind':'style','title':'测试','prompt':'合成','submission_id':'one','max_not_sent_retries':retries}).json()
        c.post(base+'/'+job['id']+'/start')
        assert len(calls)==expected
        c.post(base+'/'+job['id']+'/recover')
        assert len(calls)==expected


def test_interrupted_not_sent_needs_explicit_recover_and_retains_grant(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch);success=app.state.image_provider.transport.handler
    def transport(request):
        if not calls:calls.append(request);raise httpx.ConnectError('synthetic',request=request)
        return success(request)
    app.state.image_provider.transport=httpx.MockTransport(transport);original=app.state.image_provider.execute
    async def interrupted(*args,**kwargs):
        result=await original(*args,**kwargs)
        if result['status']=='not_sent':raise RuntimeError('synthetic process interruption')
        return result
    monkeypatch.setattr(app.state.image_provider,'execute',interrupted)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'resume synthetic'}).json()['id'];base=f'/api/projects/{pid}/image-jobs'
        job=c.post(base,json={'kind':'style','title':'测试','prompt':'合成','submission_id':'one','max_not_sent_retries':2}).json();path=base+'/'+job['id']
        c.post(path+'/start');interrupted_job=c.get(path).json()
        assert interrupted_job['status']=='interrupted' and len(calls)==1
        assert interrupted_job['call']['attempts']['remaining_attempts']==2
        monkeypatch.setattr(app.state.image_provider,'execute',original)
        c.get(path);assert len(calls)==1
        assert c.post(path+'/recover').status_code==200
        final=c.get(path).json();assert final['status']=='succeeded' and len(calls)==2
        assert final['input_hash']==job['input_hash'] and final['call']['attempts']['remaining_attempts']==1


def test_batch_pause_between_attempts_preserves_preview_and_original_network_budget(tmp_path,monkeypatch):
    from backend.tests.test_image_batches import packages,request,wait
    app,calls=fixture(tmp_path,monkeypatch);success=app.state.image_provider.transport.handler;owner={}
    def transport(req):
        if not calls:
            calls.append(req)
            with app.state.store.db() as db:db.execute("UPDATE image_batches SET status='pausing' WHERE id=?",(owner['bid'],))
            raise httpx.ConnectError('synthetic',request=req)
        return success(req)
    app.state.image_provider.transport=httpx.MockTransport(transport)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'pause retries synthetic'}).json()['id'];base=f'/api/projects/{pid}';pkgs=packages(c,base,1)
        preview=c.post(base+'/image-batches',json={**request(pkgs),'max_not_sent_retries':2}).json();bid=owner['bid']=preview['id']
        assert preview['payload']['call_limits']['image_network_attempts']==3
        assert preview['jobs'][0]['payload']['retry_policy']=={'version':1,'max_not_sent_retries':2}
        c.post(base+'/image-batches/'+bid+'/start')
        paused=wait(c,base,bid);assert paused['status']=='paused',paused
        assert paused['jobs'][0]['status']=='preview' and len(calls)==1
        c.post(base+'/image-batches/'+bid+'/recover')
        final=wait(c,base,bid);assert final['status']=='completed',final
        assert len(calls)==2 and final['jobs'][0]['call']['attempts']['remaining_attempts']==1
        assert final['payload']['call_limits']['image_network_attempts']==3

@pytest.mark.parametrize('change',['cancel','version'])
def test_between_attempt_guards_stop_cancellation_and_input_change(tmp_path,monkeypatch,change):
    app,calls=fixture(tmp_path,monkeypatch);ids={}
    def transport(req):
        calls.append(req)
        with app.state.store.db() as db:
            if change=='cancel':
                row=db.execute('SELECT payload FROM image_jobs WHERE id=?',(ids['jid'],)).fetchone();payload=json.loads(row[0]);payload['cancel_requested']=True
                db.execute("UPDATE image_jobs SET status='cancelled',payload=? WHERE id=?",(json.dumps(payload),ids['jid']))
            else:app.state.store.save(db,ids['pid'],ids['target'],1,{'prompt':'合成新版本'})
        raise httpx.ConnectError('synthetic',request=req)
    app.state.image_provider.transport=httpx.MockTransport(transport)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'guard synthetic'}).json()['id'];base=f'/api/projects/{pid}'
        ids['pid']=pid
        target=c.post(base+'/records',json={'kind':'style','title':'固定资料','content':{'prompt':'原稿'}}).json();ids['target']=target['id']
        job=c.post(base+'/image-jobs',json={'kind':'style','title':'测试','prompt':'合成','target':{'id':target['id'],'version':1},'submission_id':'one','max_not_sent_retries':2}).json();ids['jid']=job['id'];path=base+'/image-jobs/'+job['id']
        c.post(path+'/start');final=c.get(path).json()
        assert len(calls)==1 and final['status']==('cancelled' if change=='cancel' else 'blocked'),final
        assert final['call']['attempts']['remaining_attempts']==2
        assert c.post(path+'/recover').status_code==409 and len(calls)==1


def test_legacy_not_sent_cannot_gain_new_retry_policy(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch)
    def transport(req):calls.append(req);raise httpx.ConnectError('synthetic',request=req)
    app.state.image_provider.transport=httpx.MockTransport(transport)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'legacy synthetic'}).json()['id'];base=f'/api/projects/{pid}/image-jobs'
        job=c.post(base,json={'kind':'style','title':'测试','prompt':'合成','submission_id':'one'}).json()
        legacy=app.state.image_provider.prepare(pid,'old-call','合成')
        payload=job['payload'];payload.pop('retry_policy');payload.pop('max_not_sent_retries')
        with app.state.store.db() as db:db.execute('UPDATE image_jobs SET call_id=?,payload=? WHERE id=?',(legacy['id'],json.dumps(payload),job['id']))
        path=base+'/'+job['id'];c.post(path+'/start');final=c.get(path).json()
        assert final['status']=='blocked' and final['call']['attempts'] is None and len(calls)==1
        assert c.post(path+'/recover').status_code==409 and len(calls)==1


def test_restore_only_batch_cannot_spend_remaining_not_sent_attempts(tmp_path,monkeypatch):
    from backend.tests.test_image_batches import packages,request,wait
    app,calls=fixture(tmp_path,monkeypatch);owner={}
    def transport(req):
        calls.append(req)
        with app.state.store.db() as db:db.execute("UPDATE image_batches SET status='pausing' WHERE id=?",(owner['bid'],))
        raise httpx.ConnectError('synthetic',request=req)
    app.state.image_provider.transport=httpx.MockTransport(transport)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'restore only synthetic'}).json()['id'];base=f'/api/projects/{pid}'
        preview=c.post(base+'/image-batches',json={**request(packages(c,base,1)),'max_not_sent_retries':3}).json();bid=owner['bid']=preview['id']
        c.post(base+'/image-batches/'+bid+'/start');assert wait(c,base,bid)['status']=='paused'
        with app.state.store.db() as db:
            row=db.execute('SELECT payload FROM image_batches WHERE id=?',(bid,)).fetchone();payload=json.loads(row[0]);payload['restore_only']=True
            db.execute('UPDATE image_batches SET payload=? WHERE id=?',(json.dumps(payload),bid))
        c.post(base+'/image-batches/'+bid+'/recover');final=wait(c,base,bid)
        assert len(calls)==1 and final['jobs'][0]['call']['attempts']['remaining_attempts']==3


def test_planned_repair_inherits_policy_without_replacing_original_attempt_history(tmp_path,monkeypatch):
    from backend.tests.test_image_batches import packages,request,wait
    from backend.tests.test_image_postprocess import setup,report
    app,images,vision=setup(tmp_path,monkeypatch,[report('critical'),report()]);success=app.state.image_provider.transport.handler;physical=[]
    def transport(req):
        physical.append(req)
        if len(physical) in (1,3):raise httpx.ConnectError('synthetic',request=req)
        return success(req)
    app.state.image_provider.transport=httpx.MockTransport(transport)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'repair retries synthetic'}).json()['id'];base=f'/api/projects/{pid}'
        preview=c.post(base+'/image-batches',json={**request(packages(c,base,1)),'inspection':'review_repair','max_not_sent_retries':2}).json();bid=preview['id']
        assert preview['payload']['call_limits']=={'images':2,'vision':2,'image_network_attempts':6}
        c.post(base+'/image-batches/'+bid+'/start');done=wait(c,base,bid)
        assert done['status']=='completed' and len(physical)==4 and len(images)==len(vision)==2,done
        root=done['jobs'][0];repair=c.get(base+'/image-jobs/'+root['payload']['postprocess']['repair_job_id']).json()
        for image in (root,repair):
            assert image['payload']['retry_policy']==image['call']['manifest']['retry_policy']=={'version':1,'max_not_sent_retries':2}
            assert len(image['call']['attempts']['attempts'])==2 and image['call']['attempts']['remaining_attempts']==1
        assert root['call_id']!=repair['call_id']


def test_dependency_rebind_preserves_policy_and_never_resets_submitted_call(tmp_path,monkeypatch):
    from backend.tests.test_image_batches import packages,request,wait
    from backend.tests.test_image_dependencies import link,adopt_review
    app,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'dependency retries synthetic'}).json()['id'];base=f'/api/projects/{pid}';ps=packages(c,base,2)
        ps[1]=link(c,base,ps[1],[ps[0]])
        preview=c.post(base+'/image-batches',json={**request(ps),'max_not_sent_retries':2}).json();bid=preview['id'];original=preview['jobs'][1]
        c.post(base+'/image-batches/'+bid+'/start');waiting=wait(c,base,bid)
        assert waiting['jobs'][1]['status']=='waiting_dependency'
        adopt_review(c,base,waiting['jobs'][0])
        c.post(base+'/image-batches/'+bid+'/recover');done=wait(c,base,bid)
        assert done['status']=='completed' and len(calls)==2
        rebound=done['jobs'][1];assert rebound['call_id']!=original['call_id']
        for call in (app.state.image_provider.get(pid,original['call_id']),rebound['call']):assert call['manifest']['retry_policy']=={'version':1,'max_not_sent_retries':2}
        old=app.state.image_provider.get(pid,original['call_id']);assert old['status']=='prepared' and old['attempts'] is None
        assert len(rebound['call']['attempts']['attempts'])==1 and rebound['call']['attempts']['remaining_attempts']==2
