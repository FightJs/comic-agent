"""Approved text-production reference state remains relevant through adoption."""
import json
import pytest
from backend.tests.test_workflow import setup


def fixture(tmp_path):
    c,b,add=setup(tmp_path);c.app.state.provider_secret_get=lambda purpose:'synthetic-reference-only'
    script=add('script',{'episode':1,'panel':1,'batch':1,'description':'原稿'})
    asset=add('asset',{'description':'批准人物参考'})
    assert c.post(b+f"/records/{asset['id']}/reviews",json={'version':1,'decision':'approved','note':'合成依据'}).status_code==200
    return c,b,add,script,asset


def revoke(c,b,asset):
    response=c.post(b+f"/records/{asset['id']}/reviews",json={'version':1,'decision':'changes','note':'撤回批准'})
    assert response.status_code==200,response.text


def submit(c,b,script,token='new'):
    response=c.post(b+'/production-jobs',json={'operation':'package','refs':[{'id':script['id'],'version':1}],'submission_id':token})
    assert response.status_code==200,response.text
    return c.get(b+'/tasks').json()[0]


@pytest.mark.parametrize('timing',['before_dispatch','inflight','after_return'])
@pytest.mark.parametrize('existing',[False,True])
def test_revoked_approval_never_becomes_adopted_package(tmp_path,timing,existing):
    c,b,add,script,asset=fixture(tmp_path)
    target=add('package',{'episode':1,'panel':1,'prompt':'旧生图包'}) if existing else None
    original=c.app.state.pi_runtime.request;submitted=[]
    async def request(command,**kw):
        if timing=='before_dispatch':revoke(c,b,asset)
        if kw.get('before_dispatch'):kw['before_dispatch']()
        submitted.append(kw)
        if timing=='inflight':revoke(c,b,asset)
        return await original(command,**kw)
    c.app.state.pi_runtime.request=request
    task=submit(c,b,script)
    if timing=='before_dispatch':
        assert task['status']=='failed' and submitted==[] and not task['output_id']
    else:
        assert task['status']=='succeeded'
        candidate=c.get(b+'/records/'+task['output_id']).json()
        assert candidate['adopted']==0
        if timing=='inflight':assert candidate['content']['input_stale'] is True
        if timing=='after_return':revoke(c,b,asset)
        response=c.post(b+f"/candidates/{candidate['id']}/adopt",json={})
        assert response.status_code==409,response.text
        assert c.get(b+'/records/'+candidate['id']).json()['adopted']==0
        assert len(submitted)==1
    assert c.get(b+'/records/'+script['id']).json()['version']==1
    if target:assert c.get(b+'/records/'+target['id']).json()['version']==1


def test_unchanged_approved_reference_still_allows_explicit_adoption(tmp_path):
    c,b,_,script,asset=fixture(tmp_path)
    task=submit(c,b,script);assert task['status']=='succeeded'
    assert c.post(b+f"/candidates/{task['output_id']}/adopt",json={}).status_code==200


def test_review_change_of_unrelated_reference_does_not_invalidate_candidate(tmp_path):
    c,b,add,script,asset=fixture(tmp_path)
    unrelated=add('asset',{'description':'未批准，不参与生成'})
    task=submit(c,b,script);assert task['status']=='succeeded'
    revoke(c,b,unrelated)
    assert c.post(b+f"/candidates/{task['output_id']}/adopt",json={}).status_code==200


def test_switching_adopted_reference_without_head_change_blocks_adoption(tmp_path):
    c,b,_,script,asset=fixture(tmp_path)
    updated=c.put(b+f"/records/{asset['id']}",json={'expected_version':1,'content':{'description':'新版参考'}});assert updated.status_code==200,updated.text
    assert c.post(b+f"/records/{asset['id']}/reviews",json={'version':2,'decision':'approved','note':'合成批准'}).status_code==200
    assert c.post(b+f"/records/{asset['id']}/adopt",json={'version':2}).status_code==200
    task=submit(c,b,script);assert task['status']=='succeeded'
    assert c.post(b+f"/records/{asset['id']}/adopt",json={'version':1}).status_code==200
    assert c.get(b+f"/records/{asset['id']}").json()['version']==2
    response=c.post(b+f"/candidates/{task['output_id']}/adopt",json={})
    assert response.status_code==409,response.text


@pytest.mark.parametrize('missing',['review','adopted','version','record'])
def test_missing_frozen_state_or_missing_reference_fails_closed(tmp_path,missing):
    from backend.production_references import state_stale
    c,b,_,_,asset=fixture(tmp_path)
    snapshot=c.get(b+f"/records/{asset['id']}").json()
    if missing in ('review','adopted'):snapshot.pop(missing)
    elif missing=='version':snapshot['version']=999
    else:snapshot['id']='missing-record'
    with c.app.state.store.db() as db:
        assert state_stale(c.app.state.store,db,asset['project_id'],[snapshot]) is True
