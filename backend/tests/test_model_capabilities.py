import json
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.store import Store,dump
from backend.model_capabilities import register_model_capabilities

@pytest.fixture
def env(tmp_path):
    store=Store(tmp_path);app=FastAPI()
    with store.db() as db:
        db.execute('INSERT INTO projects VALUES(?,?,?,?,?)',('p','private',0,'t','t'))
        db.execute('INSERT INTO projects VALUES(?,?,?,?,?)',('other','other',0,'t','t'))
        db.execute('INSERT INTO settings VALUES(1,?)',(dump({'text':{'url':'http://localhost:123','model':'m'},'image':{'url':'http://localhost:123','model':'m','api':'openai-images'},'vision':{'url':'http://localhost:123','model':'m'}}),))
        db.execute('CREATE TABLE agent_runs(id TEXT PRIMARY KEY,project_id TEXT,session_id TEXT,status TEXT,reply TEXT,created TEXT,updated TEXT)')
        db.execute('CREATE TABLE agent_requests(run_id TEXT PRIMARY KEY,config TEXT)')
        db.execute('CREATE TABLE image_calls(id TEXT PRIMARY KEY,project_id TEXT,manifest TEXT,status TEXT,result TEXT,created TEXT,updated TEXT)')
        db.execute('CREATE TABLE vision_reviews(id TEXT PRIMARY KEY,project_id TEXT,manifest TEXT,status TEXT,raw TEXT,report TEXT,created TEXT,updated TEXT)')
        db.execute('INSERT INTO agent_runs VALUES(?,?,?,?,?,?,?)',('r','p','s','completed','SECRET正文','t','t'))
        db.execute('INSERT INTO agent_requests VALUES(?,?)',('r',dump({'url':'http://localhost:123','model':'m'})))
    register_model_capabilities(app,store)
    return store,app,TestClient(app)

def test_unverified_get_does_not_reconcile_or_expose_text(env):
    store,app,client=env
    result=client.get('/api/projects/p/model-capabilities').json()
    assert len(result['capabilities'])==5
    assert all(c['status']=='unverified' for c in result['capabilities'])
    assert len(result['candidates'])==2
    assert 'SECRET' not in json.dumps(result)

def test_reconcile_text_idempotence_and_profile_staleness(env):
    store,app,c=env
    body={'evidence':[{'kind':'text','receipt_id':'r'}]}
    a=c.post('/api/projects/p/model-capabilities/reconcile',json=body)
    assert a.status_code==200
    item=a.json()['capabilities'][0]
    assert item['status']=='verified' and item['source']=='unknown'
    assert c.post('/api/projects/p/model-capabilities/reconcile',json=body).json()==a.json()
    with store.db() as db:
        db.execute('UPDATE settings SET content=?',(dump({'text':{'url':'http://localhost:123','model':'changed'}}),))
    assert c.get('/api/projects/p/model-capabilities').json()['capabilities'][0]['status']=='stale'

def test_project_isolation_and_strict_input(env):
    _,_,c=env
    assert c.post('/api/projects/other/model-capabilities/reconcile',json={'evidence':[{'kind':'text','receipt_id':'r'}]}).status_code==404
    assert c.get('/api/projects/other/model-capabilities').json()['candidates']==[]
    assert c.post('/api/projects/p/model-capabilities/reconcile',json={'evidence':[{'kind':'text','receipt_id':'r','secret':'bad'}]}).status_code==422
    assert c.post('/api/projects/p/model-capabilities/reconcile',json={'evidence':[]}).status_code==422

def test_tool_without_sdk_confirmation_remains_unverified(env):
    _,_,c=env
    result=c.post('/api/projects/p/model-capabilities/reconcile',json={'evidence':[{'kind':'tool','receipt_id':'r'}]}).json()
    item=result['capabilities'][1]
    assert item['status']=='unverified' and 'tool_roundtrip_unproven' in item['reason_codes']

def image(env,*,kind='generate',status='completed',pid='p',cid='i',source='ai',refs=(),mask=None):
    store,_,_=env
    manifest={'provider':{'url':'http://localhost:123','model':'m','api':'openai-images'},'operation':kind,'references':list(refs),'mask':mask,'source':source,'prompt':'SECRET'}
    with store.db() as db:
        db.execute('INSERT INTO image_calls VALUES(?,?,?,?,?,?,?)',(cid,pid,dump(manifest),status,dump({'url':f'/api/projects/{pid}/files/file','sha256':'a'*64,'width':1,'height':1,'format':'PNG'}),'t','t'))

def test_generation_does_not_prove_edit_and_unknown_never_verifies(env):
    image(env);_,_,c=env
    res=c.post('/api/projects/p/model-capabilities/reconcile',json={'evidence':[{'kind':'generation','receipt_id':'i'}]}).json()
    assert res['capabilities'][3]['status']=='verified'
    assert res['capabilities'][4]['status']=='unverified'
    assert c.post('/api/projects/p/model-capabilities/reconcile',json={'evidence':[{'kind':'edit','receipt_id':'i'}]}).status_code==409
    image(env,cid='unknown',status='unknown')
    assert c.post('/api/projects/p/model-capabilities/reconcile',json={'evidence':[{'kind':'generation','receipt_id':'unknown'}]}).status_code==409
    assert 'SECRET' not in json.dumps(res)

def test_candidate_bound_and_edit_observations(env):
    for n in range(25):image(env,cid=str(n))
    image(env,cid='edit',kind='edit',refs=[{'sha256':'a'*64,'file_id':'f'},{'sha256':'b'*64,'file_id':'g'}],mask={'sha256':'c'*64,'file_id':'h'})
    _,_,c=env
    res=c.post('/api/projects/p/model-capabilities/reconcile',json={'evidence':[{'kind':'edit','receipt_id':'edit'}]}).json()
    assert len([r for r in res['candidates'] if r['kind']=='generation'])==20
    assert res['capabilities'][4]['limits']=={'reference_count':2,'mask_observed':True}

def test_vision_requires_actual_image_manifest_and_valid_exact_report(env):
    store,_,c=env
    report={'summary':'SECRET','issues':[]}
    manifest={'provider':{'url':'http://localhost:123','model':'m'},'images':[{'file_id':'f','sha256':'a'*64}],'sources':[],'source':'ai'}
    with store.db() as db:
        db.execute('INSERT INTO vision_reviews VALUES(?,?,?,?,?,?,?,?)',('v','p',dump(manifest),'completed',dump(report),dump(report),'t','t'))
    res=c.post('/api/projects/p/model-capabilities/reconcile',json={'evidence':[{'kind':'vision','receipt_id':'v'}]})
    assert res.status_code==200 and res.json()['capabilities'][2]['status']=='verified'
    assert 'SECRET' not in json.dumps(res.json())
    with store.db() as db:db.execute('UPDATE vision_reviews SET report=?',(dump({'summary':'different','issues':[]}),))
    assert c.post('/api/projects/p/model-capabilities/reconcile',json={'evidence':[{'kind':'vision','receipt_id':'v'}]}).status_code==409

def test_tool_requires_exact_sdk_result_roundtrip_and_only_reads_checkpoint(env):
    from backend import tool_receipts
    store,app,c=env
    message={'tool_call_id':'call','name':'project_query','arguments':{},'input_hash':'a'*64}
    with store.db() as db:
        tool_receipts.schema(db);tool_receipts.save(db,'p','discussion','r',message,{'secret':'PRIVATE'})
        host=tool_receipts.summaries(db,'p','discussion','r')[0]
    checkpoint={'run_id':'r','session_id':'s','tools':[{'id':'call','name':'project_query','input_hash':'a'*64,'result_hash':host['result_hash'],'result_encoding':'host_json','status':'received'}]}
    calls=[]
    class Runtime:
        async def request(self,command,**kwargs):
            calls.append((command,kwargs));return {'type':'result','data':{'checkpoint':checkpoint}}
    app.state.pi_runtime=Runtime()
    body={'evidence':[{'kind':'tool','receipt_id':'r'}]}
    good=c.post('/api/projects/p/model-capabilities/reconcile',json=body)
    assert good.json()['capabilities'][1]['status']=='verified'
    assert calls==[('checkpoint_details',{'project_id':'p','session_id':'s','run_id':'r','timeout':10})]
    assert 'PRIVATE' not in good.text
    checkpoint['tools'][0]['result_hash']='b'*64
    assert c.post('/api/projects/p/model-capabilities/reconcile',json=body).json()['capabilities'][1]['status']=='unverified'

def test_remote_ai_source_never_becomes_real_validation(env):
    store,_,c=env
    with store.db() as db:
        profile={'url':'https://api.example.test','model':'m'}
        db.execute('UPDATE settings SET content=?',(dump({'text':profile}),))
        db.execute('UPDATE agent_requests SET config=?',(dump(profile),))
    result=c.post('/api/projects/p/model-capabilities/reconcile',json={'evidence':[{'kind':'text','receipt_id':'r'}]}).json()['capabilities'][0]
    assert result['status']=='verified' and result['source']=='unknown'
    assert 'api.example' not in json.dumps(result)

def test_batch_failure_does_not_partially_register(env):
    _,_,c=env
    response=c.post('/api/projects/p/model-capabilities/reconcile',json={'evidence':[{'kind':'text','receipt_id':'r'},{'kind':'vision','receipt_id':'missing'}]})
    assert response.status_code==404
    assert c.get('/api/projects/p/model-capabilities').json()['capabilities'][0]['status']=='unverified'


def test_local_provider_is_unknown_and_mock_input_does_not_identify_provider(env):
    from backend.model_capabilities import origin
    for address in ('http://localhost:11434','http://127.0.0.1:1234','http://[::1]:1234','https://api.example.test'):
        assert origin({'url':address})=='unknown'
        assert origin({'url':address},{'source':'ai'})=='unknown'
        assert origin({'url':address},{'source':'mock'})=='mock'
    _,_,c=env
    result=c.post('/api/projects/p/model-capabilities/reconcile',json={'evidence':[{'kind':'text','receipt_id':'r'}]}).json()
    assert result['capabilities'][0]['source']=='unknown'
    assert all(candidate['source']=='unknown' for candidate in result['candidates'])
