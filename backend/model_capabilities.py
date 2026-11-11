"""Reconcile existing paid-business receipts; never dispatch models or tools."""
import hashlib
import json
from typing import Literal
from urllib.parse import urlparse
from fastapi import HTTPException
from pydantic import BaseModel,ConfigDict,Field
from .store import dump,now
from .config_packages import profiles
from . import tool_receipts
from .vision_reviews import validate_report

KINDS=('text','tool','vision','generation','edit')
LABELS={'text':'文本回复','tool':'工具往返','vision':'实图检查','generation':'图片生成','edit':'底图编辑'}
PURPOSE={'text':'text','tool':'text','vision':'vision','generation':'image','edit':'image'}

class Evidence(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    kind:Literal['text','tool','vision','generation','edit']
    receipt_id:str=Field(min_length=1,max_length=200,pattern=r'^[a-zA-Z0-9_-]+$')

class Reconcile(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    evidence:list[Evidence]=Field(min_length=1,max_length=20)


def public_profile(value,purpose):
    return {'purpose':purpose,'url':(value.get('url') or '').rstrip('/'),'model':value.get('model') or '', 'api':value.get('api') or ('openai-images' if purpose=='image' else 'openai-completions')}


def profile_hash(value,purpose):
    return hashlib.sha256(json.dumps(public_profile(value,purpose),sort_keys=True).encode()).hexdigest()


def origin(profile,manifest=None):
    # Input provenance does not identify the supplier; local endpoints may be real.
    if (manifest or {}).get('source')=='mock':return 'mock'
    return 'unknown'


def table(db,name):return db.execute('SELECT 1 FROM sqlite_master WHERE type=? AND name=?',('table',name)).fetchone() is not None


def load(db,pid,kind,rid):
    if kind in ('text','tool'):
        if not table(db,'agent_runs') or not table(db,'agent_requests'):raise HTTPException(404,'本项目回执不存在')
        row=db.execute('SELECT r.*,q.config FROM agent_runs r JOIN agent_requests q ON q.run_id=r.id WHERE r.id=? AND r.project_id=?',(rid,pid)).fetchone()
        if not row:raise HTTPException(404,'本项目回执不存在')
        r=dict(row);r['profile']=json.loads(r['config']);r['receipt_type']='agent_run';r['manifest']={}
    else:
        name='vision_reviews' if kind=='vision' else 'image_calls'
        if not table(db,name):raise HTTPException(404,'本项目回执不存在')
        row=db.execute('SELECT * FROM '+name+' WHERE id=? AND project_id=?',(rid,pid)).fetchone()
        if not row:raise HTTPException(404,'本项目回执不存在')
        r=dict(row);r['manifest']=json.loads(r['manifest']);r['profile']=r['manifest'].get('provider',{});r['receipt_type']='vision_review' if kind=='vision' else 'image_call'
    return r


def inspect_receipt(r,kind):
    if r['status']!='completed':raise HTTPException(409,'回执未完整完成；未重新调用模型')
    profile=r['profile'];parsed=urlparse(profile.get('url') or '')
    if not profile.get('model') or parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:raise HTTPException(409,'回执缺少可核对的明确模型配置')
    limits={}
    if kind in ('text','tool'):
        if not isinstance(r.get('reply'),str) or not r['reply'].strip():raise HTTPException(409,'缺少完整文本返回')
    elif kind=='vision':
        manifest=r['manifest'];images=manifest.get('images',[])
        if not images or not all(isinstance(i,dict) and i.get('file_id') and isinstance(i.get('sha256'),str) and len(i['sha256'])==64 for i in images):raise HTTPException(409,'缺少固定实图输入证据')
        try:
            report=validate_report(r['raw'],len(images),manifest.get('sources',[]))
            if report!=json.loads(r['report']):raise ValueError('report_mismatch')
        except (ValueError,TypeError,KeyError):raise HTTPException(409,'视觉原始返回与结构报告无法核对')
        limits={'image_count':len(images),'semantic_quality_verified':False}
    else:
        manifest=r['manifest'];expected='generate' if kind=='generation' else 'edit'
        if manifest.get('operation')!=expected:raise HTTPException(409,'回执操作与能力类别不匹配')
        try:result=json.loads(r['result'])
        except (ValueError,TypeError):raise HTTPException(409,'缺少完整图像返回')
        if not isinstance(result,dict) or not isinstance(result.get('sha256'),str) or len(result['sha256'])!=64 or result.get('format')!='PNG' or not result.get('url') or any(type(result.get(k)) is not int or result[k]<=0 for k in ('width','height')):raise HTTPException(409,'缺少已登记图片证据')
        refs=manifest.get('references',[])
        if expected=='edit' and (not refs or not all(isinstance(i,dict) and i.get('file_id') and i.get('sha256') for i in refs)):raise HTTPException(409,'缺少底图输入证据')
        if expected=='generate' and (refs or manifest.get('mask')):raise HTTPException(409,'无参考生成回执输入冲突')
        limits={'reference_count':len(refs),'mask_observed':manifest.get('mask') is not None}
    return limits


def candidates(db,pid):
    output=[]
    for kind in KINDS:
        name='agent_runs' if kind in ('text','tool') else 'vision_reviews' if kind=='vision' else 'image_calls'
        if not table(db,name):continue
        # Bounded query per kind; filter image operation in SQL, never scan all project data.
        if kind in ('generation','edit'):
            rows=db.execute('SELECT id FROM image_calls WHERE project_id=? AND status=? AND json_extract(manifest,\'$.operation\')=? ORDER BY updated DESC,id DESC LIMIT 20',(pid,'completed','generate' if kind=='generation' else 'edit')).fetchall()
        else:rows=db.execute('SELECT id FROM '+name+' WHERE project_id=? AND status=? ORDER BY updated DESC,id DESC LIMIT 20',(pid,'completed')).fetchall()
        for row in rows:
            try:r=load(db,pid,kind,row['id'])
            except (HTTPException,ValueError,TypeError):continue
            output.append({'kind':kind,'receipt_id':r['id'],'label':LABELS[kind],'source':origin(r['profile'],r['manifest']),'observed_at':r['updated']})
    return output


def state(store,db,pid):
    store.project(db,pid);current=profiles(db);items=[]
    for kind in KINDS:
        purpose=PURPOSE[kind];hashed=profile_hash(current.get(purpose,{}),purpose)
        row=db.execute('SELECT content FROM model_capability_receipts WHERE project_id=? AND kind=? ORDER BY (profile_hash=?) DESC,checked_at DESC,rowid DESC LIMIT 1',(pid,kind,hashed)).fetchone()
        value=json.loads(row['content']) if row else {'kind':kind,'status':'unverified','source':'unknown','profile_hash':hashed,'observed_at':None,'receipt':None,'limits':{},'reason_codes':['no_checked_receipt']}
        if row and value['profile_hash']!=hashed:value={**value,'status':'stale','reason_codes':['profile_changed']}
        items.append(value)
    return {'capabilities':items,'candidates':candidates(db,pid)}


def register_model_capabilities(app,store):
    with store.db() as db:db.execute('CREATE TABLE IF NOT EXISTS model_capability_receipts(project_id TEXT,kind TEXT,receipt_id TEXT,profile_hash TEXT,content TEXT,checked_at TEXT,PRIMARY KEY(project_id,kind,receipt_id,profile_hash))')

    @app.get('/api/projects/{pid}/model-capabilities')
    def get_capabilities(pid:str):
        with store.db() as db:return state(store,db,pid)

    @app.post('/api/projects/{pid}/model-capabilities/reconcile')
    async def reconcile(pid:str,body:Reconcile):
        checked=[];snapshots=[]
        for evidence in body.evidence:
            kind,rid=evidence.kind,evidence.receipt_id
            with store.db() as db:
                store.project(db,pid);r=load(db,pid,kind,rid);limits=inspect_receipt(r,kind)
                host=tool_receipts.summaries(db,pid,'discussion',rid) if kind=='tool' and table(db,'pi_tool_receipts') else []
                snapshots.append((kind,rid,r))
            reasons=[];status='verified'
            if kind=='tool':
                matched=False
                runtime=getattr(app.state,'pi_runtime',None)
                if runtime and host:
                    try:
                        response=await runtime.request('checkpoint_details',project_id=pid,session_id=r['session_id'],run_id=rid,timeout=10)
                        cp=response.get('data',{}).get('checkpoint',{})
                        if response.get('type')=='result' and cp.get('run_id')==rid and cp.get('session_id')==r['session_id']:
                            matches=tool_receipts.compare(host,cp)
                            matched=any(i['state']=='matched' and i['node_status'] in ('received','completed') for i in matches)
                    except Exception:pass
                if not matched:status='unverified';reasons=['tool_roundtrip_unproven']
            purpose=PURPOSE[kind]
            checked.append({'kind':kind,'status':status,'source':origin(r['profile'],r['manifest']),'profile_hash':profile_hash(r['profile'],purpose),'observed_at':r['updated'],'receipt':{'type':r['receipt_type'],'id':rid},'limits':limits,'reason_codes':reasons})
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE');store.project(db,pid)
            for kind,rid,snapshot in snapshots:
                if load(db,pid,kind,rid)!=snapshot:raise HTTPException(409,'核对期间原回执已变化，请重新核对；未调用模型')
            for value in checked:
                key=(pid,value['kind'],value['receipt']['id'],value['profile_hash'])
                old=db.execute('SELECT content FROM model_capability_receipts WHERE project_id=? AND kind=? AND receipt_id=? AND profile_hash=?',key).fetchone()
                if old and json.loads(old['content'])==value:continue
                db.execute('INSERT INTO model_capability_receipts VALUES(?,?,?,?,?,?) ON CONFLICT(project_id,kind,receipt_id,profile_hash) DO UPDATE SET content=excluded.content,checked_at=excluded.checked_at',(*key,dump(value),now()))
            return state(store,db,pid)
