"""Durable effective-time budget and drain-before-pause for authorized image batches.
A short prepaid lease survives crashes; clean boundaries settle actual monotonic time.
"""
import json
import time
from fastapi import HTTPException
from .store import dump,now,uid

TARGET=4*3600
HARD=7*3600
LEASE=10.


class DispatchStopped(HTTPException):
    def __init__(self,pid,bid,reason):
        self.pid,self.bid,self.reason=pid,bid,reason
        super().__init__(409,'本批有效运行已达7小时，停止新派发；在途返回仍保留' if reason=='budget' else '本批已暂停或停止新派发；原请求与返回保留')


def initial_runtime():
    return {'charged_seconds':0.,'target_seconds':TARGET,'hard_limit_seconds':HARD,'lease_id':None,'reserved_seconds':0.,'lease_wall_started':None,'uncertain_seconds':0.,'checkpoint':None}


class ImageBatchControl:
    def __init__(self,store):
        self.store=store;self.now=time.monotonic;self.wall=time.time;self.leases={};self.prior={}

    def read(self,db,pid,bid):
        self.store.project(db,pid);row=db.execute('SELECT * FROM image_batches WHERE id=? AND project_id=?',(bid,pid)).fetchone()
        if not row:raise HTTPException(404,'图像批次不存在')
        value=dict(row);value['payload']=json.loads(value['payload']);return value

    def active_lease(self,batch):
        stamp=batch['payload'].get('runtime',{}).get('lease_id')
        return next((value for value in (self.leases.get(batch['id']),self.prior.get(batch['id'])) if value and value[0]==stamp),None)

    def runtime(self,batch):
        if 'runtime' not in batch['payload']:batch['payload']['runtime']={**initial_runtime(),'historical_time_unknown':True}
        return batch['payload']['runtime']

    def elapsed(self,batch):
        runtime=batch['payload'].get('runtime',initial_runtime());spent=runtime['charged_seconds'];lease=self.active_lease(batch)
        if lease:spent=spent-lease[2]+max(0,self.now()-lease[1])
        return max(0,spent)

    def view(self,batch):
        r=batch['payload'].get('runtime',initial_runtime());used=self.elapsed(batch)
        return {'effective_seconds':round(used,3),'confirmed_seconds':round(max(0,used-r['uncertain_seconds']),3),'remaining_seconds':round(max(0,r['hard_limit_seconds']-used),3),'target_seconds':r['target_seconds'],'hard_limit_seconds':r['hard_limit_seconds'],'target_reached':used>=r['target_seconds'],'uncertain_seconds':r['uncertain_seconds'],'historical_time_unknown':r.get('historical_time_unknown','runtime' not in batch['payload']),'checkpoint':r['checkpoint']}

    def checkpoint(self,db,batch,reason):
        states=[]
        for jid in batch['payload']['job_ids']:
            row=db.execute('SELECT id,status,call_id,output_id,payload FROM image_jobs WHERE id=? AND project_id=?',(jid,batch['project_id'])).fetchone()
            if not row:continue
            p=json.loads(row['payload']);post=p.get('postprocess',{})
            states.append({**{k:row[k] for k in ('id','status','call_id','output_id')},'postprocess_status':post.get('status'),'initial_review_id':post.get('initial_review_id'),'repair_job_id':post.get('repair_job_id'),'final_review_id':post.get('final_review_id')})
        return {'reason':reason,'at':now(),'jobs':states}

    def save(self,db,batch):
        db.execute('UPDATE image_batches SET status=?,payload=?,error=?,updated=? WHERE id=? AND project_id=?',(batch['status'],dump(batch['payload']),batch['error'],now(),batch['id'],batch['project_id']))

    def touch(self,db,pid,bid):
        batch=self.read(db,pid,bid)
        if batch['status'] not in ('running','pausing','budget_exhausted'):return False
        r=self.runtime(batch);spent=self.elapsed(batch)
        if r.get('lease_id') and not self.active_lease(batch):
            self.lost_checkpoint(db,batch);return False
        previous=self.active_lease(batch)
        duration=min(LEASE,max(0,r['hard_limit_seconds']-spent));stamp=uid()
        r.update(charged_seconds=spent+duration,reserved_seconds=duration,lease_id=stamp,lease_wall_started=self.wall())
        if spent>=r['hard_limit_seconds']:
            if batch['status']!='budget_exhausted':r['checkpoint']=self.checkpoint(db,batch,'budget_exhausted')
            batch.update(status='budget_exhausted',error='已达7小时有效运行上限，不能通过恢复重置；在途返回仍保留')
        self.save(db,batch)
        if previous:self.prior[bid]=previous
        self.leases[bid]=(stamp,self.now(),duration)
        return batch['status']=='running'

    def gate(self,db,pid,bid):
        batch=self.read(db,pid,bid)
        if batch['status']!='running':raise DispatchStopped(pid,bid,'budget' if batch['status']=='budget_exhausted' else 'paused')
        if self.elapsed(batch)>=batch['payload'].get('runtime',initial_runtime())['hard_limit_seconds']:raise DispatchStopped(pid,bid,'budget')
        lease=self.active_lease(batch)
        if not lease or self.now()-lease[1]>lease[2]:raise DispatchStopped(pid,bid,'checkpoint')

    def lost_checkpoint(self,db,batch):
        r=self.runtime(batch);observed=self.active_lease(batch)
        if observed:r['charged_seconds']=self.elapsed(batch)
        else:r['uncertain_seconds']+=r['reserved_seconds']
        r.update(lease_id=None,reserved_seconds=0.,lease_wall_started=None)
        batch.update(status='interrupted',error='有效计时检查点失联；未观测尾段保守计入，请明确恢复原批次')
        if r['charged_seconds']>=r['hard_limit_seconds']:batch.update(status='budget_exhausted',error='有效运行预算已耗尽，不能通过恢复清零')
        r['checkpoint']=self.checkpoint(db,batch,'clock_checkpoint_lost');self.save(db,batch)

    def handle(self,exc):
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if exc.reason=='budget':self.touch(db,exc.pid,exc.bid)
            elif exc.reason=='checkpoint':
                batch=self.read(db,exc.pid,exc.bid)
                if batch['status']=='running':self.lost_checkpoint(db,batch)

    def finish(self,db,pid,bid):
        batch=self.read(db,pid,bid);r=self.runtime(batch);spent=self.elapsed(batch)
        r.update(charged_seconds=spent,reserved_seconds=0.,lease_id=None,lease_wall_started=None)
        if batch['status']=='pausing':batch.update(status='paused',error='已暂停新派发；在途返回已处理，继续需明确恢复原授权')
        r['checkpoint']=self.checkpoint(db,batch,batch['status']);self.save(db,batch);self.leases.pop(bid,None);self.prior.pop(bid,None)

    def reconcile(self):
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            for row in db.execute('SELECT * FROM image_batches').fetchall():
                batch=dict(row);batch['payload']=json.loads(batch['payload']);r=batch['payload'].get('runtime')
                if not r or not r.get('lease_id'):continue
                # Exit time is unknowable after a crash: charge a marked upper bound, never
                # call it measured work or silently grant a fresh budget on restart.
                last=r.get('lease_wall_started');gap=self.wall()-last if last is not None else -1
                ceiling=max(r['reserved_seconds'],gap) if gap>=0 else r['hard_limit_seconds']
                confirmed=max(0,r['charged_seconds']-r['reserved_seconds'])
                uncertain=min(ceiling,max(0,r['hard_limit_seconds']-confirmed))
                r['charged_seconds']=confirmed+uncertain;r['uncertain_seconds']+=uncertain
                r.update(lease_id=None,reserved_seconds=0.,lease_wall_started=None)
                if batch['status']=='pausing':batch.update(status='paused',error='重启前暂停尚有未决调用；请核对后明确恢复')
                elif batch['status'] in ('running','queued'):batch.update(status='interrupted',error='异常退出后未自动派发；未观测的计时尾段保守计入，请核对后恢复')
                if r['charged_seconds']>=r['hard_limit_seconds'] and batch['status'] not in ('completed','cancelled'):batch.update(status='budget_exhausted',error='已达有效运行硬限，恢复不能重置')
                r['checkpoint']=self.checkpoint(db,batch,'unclean_restart');self.save(db,batch)

    def shutdown(self):
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            for bid in list(self.leases):
                row=db.execute('SELECT project_id FROM image_batches WHERE id=?',(bid,)).fetchone()
                if row:self.finish(db,row['project_id'],bid)
