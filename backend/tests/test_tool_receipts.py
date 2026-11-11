import hashlib
import pytest
from fastapi import HTTPException
from backend.store import Store,dump
from backend import tool_receipts as receipts


def test_atomic_receipts_retry_conflict_and_legacy(tmp_path):
    store=Store(tmp_path)
    message={'tool_call_id':'call','name':'project_query','arguments':{'number':1e-7},'input_hash':'a'*64}
    result={'text':'private synthetic 中文','value':1e-7}
    with store.db() as db:
        receipts.schema(db)
        assert receipts.lookup(db,'p','discussion','r',message) is None
        receipts.save(db,'p','discussion','r',message,result)
    with store.db() as db:
        assert receipts.lookup(db,'p','discussion','r',message)==result
        assert receipts.lookup(db,'other','discussion','r',message) is None
        for changed in ({'input_hash':'b'*64},{'arguments':{'number':2}},{'input_hash':None}):
            with pytest.raises(HTTPException):receipts.lookup(db,'p','discussion','r',{**message,**changed})
        summary=receipts.summaries(db,'p','discussion','r')
        assert summary[0]['result_hash']==hashlib.sha256(dump(result).encode()).hexdigest()
        assert 'private synthetic' not in dump(summary)
        receipts.save(db,'p','production','attempt',{'name':'project_query'},result)
        assert receipts.summaries(db,'p','production','attempt')==[]
    with pytest.raises(RuntimeError):
        with store.db() as db:
            receipts.save(db,'p','discussion','rollback',{**message,'tool_call_id':'rolled'},result)
            raise RuntimeError('rollback')
    with store.db() as db:assert receipts.summaries(db,'p','discussion','rollback')==[]


def test_comparison_requires_exact_host_encoding_and_input():
    host=[{'call_id':'a','name':'project_query','node_input_hash':'a'*64,'result_hash':'b'*64}]
    node={'tools':[{'id':'a','name':'project_query','input_hash':'a'*64,'status':'registered'}]}
    assert receipts.compare(host,node)[0]['state']=='host_saved_node_unconfirmed'
    node['tools'][0].update(status='received',result_hash='b'*64,result_encoding='host_json')
    assert receipts.compare(host,node)[0]['state']=='matched'
    node['tools'][0]['result_encoding']='local_json'
    assert receipts.compare(host,node)[0]['state']=='unverified'
    node['tools'][0]['input_hash']='c'*64
    assert receipts.compare(host,node)[0]['state']=='mismatch'
    assert receipts.compare([],node)[0]['state']=='missing_or_legacy'
