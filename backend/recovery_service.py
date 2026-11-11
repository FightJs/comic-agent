"""Explicit offline reconciliation; persistent locks survive interrupted requests."""
import json
from pydantic import BaseModel, ConfigDict, Field
from fastapi import HTTPException
from . import tool_recovery, tool_receipts
from .store import dump

# Strict bool rejects integer 1; the validator requires an affirmative grant.
from pydantic import field_validator
class RecoverProduction(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    confirm:bool
    @field_validator('confirm')
    @classmethod
    def authorized(cls,value):
        if value is not True:raise ValueError('需要明确确认仅补已有结果')
        return value
class RecoverDiscussion(RecoverProduction):
    expected_version:int=Field(ge=0)

_active=set()
def schema(db):
    tool_recovery.schema(db)
    db.execute('CREATE TABLE IF NOT EXISTS pi_recovery_locks(project_id TEXT,session_id TEXT,owner_id TEXT,recovery_id TEXT,snapshot TEXT,PRIMARY KEY(project_id,session_id))')

def unlocked(db,pid,sid):
    if db.execute('SELECT 1 FROM pi_recovery_locks WHERE project_id=? AND session_id=?',(pid,sid)).fetchone():raise HTTPException(409,'工具结果正在恢复或待核对；请重试原恢复请求或取消')

def call_ids(cp):
    if (cp.get('status') not in ('failed','interrupted','paused') and not (cp.get('status')=='running' and cp.get('_interrupted') is True)) or cp.get('continued_by') or type(cp.get('unreturned_models')) is not int or cp['unreturned_models']!=0:raise HTTPException(409,'检查点不支持工具结果恢复')
    tools=cp.get('tools',[]);pending=[t for t in tools if t.get('status')=='registered']
    groups={t.get('assistant_leaf_id') for t in pending}
    if not pending or len(groups)!=1 or None in groups or '' in groups:raise HTTPException(409,'没有唯一可核对的工具组')
    return [t['id'] for t in tools if t.get('assistant_leaf_id') in groups]

def counters(cp):
    keys=('run_id','session_id','input_hash','model_requests','unreturned_models','tool_calls','unknown_usage_requests','usage','usage_complete','parent_run_id','continued_by')
    return {k:cp.get(k) for k in keys}

async def details(runtime,pid,sid,owner):
    try:response=await runtime.request('checkpoint_details',project_id=pid,session_id=sid,run_id=owner,timeout=10)
    except Exception:raise HTTPException(503,'Pi回执暂不可读取；未调用模型或工具')
    cp=response.get('data',{}).get('checkpoint',{})
    if response.get('type')!='result' or cp.get('run_id')!=owner or cp.get('session_id')!=sid:raise HTTPException(409,'检查点缺失或归属冲突')
    return {**cp,'_interrupted':response.get('data',{}).get('interrupted') is True}

def available(db,pid,kind,owner,status,cp):
    try:
        if status not in ('error','failed','interrupted','paused'):return False
        lock=db.execute('SELECT snapshot FROM pi_recovery_locks WHERE project_id=? AND owner_id=?',(pid,owner)).fetchone()
        if lock:
            stopped=cp.get('status') in ('failed','interrupted','paused') or cp.get('status')=='running' and cp.get('_interrupted') is True
            return stopped and not cp.get('continued_by') and counters(cp)==json.loads(lock['snapshot'])['counters']
        ids=call_ids(cp);compared=tool_receipts.compare(tool_receipts.summaries(db,pid,kind,owner),cp)
        return all(x['state'] in ('host_saved_node_unconfirmed','matched') for x in compared if x['call_id'] in ids) and set(ids)<=set(x['call_id'] for x in compared)
    except (HTTPException,KeyError,TypeError):return False

def binding(db,kind,owner):
    if kind=='discussion':
        request=db.execute('SELECT prompt,config FROM agent_requests WHERE run_id=?',(owner,)).fetchone()
        frozen=db.execute('SELECT manifest FROM agent_inputs WHERE run_id=?',(owner,)).fetchone()
        if request is None or frozen is None:raise HTTPException(409,'缺少冻结请求')
        return [list(request),list(frozen)]
    request=db.execute('SELECT content FROM production_requests WHERE attempt_id=?',(owner,)).fetchone()
    payload=db.execute('SELECT t.payload FROM tasks t JOIN production_attempts a ON a.task_id=t.id WHERE a.id=?',(owner,)).fetchone()
    if request is None or payload is None:raise HTTPException(409,'缺少冻结请求')
    return [list(request),list(payload)]

async def recover(store,runtime,pid,kind,owner,sid,validate,publish):
    token=(pid,sid)
    if token in _active:raise HTTPException(409,'恢复请求仍在核对中')
    _active.add(token)
    try:
        cp=await details(runtime,pid,sid,owner)
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE');validate(db)
            original_binding=binding(db,kind,owner)
            lock=db.execute('SELECT * FROM pi_recovery_locks WHERE project_id=? AND session_id=?',(pid,sid)).fetchone()
            if lock:
                if lock['owner_id']!=owner:raise HTTPException(409,'会话有另一恢复请求')
                frozen=json.loads(lock['snapshot']);ids=frozen['ids'];before=frozen['counters']
                if frozen['binding']!=original_binding:raise HTTPException(409,'原始请求已变化')
            else:ids=call_ids(cp);before=counters(cp)
            if counters(cp)!=before:raise HTTPException(409,'恢复前原计数已变化')
            claim=tool_recovery.claim(db,pid,kind,owner,ids)
            if lock and lock['recovery_id']!=claim['recovery_id']:raise HTTPException(409,'恢复编号冲突')
            if not lock:db.execute('INSERT INTO pi_recovery_locks VALUES(?,?,?,?,?)',(pid,sid,owner,claim['recovery_id'],dump({'ids':ids,'counters':before,'binding':original_binding})))
        try:response=await runtime.request('recover_tools',project_id=pid,session_id=sid,run_id=owner,**claim,timeout=30)
        except Exception:raise HTTPException(503,'恢复尚未确认；请重试同一恢复请求')
        result=response.get('data',{});after=await details(runtime,pid,sid,owner)
        if response.get('type')!='result' or result.get('session_id')!=sid or result.get('checkpoint')!= {k:v for k,v in after.items() if k not in ('tools','_interrupted')} or counters(after)!=before:raise HTTPException(409,'恢复结果或原计数冲突；保留原恢复记录')
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE');validate(db)
            compared=tool_receipts.compare(tool_receipts.summaries(db,pid,kind,owner),after)
            if any(x['state']!='matched' for x in compared if x['call_id'] in ids) or not set(ids)<=set(x['call_id'] for x in compared):raise HTTPException(409,'持久回执未完整匹配')
            if binding(db,kind,owner)!=original_binding:raise HTTPException(409,'原始请求已变化')
            tool_recovery.finish(db,pid,kind,owner,claim['recovery_id'],result)
            value=publish(db,{k:v for k,v in after.items() if k!='_interrupted'})
            db.execute('DELETE FROM pi_recovery_locks WHERE project_id=? AND session_id=? AND owner_id=?',(pid,sid,owner))
            return value
    finally:_active.discard(token)
