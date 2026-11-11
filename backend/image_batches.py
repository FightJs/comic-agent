"""Authorized continuous independent-panel image jobs, reusing the single-call ledger."""
import asyncio
import hashlib
import json
from typing import Literal
from fastapi import BackgroundTasks,HTTPException,Query
from pydantic import BaseModel,ConfigDict,Field
from .image_jobs import PreviewIn,Ref,image_inputs_stale
from .store import uid,now,dump
from . import panel_image_inputs,image_dependencies,image_attempts
from .image_postprocess import ImagePostprocess
from .vision_api import SourceRange
from .image_batch_control import ImageBatchControl,DispatchStopped,initial_runtime

class BatchIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    packages:list[Ref]=Field(min_length=1,max_length=100)
    submission_id:str=Field(min_length=1,max_length=100)
    max_not_sent_retries:int=Field(default=0,strict=True,ge=0,le=4)
    inspection:Literal['none','review','review_repair']='none'
    source_ranges:list[SourceRange]=Field(default_factory=list,max_length=10)


def register_image_batches(app,store):
    images=app.state.image_jobs;workers=set();active_batches=set();lifecycle={'stopping':False}
    postprocess=ImagePostprocess(app,store)
    app.state.image_postprocess=postprocess
    with store.db() as db:
        db.execute('CREATE TABLE IF NOT EXISTS image_batches(id TEXT PRIMARY KEY,project_id TEXT,token TEXT,input_hash TEXT,status TEXT,payload TEXT,error TEXT,created TEXT,updated TEXT,UNIQUE(project_id,token))')
    control=ImageBatchControl(store);app.state.image_batch_control=control;control.reconcile()
    with store.db() as db:
        db.execute("UPDATE image_batches SET status='interrupted',error='应用重启；请核对后明确恢复，未自动继续调用' WHERE status IN ('queued','running')")
        db.execute("UPDATE image_batches SET status='preview_failed',error='预览准备中断，未授权生图；请从当前包重新预览' WHERE status='preparing'")

    def read(db,pid,bid):
        store.project(db,pid);row=db.execute('SELECT * FROM image_batches WHERE id=? AND project_id=?',(bid,pid)).fetchone()
        if not row:raise HTTPException(404,'图像批次不存在')
        value=dict(row);value['payload']=json.loads(value['payload']);return value

    def public(pid,bid):
        with store.db() as db:value=read(db,pid,bid)
        value['runtime']=control.view(value)
        value['jobs']=[images.public(pid,jid) for jid in value['payload']['job_ids']]
        return value

    async def execute(pid,bid,recovery):
        posttasks=[];ticker=None
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE');batch=read(db,pid,bid)
            if batch['status']!='queued':return
            db.execute("UPDATE image_batches SET status='running',updated=? WHERE id=?",(now(),bid))
            if not control.touch(db,pid,bid):
                control.finish(db,pid,bid);return
        active_batches.add(bid)
        async def tick():
            while True:
                await asyncio.sleep(1)
                with store.db() as db:
                    db.execute('BEGIN IMMEDIATE');control.touch(db,pid,bid)
        ticker=asyncio.create_task(tick())
        try:
            by_package={r['id']:jid for r,jid in zip(batch['payload']['packages'],batch['payload']['job_ids'])}
            ordered=batch['payload']['job_ids'] if batch['payload'].get('mode')=='style_tests' else [by_package[rid] for rid in batch['payload'].get('execution_order',by_package)]
            for jid in ordered:
                with store.db() as db:
                    control.gate(db,pid,bid)
                    job=images.job(db,pid,jid)
                if job['status']=='succeeded':
                    if job['payload'].get('postprocess'):posttasks.append(asyncio.create_task(postprocess.run(pid,jid)))
                    continue
                if job['status'] not in (('preview','waiting_dependency','received','interrupted','unknown','blocked') if recovery else ('preview',)):continue
                if not job['payload'].get('dependencies_bound',True):
                    try:images.bind_dependencies(pid,jid,bid,by_package)
                    except DispatchStopped:raise
                    except HTTPException as exc:
                        with store.db() as db:
                            stale=image_inputs_stale(store,db,pid,job['payload'])
                            db.execute("UPDATE image_jobs SET status=?,error=?,updated=? WHERE id=? AND status IN ('preview','waiting_dependency')",('blocked' if stale else 'waiting_dependency',str(exc.detail),now(),jid))
                        continue
                    with store.db() as db:job=images.job(db,pid,jid)
                if batch['payload'].get('restore_only') and app.state.image_provider.get(pid,job['call_id'])['status'] in ('prepared','not_sent'):continue
                background=BackgroundTasks()
                try:
                    images.queue(pid,jid,background,recovery=job['status']!='preview',batch_id=bid)
                    await background()
                    if images.public(pid,jid)['status']=='succeeded' and job['payload'].get('postprocess'):posttasks.append(asyncio.create_task(postprocess.run(pid,jid)))
                except DispatchStopped:raise
                except HTTPException as exc:
                    with store.db() as db:
                        db.execute("UPDATE image_jobs SET status='blocked',error=?,updated=? WHERE id=? AND status='preview'",(str(exc.detail),now(),jid))
            await asyncio.gather(*posttasks)
            with store.db() as db:
                value=read(db,pid,bid)
                states=[images.job(db,pid,jid)['status'] for jid in value['payload']['job_ids']]
                complete=all(state=='succeeded' for state in states) and all(images.job(db,pid,jid)['payload'].get('postprocess',{}).get('status','completed')=='completed' for jid in value['payload']['job_ids'])
                db.execute("UPDATE image_batches SET status=?,error=?,updated=? WHERE id=? AND status='running'",('completed' if complete else 'needs_attention','' if complete else '部分任务需核对；未自动重试、采用或审核',now(),bid))
        except DispatchStopped as exc:
            control.handle(exc)
        except BaseException as exc:
            for task in posttasks:task.cancel()
            await asyncio.gather(*posttasks,return_exceptions=True)
            with store.db() as db:db.execute("UPDATE image_batches SET status='interrupted',error='批次中断；请核对原任务后明确恢复，不自动重新生图',updated=? WHERE id=? AND status='running'",(now(),bid))
            if isinstance(exc,asyncio.CancelledError):raise
        finally:
            await asyncio.gather(*posttasks,return_exceptions=True)
            if ticker:
                ticker.cancel();await asyncio.gather(ticker,return_exceptions=True)
            try:
                with store.db() as db:
                    db.execute('BEGIN IMMEDIATE');control.finish(db,pid,bid)
            finally:active_batches.discard(bid)

    async def stop():
        lifecycle['stopping']=True
        for task in list(workers):task.cancel()
        await asyncio.gather(*workers,return_exceptions=True)
        with store.db() as db:db.execute("UPDATE image_batches SET status='interrupted',error='应用关闭，未自动继续；恢复需明确确认' WHERE status IN ('queued','running')")
        control.shutdown()
    # Stop paid dispatch before waiting for slower SDK/transport shutdown handlers.
    app.router.on_shutdown.insert(0,stop)

    @app.post('/api/projects/{pid}/image-batches')
    def preview(pid:str,body:BatchIn):
        if lifecycle['stopping']:raise HTTPException(503,'应用正在关闭，未创建预览')
        signature=hashlib.sha256(dump(body.model_dump(exclude_defaults=True)).encode()).hexdigest();requests=[];seen=set()
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE');store.project(db,pid)
            old=db.execute('SELECT id,input_hash FROM image_batches WHERE project_id=? AND token=?',(pid,body.submission_id)).fetchone()
            if old:
                if old['input_hash']!=signature:raise HTTPException(409,'批次预览标识不能更换输入')
                return public(pid,old['id'])
            records=[store.get(db,pid,ref.id,ref.version) for ref in body.packages];base_sources={};inspection_plans={}
            plans,execution_order=image_dependencies.graph(store,db,pid,records)
            for ref,package in zip(body.packages,records):
                content=package['content'];plan=plans[ref.id] if panel_image_inputs.dependencies_pending(content) else None
                try:
                    spec=PreviewIn(kind='image',title=f"第{content.get('episode')}话第{content.get('panel')}格图片",prompt=content.get('prompt',''),basis=ref,submission_id='pending',max_not_sent_retries=body.max_not_sent_retries)
                except ValueError:raise HTTPException(422,'生图包提示词或话格字段无效，未创建批次预览')
                if plan and len(image_dependencies.compiled_prompt(spec.prompt,plan))>32000:raise HTTPException(422,'附加前图连续性说明后的提示词超过32000字，请先精简生图包；未创建批次预览')
                target,refs,source=panel_image_inputs.prepare(store,db,pid,spec,{'input_refs':{}},plan)
                inherited=[store.get(db,pid,r['id'],r['version'])['source'] for r in refs+([target] if target else [])]
                base_sources[ref.id]='mock' if source=='mock' or 'mock' in inherited else 'ai'
                if body.inspection!='none':
                    total_refs=len(refs)+(len(plan['packages']) if plan else 0)
                    if total_refs>7:raise HTTPException(422,'自动视觉检查最多7张参考；请减少本批资产/前图引用，未静默丢参考')
                    context=[ref.model_dump()]
                    if content.get('script_id'):context.append({'id':content['script_id'],'version':content['script_version']})
                    inspection_plans[ref.id]={'policy':body.inspection,'basis':app.state.vision_reviews.freeze_basis(pid,context=context,source_ranges=[r.model_dump() for r in body.source_ranges])}
                identity=(content['episode'],content['panel'])
                if identity in seen:raise HTTPException(422,'同一批次不能重复话格')
                seen.add(identity);requests.append((spec,plan))
            for rid in execution_order:
                plans[rid]['source']='mock' if base_sources[rid]=='mock' or any(plans[r['id']]['source']=='mock' for r in plans[rid]['packages']) else 'ai'
            if body.source_ranges and body.inspection=='none':raise HTTPException(422,'原文范围仅用于已授权的自动检查')
            bid=uid();stamp=now();payload={'job_ids':[],'packages':[r.model_dump() for r in body.packages],'execution_order':execution_order,'count':len(requests),'inspection':body.inspection,'call_limits':{'images':len(requests)*(2 if body.inspection=='review_repair' else 1),'vision':len(requests)*(0 if body.inspection=='none' else 2 if body.inspection=='review_repair' else 1)},'authorization':'固定范围；仅按所选生成/检查/严重剧情一轮返修上限执行，不含采用或人工审核'}
            payload['retry_policy']=image_attempts.freeze_policy({'max_not_sent_retries':body.max_not_sent_retries})
            payload['call_limits']['image_network_attempts']=image_attempts.network_limit(payload['call_limits']['images'],payload['retry_policy'])
            payload['runtime']=initial_runtime()
            db.execute('INSERT INTO image_batches VALUES(?,?,?,?,?,?,?,?,?)',(bid,pid,body.submission_id,signature,'preparing',dump(payload),'',stamp,stamp))
        try:
            for index,(spec,plan) in enumerate(requests):
                with store.db() as db:
                    if read(db,pid,bid)['status']!='preparing':return public(pid,bid)
                spec.submission_id=f'batch-{bid}-{index}'
                inspection=inspection_plans.get(spec.basis.id)
                value=images.preview(pid,spec,bid,plan,inspection) if inspection else images.preview(pid,spec,bid,plan) if plan else images.preview(pid,spec,bid)
                payload['job_ids'].append(value['id'])
                with store.db() as db:
                    db.execute('BEGIN IMMEDIATE');cancelled=read(db,pid,bid)['status']!='preparing'
                    db.execute('UPDATE image_batches SET payload=?,updated=? WHERE id=?',(dump(payload),now(),bid))
                if cancelled:
                    images.cancel(pid,value['id']);return public(pid,bid)
            with store.db() as db:db.execute("UPDATE image_batches SET status='preview',updated=? WHERE id=? AND status='preparing'",(now(),bid))
        except Exception:
            with store.db() as db:db.execute("UPDATE image_batches SET status='preview_failed',error='预览准备未完成，未授权生图；请从当前包重新预览',updated=? WHERE id=? AND status='preparing'",(now(),bid))
            raise
        return public(pid,bid)

    @app.get('/api/projects/{pid}/image-batches')
    def history(pid:str,start:int=Query(0,ge=0),limit:int=Query(20,ge=1,le=50),mode:Literal['panels','style_tests']='panels'):
        with store.db() as db:
            store.project(db,pid);rows=db.execute('SELECT id,status,payload,error,created,updated FROM image_batches WHERE project_id=? ORDER BY created DESC,id DESC',(pid,)).fetchall()
        rows=[r for r in rows if json.loads(r['payload']).get('mode','panels')==mode]
        return {'items':[{**{k:r[k] for k in ('id','status','error','created','updated')},'count':json.loads(r['payload'])['count']} for r in rows[start:start+limit]],'total':len(rows),'next_start':start+limit if start+limit<len(rows) else None}

    @app.get('/api/projects/{pid}/image-batches/{bid}')
    def detail(pid:str,bid:str):return public(pid,bid)

    async def launch(pid,bid,recovery,body=None):
        if lifecycle['stopping']:raise HTTPException(503,'应用正在关闭，未派发批次')
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE');batch=read(db,pid,bid)
            if batch['payload'].get('mode')=='style_tests':
                from .style_batches import require_grant
                grant=require_grant(body)
                if grant.restore_only and not recovery:raise HTTPException(422,'只恢复原返回不能作为新批次启动授权')
                ids=batch['payload']['job_ids'];bindings=batch['payload'].get('call_bindings',{})
                if len(ids)!=3 or len(set(ids))!=3 or any(images.job(db,pid,jid)['call_id']!=bindings.get(jid) for jid in ids):raise HTTPException(409,'三套固定调用不完整或已变化，不能启动或恢复')
            if batch['status'] in ('queued','running','completed'):return public(pid,bid)
            if bid in active_batches:raise HTTPException(409,'在途任务仍在收尾；请待检查点保存后再明确恢复')
            if batch['status'] not in (('paused','interrupted','needs_attention') if recovery else ('preview',)):raise HTTPException(409,'当前批次不能启动或恢复，请核对原任务')
            if control.view(batch)['remaining_seconds']<=0:raise HTTPException(409,'本批已达7小时硬限，恢复不能重置运行预算')
            if not recovery:
                for jid in batch['payload']['job_ids']:
                    job=images.job(db,pid,jid)
                    if job['status']!='preview' or image_inputs_stale(store,db,pid,job['payload']) or postprocess.plan_stale(db,pid,job['payload']):raise HTTPException(409,'批次输入或单格状态已变化，请从当前包重新预览；尚未启动本批')
            occupied={r['id'] for r in db.execute("SELECT id FROM image_batches WHERE status IN ('queued','running','pausing')")}|active_batches
            if len(occupied)>=8:raise HTTPException(429,'进行中或在途收尾的图像批次过多，请先等待现有批次收口')
            if batch['payload'].get('mode')=='style_tests':
                batch['payload']['restore_only']=grant.restore_only
                db.execute('UPDATE image_batches SET payload=? WHERE id=?',(dump(batch['payload']),bid))
            db.execute("UPDATE image_batches SET status='queued',error='',updated=? WHERE id=?",(now(),bid))
        task=asyncio.create_task(execute(pid,bid,recovery));workers.add(task);task.add_done_callback(workers.discard)
        return public(pid,bid)

    @app.post('/api/projects/{pid}/image-batches/{bid}/start')
    async def start(pid:str,bid:str,body:dict|None=None):return await launch(pid,bid,False,body)

    @app.post('/api/projects/{pid}/image-batches/{bid}/recover')
    async def recover(pid:str,bid:str,body:dict|None=None):return await launch(pid,bid,True,body)

    @app.post('/api/projects/{pid}/image-batches/{bid}/pause')
    def pause(pid:str,bid:str):
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE');batch=read(db,pid,bid)
            if batch['status'] in ('pausing','paused'):return public(pid,bid)
            if batch['status'] not in ('queued','running'):raise HTTPException(409,'仅运行中的批次可以暂停')
            status='paused' if batch['status']=='queued' else 'pausing'
            db.execute('UPDATE image_batches SET status=?,error=?,updated=? WHERE id=?',(status,'已停止新派发；等待在途返回，不代表撤销费用',now(),bid))
            if status=='paused':control.finish(db,pid,bid)
        return public(pid,bid)

    @app.post('/api/projects/{pid}/image-batches/{bid}/cancel')
    def cancel(pid:str,bid:str):
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE');batch=read(db,pid,bid)
            if batch['status'] not in ('preparing','preview','queued','running','pausing','paused','budget_exhausted','interrupted','needs_attention','preview_failed'):raise HTTPException(409,'当前批次不能停止')
            db.execute("UPDATE image_batches SET status='cancelled',error='已停止后续派发；在途费用可能未知，原返回保留',updated=? WHERE id=?",(now(),bid))
        managed=list(batch['payload']['job_ids'])
        for jid in batch['payload']['job_ids']:
            repair=images.public(pid,jid)['payload'].get('postprocess',{}).get('repair_job_id')
            if repair:managed.append(repair)
        for jid in managed:
            value=images.public(pid,jid)
            if value['status'] in ('preview','waiting_dependency','queued','running'):
                try:images.cancel(pid,jid)
                except HTTPException as exc:
                    if exc.status_code!=409 or images.public(pid,jid)['status'] in ('preview','waiting_dependency','queued','running'):raise
        return public(pid,bid)

    from types import SimpleNamespace
    from . import style_batches
    app.state.image_batches=SimpleNamespace(public=public)
    style_batches.register(app,store,public,lifecycle)
