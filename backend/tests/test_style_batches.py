import json,time,threading
import pytest
from fastapi.testclient import TestClient
from backend.tests.test_image_jobs import fixture as image_fixture
from backend.tests.test_style_tests import setup


def group(app):
    from backend.style_tests import propose
    frozen,body,_=setup(app)
    with app.state.store.db() as db:
        result=propose(app.state.store,db,'p','run',frozen,body)
        db.execute("UPDATE agent_runs SET status='completed' WHERE id='run'")
    return result['id']


def wait(c,bid,status=None):
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        value=c.get('/api/projects/p/image-batches/'+bid).json()
        if value['status'] not in ('queued','running','pausing'):return value
        time.sleep(.02)
    pytest.fail('style batch did not settle')


def test_style_group_preview_and_strict_grant_generate_exactly_three_candidates(tmp_path,monkeypatch):
    app,calls=image_fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        gid=group(app);path='/api/projects/p/agent/style-tests/'+gid+'/batch-preview'
        preview=c.post(path,json={});assert preview.status_code==200,preview.text
        batch=preview.json();bid=batch['id'];assert batch['status']=='preview' and len(batch['jobs'])==3 and not calls
        assert batch['payload']['mode']=='style_tests' and batch['payload']['call_limits']=={'images':3,'vision':0,'image_network_attempts':3}
        assert c.post(path,json={}).json()['id']==bid
        assert len({j['call_id'] for j in batch['jobs']})==3
        assert c.post('/api/projects/p/image-jobs/'+batch['jobs'][0]['id']+'/start',json={}).status_code==409
        for body in [{},{'confirm':False},{'confirm':1},{'confirm':True,'count':4}]:
            assert c.post('/api/projects/p/image-batches/'+bid+'/start',json=body).status_code==422
        assert not calls
        assert c.post('/api/projects/p/image-batches/'+bid+'/start',json={'confirm':True}).status_code==200
        result=wait(c,bid);assert result['status']=='completed',result
        assert len(calls)==3 and all(j['output']['adopted']==0 for j in result['jobs'])
        assert c.post('/api/projects/p/image-batches/'+bid+'/start',json={'confirm':True}).status_code==200 and len(calls)==3
        assert c.get('/api/projects/p/image-batches').json()['total']==0
        assert c.get('/api/projects/p/image-batches?mode=style_tests').json()['total']==1
        assert c.get('/api/projects/p/agent/style-tests/'+gid).json()['batch']['id']==bid
        assert c.post('/api/projects/other/agent/style-tests/'+gid+'/batch-preview',json={}).status_code==404


@pytest.mark.parametrize('change',['started','rejected','stale'])
def test_ineligible_trio_never_claims_a_new_batch(tmp_path,monkeypatch,change):
    app,calls=image_fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        gid=group(app);value=c.get('/api/projects/p/agent/style-tests/'+gid).json();plan=value['plans'][0]
        if change=='started':
            job=c.post('/api/projects/p/agent/image-plans/'+plan['id']+'/preview',json={}).json()
            c.post('/api/projects/p/image-jobs/'+job['id']+'/start',json={})
        elif change=='rejected':c.post('/api/projects/p/agent/image-plans/'+plan['id']+'/reject',json={})
        else:c.put('/api/projects/p/preferences',json={'expected_revision':0,'text':'changed'})
        before=len(calls)
        response=c.post('/api/projects/p/agent/style-tests/'+gid+'/batch-preview',json={})
        assert response.status_code==409,response.text
        assert len(calls)==before
        with app.state.store.db() as db:assert db.execute('SELECT COUNT(*) FROM image_batches').fetchone()[0]==0


@pytest.mark.parametrize('action',['pause','cancel'])
def test_inflight_style_batch_drains_without_dispatching_more_and_pause_can_resume(tmp_path,monkeypatch,action):
    import asyncio,httpx
    app,calls=image_fixture(tmp_path,monkeypatch);original=app.state.image_provider.transport
    entered=threading.Event();release=threading.Event();dispatched=[]
    async def slow(request):
        dispatched.append(request)
        if len(dispatched)==1:
            entered.set()
            while not release.is_set():await asyncio.sleep(.01)
        return original.handle_request(request)
    app.state.image_provider.transport=httpx.MockTransport(slow)
    with TestClient(app) as c:
        gid=group(app);bid=c.post('/api/projects/p/agent/style-tests/'+gid+'/batch-preview',json={}).json()['id']
        c.post('/api/projects/p/image-batches/'+bid+'/start',json={'confirm':True});assert entered.wait(10)
        assert c.post('/api/projects/p/image-batches/'+bid+'/'+action,json={}).status_code==200
        release.set()
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            value=c.get('/api/projects/p/image-batches/'+bid).json()
            pool=c.get('/api/runtime/limits').json()['usage']['image']
            if value['status'] in ('paused','cancelled') and pool['active']==0 and value['jobs'][0]['call']['status']=='completed':break
            time.sleep(.02)
        else:pytest.fail('inflight style call did not drain')
        assert len(dispatched)==1 and len(calls)==1
        first=value['jobs'][0];assert first['call']['status']=='completed' and first['call']['result']['url']
        before=value['runtime']['effective_seconds']
        if action=='pause':
            assert first['status']=='succeeded' and not first['output']['adopted']
            assert c.post('/api/projects/p/image-batches/'+bid+'/recover',json={}).status_code==422
            c.post('/api/projects/p/image-batches/'+bid+'/recover',json={'confirm':True})
            final=wait(c,bid);assert final['status']=='completed' and len(dispatched)==3
            assert final['jobs'][0]['call_id']==first['call_id']
            assert final['runtime']['effective_seconds']>=before
        else:
            assert first['status']=='cancelled' and not first['output_id']
            assert c.post('/api/projects/p/image-batches/'+bid+'/recover',json={'confirm':True}).status_code==409
            assert len(dispatched)==1


def test_unknown_style_result_is_not_retried_on_explicit_recovery(tmp_path,monkeypatch):
    import httpx
    app,calls=image_fixture(tmp_path,monkeypatch);original=app.state.image_provider.transport;dispatched=[]
    def mixed(request):
        dispatched.append(request)
        return httpx.Response(500,json={'error':'synthetic unknown'}) if len(dispatched)==1 else original.handle_request(request)
    app.state.image_provider.transport=httpx.MockTransport(mixed)
    with TestClient(app) as c:
        gid=group(app);bid=c.post('/api/projects/p/agent/style-tests/'+gid+'/batch-preview',json={}).json()['id']
        c.post('/api/projects/p/image-batches/'+bid+'/start',json={'confirm':True})
        first=wait(c,bid);assert first['status']=='needs_attention' and len(dispatched)==3
        assert first['jobs'][0]['status']=='unknown'
        assert not first['jobs'][0]['call']['has_saved_response']
        assert all(j['status']=='succeeded' for j in first['jobs'][1:])
        c.post('/api/projects/p/image-batches/'+bid+'/recover',json={'confirm':True})
        final=wait(c,bid)
        assert final['status']=='needs_attention' and len(dispatched)==3
        assert final['jobs'][0]['call_id']==first['jobs'][0]['call_id']


def test_restart_preserves_paused_style_jobs_and_requires_explicit_recovery(tmp_path,monkeypatch):
    import asyncio,httpx
    from backend.app import create_app
    app,calls=image_fixture(tmp_path,monkeypatch);original=app.state.image_provider.transport
    entered=threading.Event();release=threading.Event()
    async def slow(request):
        entered.set()
        while not release.is_set():await asyncio.sleep(.01)
        return original.handle_request(request)
    app.state.image_provider.transport=httpx.MockTransport(slow)
    with TestClient(app) as c:
        gid=group(app);bid=c.post('/api/projects/p/agent/style-tests/'+gid+'/batch-preview',json={}).json()['id']
        c.post('/api/projects/p/image-batches/'+bid+'/start',json={'confirm':True});assert entered.wait(10)
        c.post('/api/projects/p/image-batches/'+bid+'/pause',json={});release.set()
        first=wait(c,bid);assert first['status']=='paused' and len(calls)==1
    restored=create_app(tmp_path);restored.state.image_provider.transport=original
    with TestClient(restored) as c:
        before=c.get('/api/projects/p/image-batches/'+bid).json()
        assert before['status']=='paused' and len(calls)==1
        assert c.get('/api/projects/p/agent/style-tests/'+gid).json()['batch']['id']==bid
        assert c.post('/api/projects/p/image-batches/'+bid+'/recover',json={}).status_code==422
        c.post('/api/projects/p/image-batches/'+bid+'/recover',json={'confirm':True})
        final=wait(c,bid);assert final['status']=='completed' and len(calls)==3
        assert [j['call_id'] for j in final['jobs']]==[j['call_id'] for j in first['jobs']]
        assert final['runtime']['effective_seconds']>=before['runtime']['effective_seconds']


def test_partial_preview_failure_does_not_claim_jobs_or_authorize_calls(tmp_path,monkeypatch):
    from fastapi import HTTPException
    app,calls=image_fixture(tmp_path,monkeypatch);original=app.state.agent_image_plans.preview;count=0
    def fail_second(*args):
        nonlocal count
        count+=1
        if count==2:raise HTTPException(409,'synthetic preview failure')
        return original(*args)
    monkeypatch.setattr(app.state.agent_image_plans,'preview',fail_second)
    with TestClient(app) as c:
        gid=group(app);path='/api/projects/p/agent/style-tests/'+gid+'/batch-preview'
        assert c.post(path,json={}).status_code==409
        retry=c.post(path,json={}).json();assert retry['status']=='preview_failed' and count==2
        assert not calls
        assert all(not j['payload'].get('image_batch_id') for j in retry['jobs'])
        assert c.post('/api/projects/p/image-batches/'+retry['id']+'/start',json={'confirm':True}).status_code==409


def test_style_batch_effective_time_limit_retains_first_return_and_stops_new_dispatch(tmp_path,monkeypatch):
    import httpx
    from backend.image_batch_control import HARD
    app,calls=image_fixture(tmp_path,monkeypatch);original=app.state.image_provider.transport;offset=[0.]
    clock=app.state.image_batch_control.now;app.state.image_batch_control.now=lambda:clock()+offset[0]
    def expire(request):
        result=original.handle_request(request);offset[0]=HARD+1;return result
    app.state.image_provider.transport=httpx.MockTransport(expire)
    with TestClient(app) as c:
        gid=group(app);bid=c.post('/api/projects/p/agent/style-tests/'+gid+'/batch-preview',json={}).json()['id']
        c.post('/api/projects/p/image-batches/'+bid+'/start',json={'confirm':True})
        value=wait(c,bid);assert value['status']=='budget_exhausted' and len(calls)==1
        assert value['jobs'][0]['status']=='succeeded' and value['jobs'][0]['call']['result']['url']
        assert all(j['call']['status']=='prepared' for j in value['jobs'][1:])
        assert c.post('/api/projects/p/image-batches/'+bid+'/recover',json={'confirm':True}).status_code==409
        assert len(calls)==1


def test_style_basis_change_after_first_call_blocks_remaining_authorized_jobs(tmp_path,monkeypatch):
    import httpx
    app,calls=image_fixture(tmp_path,monkeypatch);original=app.state.image_provider.transport
    def change(request):
        response=original.handle_request(request)
        with app.state.store.db() as db:
            db.execute("INSERT INTO project_preferences VALUES('p',1,'changed during dispatch') ON CONFLICT(project_id) DO UPDATE SET revision=revision+1")
        return response
    app.state.image_provider.transport=httpx.MockTransport(change)
    with TestClient(app) as c:
        gid=group(app);bid=c.post('/api/projects/p/agent/style-tests/'+gid+'/batch-preview',json={}).json()['id']
        c.post('/api/projects/p/image-batches/'+bid+'/start',json={'confirm':True})
        value=wait(c,bid);assert value['status']=='needs_attention' and len(calls)==1
        assert value['jobs'][0]['output']['content']['input_stale']
        assert all(j['status']=='blocked' and j['call']['status']=='prepared' for j in value['jobs'][1:])


def test_panel_submission_token_cannot_impersonate_a_style_group_batch(tmp_path,monkeypatch):
    from backend.tests.test_image_batches import packages,request
    app,calls=image_fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        gid=group(app);b='/api/projects/p'
        ordinary=c.post(b+'/image-batches',json=request(packages(c,b,1),'style-test-'+gid));assert ordinary.status_code==200,ordinary.text
        original=ordinary.json()
        value=c.get(b+'/agent/style-tests/'+gid).json()
        assert 'batch' not in value
        response=c.post(b+'/agent/style-tests/'+gid+'/batch-preview',json={})
        assert response.status_code==409,response.text
        assert not calls
        assert c.get(b+'/image-batches/'+original['id']).json()['payload'].get('mode','panels')=='panels'


def test_stale_style_batch_can_restore_saved_return_without_another_supplier_call(tmp_path,monkeypatch):
    app,calls=image_fixture(tmp_path,monkeypatch);original=app.state.store.add;failed=[False]
    def fail_candidate(db,pid,kind,title,*args,**kwargs):
        if kind=='style' and title.startswith('候选') and not failed[0]:
            failed[0]=True;raise OSError('synthetic registration interruption')
        return original(db,pid,kind,title,*args,**kwargs)
    with TestClient(app) as c:
        gid=group(app);bid=c.post('/api/projects/p/agent/style-tests/'+gid+'/batch-preview',json={}).json()['id']
        monkeypatch.setattr(app.state.store,'add',fail_candidate)
        c.post('/api/projects/p/image-batches/'+bid+'/start',json={'confirm':True})
        first=wait(c,bid);assert first['status']=='needs_attention' and first['jobs'][0]['status']=='interrupted'
        assert len(calls)==3 and first['jobs'][0]['call']['status']=='completed'
        c.put('/api/projects/p/preferences',json={'expected_revision':0,'text':'new source interpretation'})
        c.post('/api/projects/p/image-batches/'+bid+'/recover',json={'confirm':True})
        final=wait(c,bid);assert final['status']=='completed' and len(calls)==3
        assert final['jobs'][0]['call_id']==first['jobs'][0]['call_id']
        assert final['jobs'][0]['output']['content']['input_stale']
        assert c.post('/api/projects/p/candidates/'+final['jobs'][0]['output_id']+'/adopt',json={}).status_code==409


def test_restore_only_grant_cannot_dispatch_prepared_jobs_even_after_basis_is_valid_again(tmp_path,monkeypatch):
    app,calls=image_fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        gid=group(app);batch=c.post('/api/projects/p/agent/style-tests/'+gid+'/batch-preview',json={}).json();bid=batch['id']
        assert c.post('/api/projects/p/image-batches/'+bid+'/start',json={'confirm':True,'restore_only':True}).status_code==422
        pool=app.state.capacity.pools['image'];c.portal.call(pool.acquire)
        try:
            c.post('/api/projects/p/image-batches/'+bid+'/start',json={'confirm':True})
            deadline=time.monotonic()+10
            while time.monotonic()<deadline:
                if c.get('/api/runtime/limits').json()['usage']['image']['waiting']==1:break
                time.sleep(.02)
            else:pytest.fail('no queued image lease')
            assert c.post('/api/projects/p/image-batches/'+bid+'/pause',json={}).status_code==200
        finally:c.portal.call(pool.release)
        assert wait(c,bid)['status']=='paused' and not calls
        result=c.post('/api/projects/p/image-batches/'+bid+'/recover',json={'confirm':True,'restore_only':True})
        assert result.status_code==200,result.text
        stopped=wait(c,bid);assert stopped['status']=='needs_attention' and not calls
        assert all(j['call']['status']=='prepared' for j in stopped['jobs'])
        c.post('/api/projects/p/image-batches/'+bid+'/recover',json={'confirm':True})
        assert wait(c,bid)['status']=='completed' and len(calls)==3
