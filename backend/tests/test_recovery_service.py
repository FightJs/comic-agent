import asyncio
import functools
import pytest
from pydantic import ValidationError
from backend import recovery_service as r


def test_strict_authorization():
    for confirm in (False,1,'true'):
        with pytest.raises(ValidationError):r.RecoverDiscussion(confirm=confirm,expected_version=0)
    with pytest.raises(ValidationError):r.RecoverDiscussion(confirm=True,expected_version=True)
    assert r.RecoverProduction(confirm=True).confirm is True


def test_exact_assistant_group_and_unknown_models():
    cp={'status':'failed','run_id':'r','session_id':'s','unreturned_models':0,'continued_by':None,'tools':[{'id':'a','assistant_leaf_id':'leaf','status':'registered'},{'id':'b','assistant_leaf_id':'leaf','status':'received'}]}
    assert r.call_ids(cp)==['a','b']
    for changed in ({'unreturned_models':1},{'status':'cancelled'},{'tools':[{'id':'x','status':'registered'}]}):
        with pytest.raises(Exception):r.call_ids({**cp,**changed})

def sync_test(fn):
    @functools.wraps(fn)
    def wrapped(*args,**kwargs):return asyncio.run(fn(*args,**kwargs))
    return wrapped

import hashlib
import json
from fastapi import HTTPException
from backend.store import Store,dump
from backend import tool_receipts

@pytest.fixture
def evidence(tmp_path):
    store=Store(tmp_path)
    message={'tool_call_id':'a','name':'project_query','arguments':{},'input_hash':'a'*64}
    result={'synthetic':True}
    with store.db() as db:
        tool_receipts.schema(db);r.schema(db)
        db.execute('CREATE TABLE agent_requests(run_id,prompt,config)')
        db.execute('CREATE TABLE agent_inputs(run_id,manifest)')
        db.execute("INSERT INTO agent_requests VALUES('r','prompt','config')")
        db.execute("INSERT INTO agent_inputs VALUES('r','frozen')")
        db.execute('CREATE TABLE agent_tool_calls(run_id,call_id,name,input_hash,result)')
        tool_receipts.save(db,'p','discussion','r',message,result)
        db.execute('INSERT INTO agent_tool_calls VALUES(?,?,?,?,?)',('r','a','project_query',hashlib.sha256(dump(['project_query',{}]).encode()).hexdigest(),dump(result)))
    cp={'run_id':'r','session_id':'s','status':'failed','unreturned_models':0,'unresolved_tools':1,'continued_by':None,'model_requests':1,'tool_calls':1,'usage':{'totalTokens':6},'session_saved':True,'tools':[{'id':'a','name':'project_query','input_hash':'a'*64,'assistant_leaf_id':'leaf','status':'registered'}]}
    return store,cp

@sync_test
async def test_failed_pending_retry_preserves_identity_and_usage(evidence):
    store,cp=evidence;calls=[];published=[]
    class Runtime:
        fail=True
        async def request(self,command,**kw):
            if command=='checkpoint_details':return {'type':'result','data':{'checkpoint':cp.copy()}}
            calls.append(kw['recovery_id'])
            if self.fail:raise RuntimeError('offline')
            cp.update(status='paused',unresolved_tools=0,reason='tools_recovered')
            cp['tools'][0].update(status='received',result_encoding='host_json',result_hash=hashlib.sha256(dump({'synthetic':True}).encode()).hexdigest())
            return {'type':'result','data':{'project_id':'p','run_id':'r','session_id':'s','recovery_id':kw['recovery_id'],'checkpoint':{k:v for k,v in cp.items() if k!='tools'}}}
    runtime=Runtime()
    with pytest.raises(HTTPException) as error:await r.recover(store,runtime,'p','discussion','r','s',lambda db:None,lambda db,cp:published.append(cp))
    assert error.value.status_code==503
    with store.db() as db:
        with pytest.raises(HTTPException):r.unlocked(db,'p','s')
    runtime.fail=False
    await r.recover(store,runtime,'p','discussion','r','s',lambda db:None,lambda db,cp:published.append(cp))
    assert calls[0]==calls[1] and len(published)==1 and published[0]['usage']['totalTokens']==6
    with store.db() as db:r.unlocked(db,'p','s')

@sync_test
@pytest.mark.parametrize('tamper',['usage','cancel'])
async def test_no_publish_on_counter_change_or_cancel(evidence,tamper):
    store,cp=evidence;cancelled=False;published=[]
    def validate(db):
        if cancelled:raise HTTPException(409,'cancelled')
    class Runtime:
        async def request(self,command,**kw):
            nonlocal cancelled
            if command=='checkpoint_details':return {'type':'result','data':{'checkpoint':json.loads(dump(cp))}}
            if tamper=='cancel':cancelled=True
            else:cp['usage']={'totalTokens':0}
            cp.update(status='paused',unresolved_tools=0)
            return {'type':'result','data':{'project_id':'p','run_id':'r','session_id':'s','recovery_id':kw['recovery_id'],'checkpoint':{k:v for k,v in cp.items() if k!='tools'}}}
    with pytest.raises(HTTPException):await r.recover(store,Runtime(),'p','discussion','r','s',validate,lambda db,cp:published.append(cp))
    assert not published

@sync_test
async def test_parallel_recovery_rejected_without_second_dispatch(evidence):
    store,cp=evidence;started=asyncio.Event();release=asyncio.Event();calls=[]
    class Runtime:
        async def request(self,command,**kw):
            if command=='checkpoint_details':return {'type':'result','data':{'checkpoint':cp.copy()}}
            calls.append(kw);started.set();await release.wait();raise RuntimeError('offline')
    runtime=Runtime()
    first=asyncio.create_task(r.recover(store,runtime,'p','discussion','r','s',lambda db:None,lambda db,cp:None))
    await started.wait()
    with pytest.raises(HTTPException) as error:await r.recover(store,runtime,'p','discussion','r','s',lambda db:None,lambda db,cp:None)
    assert error.value.status_code==409 and len(calls)==1
    release.set()
    with pytest.raises(HTTPException):await first
