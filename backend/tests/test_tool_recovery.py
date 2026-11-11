import hashlib
import json
import sqlite3
import pytest
from fastapi import HTTPException
from backend import tool_receipts, tool_recovery
from backend.store import dump


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def database(kind='discussion'):
    db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
    tool_receipts.schema(db);tool_recovery.schema(db)
    db.execute('CREATE TABLE agent_tool_calls(run_id,call_id,name,input_hash,result,created)')
    db.execute('CREATE TABLE production_tool_calls(id,attempt_id,name,arguments,result,created)')
    args={'secret':'private/path'};result={'body':'PRIVATE'};host=digest(dump(['read',args]))
    db.execute('INSERT INTO pi_tool_receipts VALUES(?,?,?,?,?,?,?,?,?,?)',('p',kind,'o','c','read','a'*64,host,digest(dump(result)),dump(result),'today'))
    db.execute('INSERT INTO agent_tool_calls VALUES(?,?,?,?,?,?)',('o','c','read',host,dump(result),'today'))
    db.execute('INSERT INTO production_tool_calls VALUES(?,?,?,?,?,?)',('audit','o','read',dump(args),dump(result),'today'))
    db.commit();db.execute('BEGIN IMMEDIATE');return db


@pytest.mark.parametrize('kind',['discussion','production'])
def test_claim_freezes_original_result_and_reuses_id(kind):
    db=database(kind);a=tool_recovery.claim(db,'p',kind,'o',['c'])
    assert a==tool_recovery.claim(db,'p',kind,'o',['c'])
    assert a['receipts'][0]['result_json']==dump({'body':'PRIVATE'})
    assert a['recovery_id']
    public=tool_recovery.metadata(db,'p',kind,'o')
    assert 'PRIVATE' not in json.dumps(public) and 'private/path' not in json.dumps(public)
    assert 'receipts' not in public


@pytest.mark.parametrize('mutation',[
    "UPDATE pi_tool_receipts SET node_input_hash=NULL",
    "UPDATE pi_tool_receipts SET result='{}'",
    "DELETE FROM agent_tool_calls",
    "UPDATE agent_tool_calls SET input_hash='bad'",
    "UPDATE pi_tool_receipts SET host_input_hash='bad'",
])
def test_refuses_missing_or_tampered_evidence(mutation):
    db=database();db.execute(mutation)
    with pytest.raises(HTTPException):tool_recovery.claim(db,'p','discussion','o',['c'])


def test_scope_duplicates_and_transaction_rollback():
    db=database()
    for pid,calls in [('other',['c']),('p',['c','c']),('p',[])]:
        with pytest.raises(HTTPException):tool_recovery.claim(db,pid,'discussion','o',calls)
    first=tool_recovery.claim(db,'p','discussion','o',['c']);db.rollback()
    assert tool_recovery.metadata(db,'p','discussion','o') is None
    db.execute('BEGIN IMMEDIATE');assert tool_recovery.claim(db,'p','discussion','o',['c'])['recovery_id']!=first['recovery_id']


def test_production_ambiguous_audit_refused():
    db=database('production');db.execute('INSERT INTO production_tool_calls SELECT * FROM production_tool_calls')
    with pytest.raises(HTTPException):tool_recovery.claim(db,'p','production','o',['c'])


def test_claim_rejects_changed_evidence_and_finish_requires_clean_owner():
    db=database();a=tool_recovery.claim(db,'p','discussion','o',['c'])
    db.execute("UPDATE pi_tool_receipts SET node_input_hash=?",('b'*64,))
    with pytest.raises(HTTPException):tool_recovery.claim(db,'p','discussion','o',['c'])
    checkpoint={'project_id':'p','run_id':'o','session_id':'s','recovery_id':a['recovery_id'],'status':'paused','session_saved':True,'unreturned_models':0,'unresolved_tools':0,'usage':{'tokens':7}}
    for changes in [{'run_id':'other'},{'status':'running'},{'unresolved_tools':1},{'recovery_id':'wrong'},{'session_saved':False}]:
        with pytest.raises(HTTPException):tool_recovery.finish(db,'p','discussion','o',a['recovery_id'],{'project_id':'p','run_id':'o','session_id':'s','recovery_id':a['recovery_id'],'checkpoint':dict(checkpoint,**changes)} if 'recovery_id' not in changes else dict(changes,project_id='p',run_id='o',session_id='s',checkpoint=checkpoint))
    tool_recovery.finish(db,'p','discussion','o',a['recovery_id'],{'project_id':'p','run_id':'o','session_id':'s','recovery_id':a['recovery_id'],'checkpoint':checkpoint})
    assert tool_recovery.metadata(db,'p','discussion','o')['status']=='completed'
    assert json.loads(db.execute('SELECT checkpoint FROM pi_tool_recoveries').fetchone()[0])['usage']=={'tokens':7}


def test_failed_claim_reuses_fixed_id_and_public_error_is_sanitized():
    db=database();a=tool_recovery.claim(db,'p','discussion','o',['c'])
    tool_recovery.failed(db,'p','discussion','o',a['recovery_id'])
    assert tool_recovery.metadata(db,'p','discussion','o')['status']=='failed'
    assert tool_recovery.claim(db,'p','discussion','o',['c'])==a
    with pytest.raises(HTTPException):tool_recovery.failed(db,'p','discussion','o','wrong')


def test_requires_transaction_and_rejects_multiple_call_ids_for_one_production_audit():
    db=database('production');db.execute("INSERT INTO pi_tool_receipts SELECT project_id,kind,owner_id,'second',name,node_input_hash,host_input_hash,result_hash,result,created FROM pi_tool_receipts")
    with pytest.raises(HTTPException):tool_recovery.claim(db,'p','production','o',['c','second'])
    db.commit()
    with pytest.raises(HTTPException):tool_recovery.claim(db,'p','production','o',['c'])


def test_finish_accepts_authenticated_outer_without_forging_checkpoint_fields():
    db=database();a=tool_recovery.claim(db,'p','discussion','o',['c'])
    cp={'run_id':'o','session_id':'s','status':'paused','session_saved':True,'unreturned_models':0,'unresolved_tools':0,'usage':{'tokens':9}}
    result={'project_id':'p','run_id':'o','session_id':'s','recovery_id':a['recovery_id'],'checkpoint':cp}
    tool_recovery.finish(db,'p','discussion','o',a['recovery_id'],result)
    assert json.loads(db.execute('SELECT checkpoint FROM pi_tool_recoveries').fetchone()[0])==cp


@pytest.mark.parametrize('change',[{'project_id':'other'},{'run_id':'other'},{'session_id':'other'},{'recovery_id':'other'}])
def test_finish_rejects_outer_scope_change(change):
    db=database();a=tool_recovery.claim(db,'p','discussion','o',['c'])
    cp={'run_id':'o','session_id':'s','status':'paused','session_saved':True,'unreturned_models':0,'unresolved_tools':0}
    result={'project_id':'p','run_id':'o','session_id':'s','recovery_id':a['recovery_id'],'checkpoint':cp}
    with pytest.raises(HTTPException):tool_recovery.finish(db,'p','discussion','o',a['recovery_id'],dict(result,**change))
