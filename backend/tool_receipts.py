"""Atomic host receipts. Metadata can reconcile evidence, never authorize replay."""
import hashlib
import json
import re
from fastapi import HTTPException
from .store import dump,now


def schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS pi_tool_receipts(
        project_id TEXT,kind TEXT,owner_id TEXT,call_id TEXT,name TEXT,
        node_input_hash TEXT,host_input_hash TEXT,result_hash TEXT,result TEXT,created TEXT,
        PRIMARY KEY(project_id,kind,owner_id,call_id))''')


def identity(message):
    call=message.get('tool_call_id');node=message.get('input_hash')
    # Old in-process callers without IDs remain legacy, without invented evidence.
    if call is None and node is None:return None
    if not isinstance(call,str) or not 1<=len(call)<=200:raise HTTPException(409,'工具回执编号无效')
    if node is not None and (not isinstance(node,str) or not re.fullmatch('[a-f0-9]{64}',node)):raise HTTPException(409,'工具输入摘要无效')
    digest=hashlib.sha256(dump([message.get('name'),message.get('arguments')]).encode()).hexdigest()
    return call,node,digest


def lookup(db,pid,kind,owner,message):
    value=identity(message)
    if value is None:return None
    call,node,digest=value
    row=db.execute('SELECT * FROM pi_tool_receipts WHERE project_id=? AND kind=? AND owner_id=? AND call_id=?',(pid,kind,owner,call)).fetchone()
    if row is None:return None
    if row['name']!=message.get('name') or row['node_input_hash']!=node or row['host_input_hash']!=digest:raise HTTPException(409,'工具编号或输入摘要冲突')
    return json.loads(row['result'])


def save(db,pid,kind,owner,message,result):
    value=identity(message)
    if value is None:return
    call,node,digest=value;serialized=dump(result)
    db.execute('INSERT INTO pi_tool_receipts VALUES(?,?,?,?,?,?,?,?,?,?)',(pid,kind,owner,call,message.get('name'),node,digest,hashlib.sha256(serialized.encode()).hexdigest(),serialized,now()))


def summaries(db,pid,kind,owner):
    return [dict(row) for row in db.execute('SELECT call_id,name,node_input_hash,result_hash,created FROM pi_tool_receipts WHERE project_id=? AND kind=? AND owner_id=? ORDER BY created,call_id',(pid,kind,owner))]


def compare(host,checkpoint):
    saved={row['call_id']:row for row in host};registered={row['id']:row for row in checkpoint.get('tools',[])}
    output=[]
    for call in sorted(saved.keys()|registered.keys()):
        h=saved.get(call);n=registered.get(call);state='missing_or_legacy'
        if h and n:
            if h['name']!=n['name'] or h['node_input_hash'] is not None and h['node_input_hash']!=n['input_hash']:state='mismatch'
            elif h['node_input_hash'] is None:state='unverified'
            elif n['status']=='registered':state='host_saved_node_unconfirmed'
            elif n.get('result_encoding')!='host_json':state='unverified'
            elif h['result_hash']!=n.get('result_hash'):state='mismatch'
            else:state='matched'
        output.append({'call_id':call,'name':(h or n)['name'],'state':state,'host_saved':h is not None,'node_status':n['status'] if n else None})
    return output
