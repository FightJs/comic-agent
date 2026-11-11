"""AI may propose image input; only a human may create a preview and authorize its call."""
import json,threading
from typing import Literal
from fastapi import HTTPException
from pydantic import BaseModel,ConfigDict,Field
from .store import uid,now,dump,is_primary
from .image_jobs import PreviewIn

class RetryPreviewIn(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    max_not_sent_retries:int=Field(default=0,ge=0,le=4)

class PlanIn(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    title:str=Field(min_length=1,max_length=200)
    prompt:str=Field(min_length=1,max_length=32000)
    category:Literal['人物','场景','道具']='人物'
    target_id:str|None=Field(default=None,min_length=1,max_length=100)
    references:list[str]=Field(default_factory=list,max_length=16)


def schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS agent_image_plans(id TEXT PRIMARY KEY,project_id TEXT,run_id TEXT,title TEXT,status TEXT,source TEXT,content TEXT,job_id TEXT,created TEXT)')


def reference(store,db,pid,frozen,rid,approved=True):
    info=frozen.get('records',{}).get(rid)
    if not info or info['kind'] not in ('style','asset'):raise HTTPException(403,'生图参考不在本次项目的固定资料中')
    current=store.get(db,pid,rid)
    if current['version']!=info['version'] or not is_primary(current):raise HTTPException(409,'目标或参考已变化，不能自动使用新版本')
    if approved and (current['review']!='approved' or not current['content'].get('url')):raise HTTPException(409,'附加参考须为已采用、审核通过的实际图片')
    return {k:current[k] for k in ('id','version','adopted','review','kind','title','source')}


def history_mock(store,db,pid,session_id):
    for table in ('agent_image_plans','agent_proposals','style_test_sets'):
        if db.execute(f"SELECT 1 FROM {table} p JOIN agent_runs r ON r.id=p.run_id WHERE r.project_id=? AND r.session_id=? AND p.source='mock' LIMIT 1",(pid,session_id)).fetchone():return True
    for row in db.execute('SELECT t.result FROM agent_tool_calls t JOIN agent_runs r ON r.id=t.run_id WHERE r.project_id=? AND r.session_id=?',(pid,session_id)):
        if json.loads(row[0]).get('source')=='mock':return True
    for row in db.execute('SELECT i.manifest FROM agent_inputs i JOIN agent_runs r ON r.id=i.run_id WHERE r.project_id=? AND r.session_id=?',(pid,session_id)):
        frozen=json.loads(row[0])
        if frozen.get('inherited_mock'):return True
        for ref in frozen.get('write_refs',[]):
            try:
                if store.get(db,pid,ref['id'],ref['version'])['source']=='mock':return True
            except HTTPException:
                return True  # Unrecoverable historical provenance cannot become formal input.
    return False


def mark_mock(db,run_id,frozen):
    frozen['inherited_mock']=True
    db.execute('UPDATE agent_inputs SET manifest=? WHERE run_id=?',(dump(frozen),run_id))
    db.execute("UPDATE agent_image_plans SET source='mock' WHERE run_id=?",(run_id,))
    db.execute("UPDATE agent_proposals SET source='mock' WHERE run_id=?",(run_id,))
    db.execute("UPDATE style_test_sets SET source='mock' WHERE run_id=?",(run_id,))


def propose(store,db,pid,run_id,frozen,value):
    if frozen.get('stage') not in ('style','asset') or 'propose_image' not in frozen.get('allowed_tools',[]):raise HTTPException(403,'本次运行未开放画风/资产生图方案工具，旧检查点不自动扩权')
    try:body=PlanIn.model_validate(value)
    except ValueError:raise HTTPException(422,'生图方案只接受名称、提示词、分类、附加目标和固定参考，不接受模型配置或密钥')
    if not body.title.strip() or not body.prompt.strip() or len(set(body.references))!=len(body.references):raise HTTPException(422,'名称/提示词不能为空，参考不能重复')
    run=db.execute('SELECT status,session_id FROM agent_runs WHERE id=? AND project_id=?',(run_id,pid)).fetchone()
    if not run or run['status']!='running':raise HTTPException(409,'当前运行不能提出生图方案')
    target=None
    if body.target_id:
        writable={r['id']:r['version'] for r in frozen.get('write_refs',[])}
        if body.target_id not in writable:raise HTTPException(403,'重生成目标须为本次明确附加的固定版本')
        target=reference(store,db,pid,frozen,body.target_id,False)
        if target['kind']!=frozen['stage'] or target['version']!=writable[body.target_id]:raise HTTPException(403,'目标不属于当前阶段或附加版本')
    refs=[reference(store,db,pid,frozen,rid) for rid in body.references]
    selection=frozen.get('image_style_selection')
    if frozen['stage']=='asset':
        current=db.execute("SELECT record_id,version FROM selections WHERE project_id=? AND kind='style'",(pid,)).fetchone()
        if not selection or (dict(current) if current else None)!=selection:raise HTTPException(409,'请先确认当前画风；选择变化后须重新讨论')
        style=reference(store,db,pid,frozen,selection['record_id'])
        if style['kind']!='style' or style['version']!=selection['version']:raise HTTPException(409,'确认画风版本已变化')
        refs=list({r['id']:r for r in [*refs,style]}.values())
    ids={r['id'] for r in refs}
    if target and store.get(db,pid,target['id'],target['version'])['content'].get('url'):ids.add(target['id'])
    if len(ids)>16:raise HTTPException(422,'连同底图与画风最多16份参考，请缩小范围')
    source='mock' if frozen.get('inherited_mock') or history_mock(store,db,pid,run['session_id']) or any(r['source']=='mock' for r in [*refs,*([target] if target else [])]) else 'ai'
    if any(store.get(db,pid,r['id'],r['version'])['source']=='mock' for r in frozen.get('write_refs',[])):source='mock'
    if any(json.loads(r['result']).get('source')=='mock' for r in db.execute('SELECT result FROM agent_tool_calls WHERE run_id=?',(run_id,))):source='mock'
    plan={'kind':frozen['stage'],'title':body.title,'prompt':body.prompt,'category':body.category,'target':target,'references':refs,'style_selection':selection if frozen['stage']=='asset' else None}
    plan_id=uid();db.execute('INSERT INTO agent_image_plans VALUES(?,?,?,?,?,?,?,?,?)',(plan_id,pid,run_id,body.title,'pending',source,dump(plan),None,now()))
    return {'id':plan_id,'status':'pending','source':source,'message':'生图方案已保存；未修改原图、未创建图像调用。请用户核对后预览，再明确授权生成。'}


def get(store,db,pid,plan_id):
    store.project(db,pid)
    row=db.execute('SELECT * FROM agent_image_plans WHERE id=? AND project_id=?',(plan_id,pid)).fetchone()
    if not row:raise HTTPException(404,'生图方案不属于当前项目')
    value=dict(row);value['plan']=json.loads(value.pop('content'))
    return value


def validate(store,db,pid,plan):
    if plan.get('style_test'):
        from .style_tests import stale
        if stale(store,db,pid,plan['style_test']['basis']):raise HTTPException(409,'画风测试依据已变化，原方案保留，请重新讨论')
    for ref in [*plan['references'],*([plan['target']] if plan['target'] else [])]:
        current=store.get(db,pid,ref['id'])
        if current['version']!=ref['version'] or current['adopted']!=ref['adopted'] or current['review']!=ref['review'] or not is_primary(current):raise HTTPException(409,'方案目标或参考已变化，请重新讨论；旧方案保留')
    for ref in plan['references']:
        if store.get(db,pid,ref['id'],ref['version'])['review']!=ref['review']:raise HTTPException(409,'参考审核状态已变化，未创建预览')
    if plan['kind']=='asset':
        current=db.execute("SELECT record_id,version FROM selections WHERE project_id=? AND kind='style'",(pid,)).fetchone()
        if (dict(current) if current else None)!=plan['style_selection']:raise HTTPException(409,'确认画风已变化，请重新讨论')


def register(app,store):
    lock=threading.RLock()
    @app.get('/api/projects/{pid}/agent/image-plans/{plan_id}')
    def read(pid:str,plan_id:str):
        with store.db() as db:return get(store,db,pid,plan_id)
    @app.post('/api/projects/{pid}/agent/image-plans/{plan_id}/preview')
    def preview(pid:str,plan_id:str,body:RetryPreviewIn|None=None):
        requested=body
        retries=body.max_not_sent_retries if body else 0
        with lock:
            with store.db() as db:
                value=get(store,db,pid,plan_id)
                run=db.execute('SELECT status FROM agent_runs WHERE id=? AND project_id=?',(value['run_id'],pid)).fetchone()
                if not run or run['status']!='completed':raise HTTPException(409,'回复须完整完成后才能核对预览；中断/额度暂停不能放行')
                if value['status']=='rejected':raise HTTPException(409,'此方案已拒绝')
                if value['job_id']:
                    existing=app.state.image_jobs.public(pid,value['job_id'])
                    if requested and 'max_not_sent_retries' in requested.model_fields_set and existing['payload'].get('retry_policy',{}).get('max_not_sent_retries',0)!=retries:raise HTTPException(409,'已有预览的重试授权不可更换，请核对原任务；新策略需重新提出方案')
                    return existing
                plan=value['plan'];validate(store,db,pid,plan)
            body=PreviewIn(kind=plan['kind'],title=plan['title'],prompt=plan['prompt'],category=plan['category'],target={k:plan['target'][k] for k in ('id','version')} if plan['target'] else None,references=[{k:r[k] for k in ('id','version')} for r in plan['references']],submission_id='ai-plan-'+plan_id+('-r'+str(retries) if retries else ''),max_not_sent_retries=retries)
            job=app.state.image_jobs.preview(pid,body,agent_plan={'id':plan_id,'run_id':value['run_id'],'source':value['source'],'references':plan['references'],'target':plan['target'],'style_selection':plan['style_selection'],**({'style_test':plan['style_test']} if plan.get('style_test') else {})})
            with store.db() as db:db.execute("UPDATE agent_image_plans SET status='previewed',job_id=? WHERE id=?",(job['id'],plan_id))
            return job
    @app.post('/api/projects/{pid}/agent/image-plans/{plan_id}/reject')
    def reject(pid:str,plan_id:str):
        with lock:
            with store.db() as db:
                value=get(store,db,pid,plan_id)
                if value['job_id']:raise HTTPException(409,'已有图像预览，请到预览中丢弃或核对原任务')
                db.execute("UPDATE agent_image_plans SET status='rejected' WHERE id=?",(plan_id,))
                return get(store,db,pid,plan_id)

    from types import SimpleNamespace
    app.state.agent_image_plans=SimpleNamespace(preview=preview)
