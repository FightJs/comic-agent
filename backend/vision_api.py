"""Explicit, single-call authorization for pixel review; no automatic approval."""
import json
from fastapi import BackgroundTasks,HTTPException
from pydantic import BaseModel,Field,ConfigDict,StrictBool,StrictInt
from .store import now

class Ref(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id:str=Field(min_length=1,max_length=100)
    version:StrictInt=Field(ge=1)
class SourceRange(BaseModel):
    model_config=ConfigDict(extra='forbid')
    document_id:str=Field(min_length=1,max_length=100)
    parse_version:StrictInt=Field(ge=1)
    start:StrictInt=Field(ge=0)
    end:StrictInt=Field(ge=1)
class Preview(BaseModel):
    model_config=ConfigDict(extra='forbid')
    target:Ref
    references:list[Ref]=Field(default_factory=list,max_length=7)
    context:list[Ref]=Field(default_factory=list,max_length=10)
    source_ranges:list[SourceRange]=Field(default_factory=list,max_length=10)
    submission_id:str=Field(min_length=1,max_length=100)
class Resolve(BaseModel):
    model_config=ConfigDict(extra='forbid')
    confirmed:StrictBool
    note:str=Field(min_length=1,max_length=2000)


def register_vision_api(app,store):
    service=app.state.vision_reviews
    @app.post('/api/projects/{pid}/vision-reviews')
    def preview(pid:str,body:Preview):
        return service.prepare(pid,body.target.model_dump(),references=[r.model_dump() for r in body.references],context=[r.model_dump() for r in body.context],source_ranges=[r.model_dump() for r in body.source_ranges],operation_key=body.submission_id)

    @app.get('/api/projects/{pid}/vision-reviews')
    def history(pid:str,target_id:str):
        with store.db() as db:
            store.project(db,pid);result=[]
            for row in db.execute('SELECT id,status,manifest,created FROM vision_reviews WHERE project_id=? ORDER BY created DESC',(pid,)):
                manifest=json.loads(row['manifest']);target=manifest['images'][0]
                if target['id']==target_id:result.append({'id':row['id'],'status':row['status'],'created':row['created'],'target_version':target['version']})
            return result

    @app.get('/api/projects/{pid}/vision-reviews/{rid}')
    def read(pid:str,rid:str):return service.get(pid,rid)

    async def run(pid,rid):
        try:await service.execute(pid,rid)
        except Exception as exc:
            message=str(exc.detail) if isinstance(exc,HTTPException) else '视觉检查执行中断；请查看原返回或核对结果，不自动重发'
            with store.db() as db:db.execute("UPDATE vision_reviews SET status='blocked',error=?,updated=? WHERE id=? AND project_id=? AND status='queued'",(message,now(),rid,pid))

    def queue(pid,rid,background,recovery=False):
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE');value=service._get(db,pid,rid)
            if value['manifest'].get('image_batch_id'):raise HTTPException(409,'此检查由图像批次管理，请从原批次启动或恢复')
            if value['status'] in ('queued','running','completed'):return value
            if value['status'] not in (('interrupted',) if recovery else ('prepared',)):raise HTTPException(409,'此状态不能提交视觉调用；未知请求不自动重发')
            for other in db.execute("SELECT id,status,raw,error,manifest FROM vision_reviews WHERE project_id=? AND id!=?",(pid,rid)):
                if json.loads(other['manifest'])['images'][0]['id']!=value['manifest']['images'][0]['id']:continue
                if other['status'] in ('queued','running','unknown') or (other['status']=='cancelled' and other['raw'] is None and other['error'].startswith('在途')):raise HTTPException(409,'同一图片仍有未决视觉调用，请先查看或记录核对结论')
            if service.profile(service.config_get())!=value['manifest']['provider'] or service.stale(db,pid,value['manifest']):raise HTTPException(409,'视觉输入或配置已变化；请关闭后从当前图片重新预览')
            db.execute("UPDATE vision_reviews SET status='queued',error='',updated=? WHERE id=?",(now(),rid))
        background.add_task(run,pid,rid)
        return service.get(pid,rid)

    @app.post('/api/projects/{pid}/vision-reviews/{rid}/start')
    def start(pid:str,rid:str,background:BackgroundTasks):return queue(pid,rid,background)
    @app.post('/api/projects/{pid}/vision-reviews/{rid}/recover')
    def recover(pid:str,rid:str,background:BackgroundTasks):
        if service.get(pid,rid)['raw'] is not None:return service._finalize(pid,rid)
        return queue(pid,rid,background,True)
    @app.post('/api/projects/{pid}/vision-reviews/{rid}/cancel')
    async def cancel(pid:str,rid:str):return await service.cancel(pid,rid)
    @app.post('/api/projects/{pid}/vision-reviews/{rid}/resolve')
    def resolve(pid:str,rid:str,body:Resolve):
        if not body.confirmed or not body.note.strip():raise HTTPException(422,'请明确确认并填写核对依据')
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE');value=service._get(db,pid,rid)
            if value['raw'] is not None or value['status'] not in ('unknown','cancelled'):raise HTTPException(409,'当前状态不需要人工结束未决调用')
            db.execute("UPDATE vision_reviews SET status='resolved',error=?,updated=? WHERE id=?",('人工记录（未验证供应商完成或费用）：'+body.note.strip(),now(),rid))
        return service.get(pid,rid)
