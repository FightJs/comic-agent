"""Production continuation metadata; no automatic replay of unknown calls."""
import json
from fastapi import HTTPException
from pydantic import BaseModel,ConfigDict
from . import preferences,graph_store,production_references
from .skills import frozen_skills

class ProductionPaused(Exception):pass

class ContinueProduction(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    confirm:bool

def schema(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS production_requests(attempt_id TEXT PRIMARY KEY,content TEXT);
    CREATE TABLE IF NOT EXISTS production_checkpoints(attempt_id TEXT PRIMARY KEY,content TEXT);
    CREATE TABLE IF NOT EXISTS production_continuations(parent_id TEXT PRIMARY KEY,child_id TEXT UNIQUE);
    ''')

def validate(store,db,pid,payload,stale):
    frozen=payload['frozen']
    if stale(db,pid,payload):raise HTTPException(409,'生产输入已变化，不能续接旧检查点；请取消暂停后重新核对')
    if production_references.state_stale(store,db,pid,payload.get('assets',[])):raise HTTPException(409,'批准参考的采用或审核状态已变化，不能续接')
    if preferences.read(store,db,pid)['revision']!=frozen.get('preferences',{}).get('revision',0):raise HTTPException(409,'项目偏好已变化，不能续接')
    if graph_store.load(store,db,pid)[0]!=frozen['graph_revision']:raise HTTPException(409,'图谱已变化，不能续接')
    stage=payload['document_kind'] if payload['operation']=='document' else 'script' if payload['operation']=='range' or payload['operation']=='rewrite' and payload['kind']=='script' else 'package'
    if [s['hash'] for s in frozen_skills(store,db,pid,stage)]!=[s['hash'] for s in payload.get('skills',[])]:raise HTTPException(409,'已启用流程已变化，不能续接')

def request(db,aid):
    row=db.execute('SELECT content FROM production_requests WHERE attempt_id=?',(aid,)).fetchone()
    if not row:raise HTTPException(409,'历史生产缺少原请求快照，不能伪造续接')
    return json.loads(row[0])

def clean(checkpoint):
    return checkpoint.get('status')=='paused' and checkpoint.get('session_saved') is True and all(type(checkpoint.get(k)) is int and checkpoint[k]==0 for k in ('unreturned_models','unresolved_tools')) and not checkpoint.get('continued_by')
