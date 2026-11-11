"""Retry allowance is fixed when an AI plan/group becomes a preview."""
import pytest
from fastapi.testclient import TestClient
from backend.tests.test_image_jobs import fixture
from backend.tests.test_style_batches import group


def test_style_trio_freezes_network_allowance_and_reopening_cannot_expand(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        gid=group(app);path=f'/api/projects/p/agent/style-tests/{gid}/batch-preview'
        response=c.post(path,json={'max_not_sent_retries':2})
        assert response.status_code==200,response.text
        batch=response.json();assert not calls
        assert batch['payload']['retry_policy']=={'version':1,'max_not_sent_retries':2}
        assert batch['payload']['call_limits']['image_network_attempts']==9
        assert batch['input_hash']!=gid
        assert all(j['call']['manifest']['retry_policy']==batch['payload']['retry_policy'] for j in batch['jobs'])
        assert c.get(f'/api/projects/p/agent/style-tests/{gid}').json()['batch']['id']==batch['id']
        assert c.post(path,json={}).json()['id']==batch['id']
        assert c.post(path,json={'max_not_sent_retries':3}).status_code==409
        assert c.post(f"/api/projects/p/image-batches/{batch['id']}/start",json={'confirm':True,'max_not_sent_retries':4}).status_code==422
        assert not calls


def test_ai_plan_freezes_first_allowance_and_old_preview_is_not_expanded(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        gid=group(app);plan=c.get(f'/api/projects/p/agent/style-tests/{gid}').json()['plans'][0]
        path=f"/api/projects/p/agent/image-plans/{plan['id']}/preview"
        response=c.post(path,json={'max_not_sent_retries':4})
        assert response.status_code==200,response.text
        saved=response.json();assert saved['payload']['retry_policy']['max_not_sent_retries']==4
        assert c.post(path,json={}).json()['id']==saved['id']
        assert c.post(path,json={'max_not_sent_retries':0}).status_code==409
        assert not calls


@pytest.mark.parametrize('value',[True,-1,5,1.5,'2'])
def test_plan_and_group_reject_noninteger_or_out_of_range_retry_allowance(tmp_path,monkeypatch,value):
    app,_=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        gid=group(app);plan=c.get(f'/api/projects/p/agent/style-tests/{gid}').json()['plans'][0]
        for path in [f'/api/projects/p/agent/style-tests/{gid}/batch-preview',f"/api/projects/p/agent/image-plans/{plan['id']}/preview"]:
            assert c.post(path,json={'max_not_sent_retries':value}).status_code==422

def test_three_styles_use_separate_attempts_within_the_frozen_group_allowance(tmp_path,monkeypatch):
    import httpx,json,time
    app,calls=fixture(tmp_path,monkeypatch);original=app.state.image_provider.transport;seen={};physical=[]
    def transport(request):
        prompt=json.loads(request.content)['prompt'];physical.append(request)
        seen[prompt]=seen.get(prompt,0)+1
        if seen[prompt]==1:raise httpx.ConnectError('synthetic connect failure',request=request)
        return original.handle_request(request)
    app.state.image_provider.transport=httpx.MockTransport(transport)
    with TestClient(app) as c:
        gid=group(app)
        preview=c.post(f'/api/projects/p/agent/style-tests/{gid}/batch-preview',json={'max_not_sent_retries':1}).json()
        bid=preview['id'];assert not physical
        assert c.post(f'/api/projects/p/image-batches/{bid}/start',json={'confirm':True}).status_code==200
        for _ in range(300):
            batch=c.get(f'/api/projects/p/image-batches/{bid}').json()
            if batch['status'] not in ('queued','running'):break
            time.sleep(.02)
        assert batch['status']=='completed',batch
        assert len(physical)==6 and len(calls)==3
        assert batch['payload']['call_limits']['image_network_attempts']==6
        for job in batch['jobs']:
            attempts=job['call']['attempts'];assert [a['evidence']['outcome'] for a in attempts['attempts']]==['not_sent','received']
            assert len({a['id'] for a in attempts['attempts']})==2 and job['output']['adopted']==0
