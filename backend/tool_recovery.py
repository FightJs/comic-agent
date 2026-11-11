"""Freeze verified host results for private, idempotent Node reconciliation.

Call claim/finish inside the caller's BEGIN IMMEDIATE transaction. This module
never commits, executes tools, updates business state, or authorizes continuation.
"""
import hashlib
import json
import re
from fastapi import HTTPException
from .store import dump, now, uid


def schema(db):
    # execute (not executescript) preserves the caller's transaction.
    db.execute('''CREATE TABLE IF NOT EXISTS pi_tool_recoveries(
        project_id TEXT,kind TEXT,owner_id TEXT,recovery_id TEXT UNIQUE,
        evidence_hash TEXT,receipts TEXT,status TEXT,checkpoint TEXT,
        created TEXT,updated TEXT,PRIMARY KEY(project_id,kind,owner_id))''')


def _reject():
    raise HTTPException(409,'工具恢复证据缺失或冲突，不能安全恢复')


def _hash(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _valid_hash(value):
    return isinstance(value,str) and re.fullmatch('[a-f0-9]{64}',value) is not None


def _row(db,pid,kind,owner):
    return db.execute('SELECT * FROM pi_tool_recoveries WHERE project_id=? AND kind=? AND owner_id=?',(pid,kind,owner)).fetchone()


def metadata(db,pid,kind,owner):
    """Public whitelist: no serialized result, argument, error, or filesystem path."""
    row=_row(db,pid,kind,owner)
    if row is None:return None
    return {key:row[key] for key in ('recovery_id','status','created','updated')}


def claim(db,pid,kind,owner,call_ids):
    """Return private {recovery_id, receipts}; caller adds project/session/run IDs."""
    if not db.in_transaction or kind not in ('discussion','production'):_reject()
    if not isinstance(call_ids,list) or not call_ids or any(not isinstance(c,str) or not 1<=len(c)<=200 for c in call_ids):_reject()
    if len(set(call_ids))!=len(call_ids):_reject()
    receipts=[];audit_ids=set()
    for call in sorted(call_ids):
        row=db.execute('SELECT * FROM pi_tool_receipts WHERE project_id=? AND kind=? AND owner_id=? AND call_id=?',(pid,kind,owner,call)).fetchone()
        if row is None or not all(_valid_hash(row[k]) for k in ('node_input_hash','host_input_hash','result_hash')):_reject()
        if not isinstance(row['result'],str) or _hash(row['result'])!=row['result_hash']:_reject()
        try:json.loads(row['result'])
        except (ValueError,TypeError):_reject()
        if kind=='discussion':
            audits=db.execute('SELECT * FROM agent_tool_calls WHERE run_id=? AND call_id=?',(owner,call)).fetchall()
            if len(audits)!=1:_reject()
            audit=audits[0]
            if audit['name']!=row['name'] or audit['input_hash']!=row['host_input_hash'] or audit['result']!=row['result']:_reject()
        else:
            matches=[]
            for audit in db.execute('SELECT * FROM production_tool_calls WHERE attempt_id=? AND name=?',(owner,row['name'])):
                try:host_hash=_hash(dump([audit['name'],json.loads(audit['arguments'])]))
                except (ValueError,TypeError):_reject()
                if host_hash==row['host_input_hash'] and audit['result']==row['result']:matches.append(audit)
            if len(matches)!=1 or matches[0]['id'] in audit_ids:_reject()
            audit_ids.add(matches[0]['id'])
        receipts.append({key:row[key] for key in ('call_id','name','node_input_hash','result_hash') } | {'result_json':row['result']})
    # Include host hashes too: Node's hash alone cannot freeze host audit identity.
    host_hashes=[r[0] for call in sorted(call_ids) for r in db.execute('SELECT host_input_hash FROM pi_tool_receipts WHERE project_id=? AND kind=? AND owner_id=? AND call_id=?',(pid,kind,owner,call))]
    evidence=_hash(dump([receipts,host_hashes]));existing=_row(db,pid,kind,owner)
    if existing:
        if existing['evidence_hash']!=evidence or existing['receipts']!=dump(receipts):_reject()
        return {'recovery_id':existing['recovery_id'],'receipts':receipts}
    recovery=uid();stamp=now()
    db.execute('INSERT INTO pi_tool_recoveries VALUES(?,?,?,?,?,?,?,?,?,?)',(pid,kind,owner,recovery,evidence,dump(receipts),'pending',None,stamp,stamp))
    return {'recovery_id':recovery,'receipts':receipts}


def finish(db,pid,kind,owner,recovery_id,result):
    """Publish completion only after Node durably returns a clean paused summary.

    Caller verifies session ownership and Node's persisted recovery summary, then
    atomically stores its normal business checkpoint along with this transition.
    The full checkpoint is retained privately, including original usage counters.
    """
    row=_row(db,pid,kind,owner)
    if not db.in_transaction or row is None or row['recovery_id']!=recovery_id or not isinstance(result,dict):_reject()
    if result.get('project_id')!=pid or result.get('run_id')!=owner or result.get('recovery_id')!=recovery_id:_reject()
    checkpoint=result.get('checkpoint')
    if not isinstance(checkpoint,dict) or checkpoint.get('run_id')!=owner:_reject()
    if not result.get('session_id') or checkpoint.get('session_id')!=result['session_id']:_reject()
    if checkpoint.get('status')!='paused' or checkpoint.get('session_saved') is not True or checkpoint.get('continued_by'):_reject()
    if any(type(checkpoint.get(k)) is not int or checkpoint[k]!=0 for k in ('unreturned_models','unresolved_tools')):_reject()
    serialized=dump(checkpoint)
    if row['status']=='completed' and row['checkpoint']!=serialized:_reject()
    db.execute('UPDATE pi_tool_recoveries SET status=?,checkpoint=?,updated=? WHERE project_id=? AND kind=? AND owner_id=?',('completed',serialized,now(),pid,kind,owner))
    return metadata(db,pid,kind,owner)


def failed(db,pid,kind,owner,recovery_id):
    """Keep frozen evidence and identity after interruption; store no raw error."""
    row=_row(db,pid,kind,owner)
    if not db.in_transaction or row is None or row['recovery_id']!=recovery_id or row['status']=='completed':_reject()
    db.execute('UPDATE pi_tool_recoveries SET status=?,updated=? WHERE project_id=? AND kind=? AND owner_id=?',('failed',now(),pid,kind,owner))
    return metadata(db,pid,kind,owner)
