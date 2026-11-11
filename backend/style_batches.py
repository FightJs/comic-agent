"""Claim three prepared style jobs into the existing durable image-batch runner."""
import hashlib,json,threading
from fastapi import HTTPException
from pydantic import BaseModel,ConfigDict
from .store import uid,now,dump
from .style_tests import stale
from .image_jobs import image_inputs_stale
from .image_batch_control import initial_runtime
from .image_attempts import freeze_policy,network_limit
from .agent_image_plans import RetryPreviewIn

class Empty(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
class Grant(Empty):
    confirm:bool
    restore_only:bool=False


def require_grant(body):
    try:valid=Grant.model_validate(body)
    except ValueError:raise HTTPException(422,'请明确授权本组固定三张，confirm必须为true；不接受数量或额外参数')
    if not valid.confirm:raise HTTPException(422,'请明确授权本组固定三张，不含采用或审核')
    return valid


def matches(row,gid):
    if not row:return False
    payload=json.loads(row['payload'])
    retries=payload.get('retry_policy',{}).get('max_not_sent_retries',0)
    expected=hashlib.sha256(dump({'style_test_id':gid,'retry_policy':freeze_policy({'max_not_sent_retries':retries})}).encode()).hexdigest() if retries else gid
    return row['input_hash']==expected and payload.get('mode')=='style_tests' and payload.get('style_test_id')==gid


def register(app,store,public,lifecycle):
    lock=threading.RLock();images=app.state.image_jobs;provider=app.state.image_provider

    @app.post('/api/projects/{pid}/agent/style-tests/{gid}/batch-preview')
    def preview(pid:str,gid:str,body:RetryPreviewIn):
        policy=freeze_policy({'max_not_sent_retries':body.max_not_sent_retries})
        signature=hashlib.sha256(dump({'style_test_id':gid,'retry_policy':policy}).encode()).hexdigest() if body.max_not_sent_retries else gid
        from .agent_image_plans import get,validate
        with lock:
            if lifecycle['stopping']:raise HTTPException(503,'应用正在关闭，未创建预览')
            token='style-test-'+gid
            with store.db() as db:
                db.execute('BEGIN IMMEDIATE');store.project(db,pid)
                group=db.execute('SELECT * FROM style_test_sets WHERE id=? AND project_id=?',(gid,pid)).fetchone()
                if not group:raise HTTPException(404,'画风测试组不属于本项目')
                prior=db.execute('SELECT id,payload,input_hash FROM image_batches WHERE project_id=? AND token=?',(pid,token)).fetchone()
                if prior:
                    if not matches(prior,gid):raise HTTPException(409,'批次标识已被其他范围占用，未复用或授权；请重新提出测试组')
                    existing=public(pid,prior['id'])
                    if 'max_not_sent_retries' in body.model_fields_set and existing['payload'].get('retry_policy',{}).get('max_not_sent_retries',0)!=body.max_not_sent_retries:raise HTTPException(409,'原组三张的重试授权已固定，不能更换；请核对已有预览')
                    return existing
                test=json.loads(group['content'])
                run=db.execute('SELECT status FROM agent_runs WHERE id=? AND project_id=?',(group['run_id'],pid)).fetchone()
                if not run or run['status']!='completed' or stale(store,db,pid,test['basis']):raise HTTPException(409,'回复未完整完成或测试依据已变化，未创建整组预览')
                plans=[get(store,db,pid,plan_id) for plan_id in test['plan_ids']]
                if len(plans)!=3:raise HTTPException(409,'测试组不完整，不能补造三套授权')
                for plan in plans:
                    validate(store,db,pid,plan['plan'])
                    if plan['status']=='rejected':raise HTTPException(409,'本组已有方案被拒绝，不能授权完整三套')
                    if plan['job_id']:
                        job=images.job(db,pid,plan['job_id'])
                        if job['payload'].get('retry_policy',{}).get('max_not_sent_retries',0)!=body.max_not_sent_retries:raise HTTPException(409,'已存在单图预览的重试授权不同，不能扩大整组授权')
                        if job['status']!='preview' or job['payload'].get('image_batch_id') or provider.get(pid,job['call_id'])['status']!='prepared':raise HTTPException(409,'本组已有任务提交或不再可认领，请核对原单图调用')
                bid=uid();stamp=now();payload={'mode':'style_tests','style_test_id':gid,'packages':[],'job_ids':[],'count':3,'inspection':'none','retry_policy':policy,'call_limits':{'images':3,'vision':0,'image_network_attempts':network_limit(3,policy)},'authorization':'固定同组三套，每套一张；仅按明确未发送重试次数执行，不含采用或审核','runtime':initial_runtime()}
                db.execute('INSERT INTO image_batches VALUES(?,?,?,?,?,?,?,?,?)',(bid,pid,token,signature,'preparing',dump(payload),'',stamp,stamp))
            try:
                for plan in plans:
                    job=app.state.agent_image_plans.preview(pid,plan['id'],body)
                    payload['job_ids'].append(job['id'])
                with store.db() as db:
                    db.execute('BEGIN IMMEDIATE')
                    state=db.execute('SELECT status FROM image_batches WHERE id=? AND project_id=?',(bid,pid)).fetchone()
                    if not state or state['status']!='preparing':raise HTTPException(409,'整组预览已停止，不认领任务')
                    fixed=[]
                    for plan,jid in zip(plans,payload['job_ids']):
                        job=images.job(db,pid,jid);call=provider.get(pid,job['call_id']);p=job['payload']
                        if job['status']!='preview' or call['status']!='prepared' or p.get('image_batch_id') or image_inputs_stale(store,db,pid,p) or p.get('agent_image_plan',{}).get('id')!=plan['id'] or p.get('style_test',{}).get('id')!=gid:raise HTTPException(409,'预览期间单图任务或测试依据变化，未授权生图')
                        fixed.append((job,call))
                    if len({j['id'] for j,_ in fixed})!=3 or len({c['id'] for _,c in fixed})!=3:raise HTTPException(409,'测试组任务或调用编号重复，不能授权')
                    if any(c['manifest']['provider']!=provider.profile() or c['manifest']['parameters']!=fixed[0][1]['manifest']['parameters'] for _,c in fixed):raise HTTPException(409,'三套图像配置不一致，请重新核对预览')
                    payload['call_bindings']={j['id']:c['id'] for j,c in fixed}
                    for job,_ in fixed:
                        p=job['payload'];p['image_batch_id']=bid
                        db.execute('UPDATE image_jobs SET payload=?,updated=? WHERE id=?',(dump(p),now(),job['id']))
                    db.execute("UPDATE image_batches SET status='preview',payload=?,updated=? WHERE id=?",(dump(payload),now(),bid))
            except Exception:
                with store.db() as db:db.execute("UPDATE image_batches SET status='preview_failed',payload=?,error='整组预览未完成，未授权生图；请核对已准备的单图，不自动重试',updated=? WHERE id=? AND status='preparing'",(dump(payload),now(),bid))
                raise
            return public(pid,bid)
