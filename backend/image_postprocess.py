"""Bounded generation -> real-pixel inspection -> one story repair -> reinspection.
All calls stay in the existing image/vision ledgers. No approval or adoption here.
"""
import asyncio
from fastapi import BackgroundTasks,HTTPException
from .image_jobs import image_inputs_stale
from .store import dump,now
from .vision_grounding import sources_stale
from .store import is_primary
from .image_batch_control import DispatchStopped


class ImagePostprocess:
    def __init__(self,app,store):self.app,self.store=app,store

    def read(self,pid,jid):
        with self.store.db() as db:return self.app.state.image_jobs.job(db,pid,jid)

    def plan_stale(self,db,pid,payload):
        post=payload.get('postprocess')
        if not post:return False
        basis=post['plan']['basis'];vision=self.app.state.vision_reviews
        try:
            if vision.profile(vision.config_get())!=basis['provider'] or sources_stale(self.store,db,pid,basis['sources']):return True
            for fixed in basis['context']:
                head=self.store.get(db,pid,fixed['id'])
                if head['version']!=fixed['version'] or not is_primary(head):return True
        except HTTPException:return True
        return False

    def update(self,pid,jid,**changes):
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE');job=self.app.state.image_jobs.job(db,pid,jid);p=job['payload'];p['postprocess'].update(changes)
            owner=db.execute('SELECT status FROM image_batches WHERE id=? AND project_id=?',(p['image_batch_id'],pid)).fetchone()
            if owner and owner['status']=='cancelled':p['postprocess']['status']='cancelled'
            db.execute('UPDATE image_jobs SET payload=?,updated=? WHERE id=?',(dump(p),now(),jid))

    def check(self,db,pid,jid):
        job=self.app.state.image_jobs.job(db,pid,jid);p=job['payload']
        self.app.state.image_batch_control.gate(db,pid,p['image_batch_id'])
        if job['status']!='succeeded' or image_inputs_stale(self.store,db,pid,p) or self.plan_stale(db,pid,p):raise HTTPException(409,'生成或检查输入已变化，原图和报告保留；未派发后续动作')
        output=self.store.get(db,pid,job['output_id'])
        if output['version']!=p['output_versions'][output['id']]:raise HTTPException(409,'生成候选已被修改或采用，后续自动操作暂停')

    async def inspect(self,pid,jid,target_job,stage):
        root=self.read(pid,jid);p=root['payload'];post=p['postprocess'];service=self.app.state.vision_reviews
        key=stage+'_review_id';review_id=post.get(key)
        if not review_id:
            with self.store.db() as db:self.check(db,pid,jid)
            target=target_job['output_id'];version=target_job['payload']['output_versions'][target]
            review=service.prepare(pid,{'id':target,'version':version},references=p['references'],frozen_basis=post['plan']['basis'],owner_batch_id=p['image_batch_id'],operation_key='post:'+jid+':'+stage)
            review_id=review['id'];self.update(pid,jid,**{key:review_id})
        review=service.get(pid,review_id)
        if review['status']=='interrupted':
            with self.store.db() as db:
                db.execute('BEGIN IMMEDIATE');self.check(db,pid,jid)
                db.execute("UPDATE vision_reviews SET status='prepared' WHERE id=? AND project_id=? AND status='interrupted'",(review_id,pid))
        self.update(pid,jid,status='reviewing' if stage=='initial' else 'rechecking')
        def before_submit(db):
            self.check(db,pid,jid)
            target=service._get(db,pid,review_id)['manifest']['images'][0]['id']
            import json
            for row in db.execute("SELECT id,manifest FROM vision_reviews WHERE project_id=? AND id!=? AND status IN ('running','queued','unknown')",(pid,review_id)):
                if json.loads(row['manifest'])['images'][0]['id']==target:raise HTTPException(409,'同一图片已有未决视觉调用，未重复检查')
        return await service.execute(pid,review_id,before_submit=before_submit,batch_id=p['image_batch_id'])

    async def run(self,pid,jid):
        root=self.read(pid,jid);post=root['payload'].get('postprocess')
        if not post or post['status']=='completed':return
        try:
            with self.store.db() as db:self.check(db,pid,jid)
            initial=await self.inspect(pid,jid,root,'initial')
            if initial['status']!='completed':
                self.update(pid,jid,status='needs_attention',error=initial['error'] or '视觉返回未完成或无效，未自动重试或返修');return
            with self.store.db() as db:self.check(db,pid,jid)
            critical=[i for i in initial['report']['issues'] if i['severity']=='critical' and i['category']=='story']
            final=root;last=initial
            if critical and post['plan']['policy']=='review_repair':
                current=self.read(pid,jid)['payload']['postprocess'];repair_id=current.get('repair_job_id')
                if not repair_id:
                    repair=self.app.state.image_jobs.prepare_repair(pid,jid,initial['id'],root['payload']['image_batch_id'])
                    repair_id=repair['id'];self.update(pid,jid,repair_job_id=repair_id)
                repair=self.app.state.image_jobs.public(pid,repair_id)
                self.update(pid,jid,status='repairing')
                if repair['status']!='succeeded':
                    background=BackgroundTasks()
                    self.app.state.image_jobs.queue(pid,repair_id,background,recovery=repair['status']!='preview',batch_id=root['payload']['image_batch_id'])
                    await background()
                final=self.app.state.image_jobs.public(pid,repair_id)
                if final['status']!='succeeded':
                    self.update(pid,jid,status='needs_attention',error='一轮返修未完成；原图/原调用保留，不自动新增返修');return
                last=await self.inspect(pid,jid,final,'final')
                if last['status']!='completed':
                    self.update(pid,jid,status='needs_attention',error=last['error'] or '返修后检查未完成，不再自动修图');return
            with self.store.db() as db:self.check(db,pid,jid)
            self.update(pid,jid,status='completed',final_job_id=final['id'],needs_manual=bool(last['report']['issues']),error='')
        except DispatchStopped as exc:
            self.app.state.image_batch_control.handle(exc)
            self.update(pid,jid,status='paused',error=str(exc.detail))
        except asyncio.CancelledError:
            self.update(pid,jid,status='interrupted',error='后处理中断；只恢复原回执，不追加调用');raise
        except Exception as exc:
            self.update(pid,jid,status='needs_attention',error=str(exc.detail) if isinstance(exc,HTTPException) else '后处理未完成；请核对原图与报告，未自动追加调用')
