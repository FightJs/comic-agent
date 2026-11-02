"""Production boundary: frozen inputs, explicit discussion and candidate adoption."""
import asyncio
import json
from typing import Literal
from fastapi import BackgroundTasks, HTTPException
from pydantic import BaseModel, Field
from .store import uid, now, dump
from .simulation import demo_image

class Ref(BaseModel):
    id: str
    version: int = Field(ge=1)
class Entry(BaseModel):
    episode: int = Field(ge=1,le=100000)
    title: str = Field(min_length=1,max_length=300)
    text: str = Field(min_length=1,max_length=200000)
    source_range: str = Field(default='',max_length=1000)
class IndexIn(BaseModel):
    outline_version: int = Field(ge=1)
    expected_version: int = Field(ge=0)
    entries: list[Entry] = Field(min_length=1,max_length=2000)
class ChatIn(BaseModel):
    refs: list[Ref] = Field(min_length=1,max_length=100)
    message: str = Field(min_length=1,max_length=20000)
    expected_version: int = Field(ge=0)
class SelectedReviewIn(BaseModel):
    refs: list[Ref] = Field(min_length=1,max_length=1000)
    decision: Literal['approved','changes']
    note: str = Field(default='',max_length=10000)

class JobIn(BaseModel):
    operation: Literal['range','rewrite','package','image','repair']
    refs: list[Ref] = Field(default_factory=list,max_length=300)
    instruction: str = Field(default='',max_length=20000)
    per_item: dict[str,str] = Field(default_factory=dict)
    annotation_versions: dict[str,int] = Field(default_factory=dict)
    submission_id: str = Field(min_length=1,max_length=100)
    conversation_id: str | None = None
    conversation_version: int | None = None
    outline_id: str | None = None
    outline_version: int | None = None
    index_version: int | None = None
    start: int = Field(default=1,ge=1)
    end: int = Field(default=1,ge=1)

def register_workflow(app, store):
    with store.db() as db:
        db.execute('CREATE TABLE IF NOT EXISTS workflow_submissions(project_id TEXT,token TEXT,response TEXT,PRIMARY KEY(project_id,token))')

    def all_records(db,pid,kind=None):
        return [store.get(db,pid,r['id']) for r in db.execute('SELECT id FROM records WHERE project_id=?'+(' AND kind=?' if kind else ''),(pid,kind) if kind else (pid,))]

    def find_index(db,pid,rid):
        return next((r for r in all_records(db,pid,'outline_index') if r['content']['outline_id']==rid),None)

    @app.get('/api/projects/{pid}/outline-index/{rid}')
    def index(pid:str,rid:str):
        with store.db() as db:
            r=store.get(db,pid,rid)
            if r['kind']!='outline': raise HTTPException(422,'请选择细纲')
            return find_index(db,pid,rid)

    @app.put('/api/projects/{pid}/outline-index/{rid}')
    def save_index(pid:str,rid:str,body:IndexIn):
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            r=store.get(db,pid,rid)
            if r['kind']!='outline' or r['version']!=body.outline_version: raise HTTPException(409,'细纲已改变，请重新核对段落')
            numbers=[e.episode for e in body.entries]
            if len(set(numbers))!=len(numbers): raise HTTPException(422,'话号重复，请校正映射')
            if any(not e.text.strip() or not e.title.strip() for e in body.entries): raise HTTPException(422,'话标题与细纲不能为空')
            content={'outline_id':rid,'outline_version':r['version'],'entries':[e.model_dump() for e in body.entries]}
            old=find_index(db,pid,rid)
            if (old['version'] if old else 0)!=body.expected_version: raise HTTPException(409,'话索引已更新，请重新读取')
            return store.save(db,pid,old['id'],body.expected_version,content,source=r['source']) if old else store.add(db,pid,'outline_index','细纲话索引',content,r['source'])

    def ref_key(refs): return sorted((r['id'],r['version']) for r in refs)

    @app.get('/api/projects/{pid}/conversations')
    def conversations(pid:str):
        with store.db() as db:
            store.project(db,pid)
            return all_records(db,pid,'conversation')

    @app.post('/api/projects/{pid}/conversations')
    def discuss(pid:str,body:ChatIn):
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            refs=[r.model_dump() for r in body.refs]
            for r in refs: store.get(db,pid,r['id'],r['version'])
            if not body.message.strip(): raise HTTPException(422,'请输入讨论内容')
            old=next((r for r in all_records(db,pid,'conversation') if ref_key(r['content']['refs'])==ref_key(refs)),None)
            if (old['version'] if old else 0)!=body.expected_version: raise HTTPException(409,'对话已更新，草稿保留，请刷新对话后再发送')
            messages=(old['content']['messages'] if old else [])+[
                {'id':uid(),'role':'user','text':body.message,'created':now()},
                {'id':uid(),'role':'assistant','text':'【模拟讨论】已记录你的意见：'+body.message+'\n建议先核对选中话格、底图和区域批注，再明确点击“按方案生成”。本回复仅整理输入，未分析原著或图片，也没有启动生成。','created':now(),'source':'mock'}]
            content={'refs':refs,'messages':messages,'plan':body.message}
            return store.save(db,pid,old['id'],old['version'],content,source='mock') if old else store.add(db,pid,'conversation','修改讨论',content,'mock')

    async def run(tid):
        with store.db() as db:
            t=db.execute('SELECT * FROM tasks WHERE id=?',(tid,)).fetchone()
            if not t or t['status']!='queued': return
            pid=t['project_id']; p=json.loads(t['payload'])
            db.execute("UPDATE tasks SET status='running',updated=? WHERE id=?",(now(),tid))
        await asyncio.sleep(.25)
        try:
            with store.db() as db:
                db.execute('BEGIN IMMEDIATE')
                item=p['snapshots'][0] if p['snapshots'] else None
                op=p['operation']; instruction=p['instruction']; outputs=[]
                if op=='range':
                    entry=p['entry']; episode=entry['episode']
                    # A small explicit fixture tests the flow; never presented as adaptation quality.
                    for panel in range(1,4):
                        old=next((r for r in p['existing'] if r['content'].get('panel')==panel),None)
                        content={'episode':episode,'batch':(episode-1)//10+1,'panel':panel,'episode_title':entry['title'],'source_range':entry.get('source_range',''),'outline_id':p['outline_id'],'outline_version':p['outline_version'],'characters':'示例人物','scene':'示例场景','weather':'未设定','time':'未设定','shot':'中景','camera':'平视','description':f'【模拟结构样例】第{episode}话第{panel}格。该内容不是对当前原著的真实改编。','dialogue':'示例台词','sfx':'','note':'请接入真实模型后生成正式成品。'}
                        if old: content.update(candidate_for=old['id'],input_version=old['version'])
                        outputs.append(store.add(db,pid,'script',f'第{episode}话 · 第{panel}格',content,'mock'))
                else:
                    content=item['content'].copy(); kind=item['kind']; target=item
                    if op=='rewrite':
                        field='description' if kind=='script' else 'prompt'
                        content[field]=content.get(field,'')+'\n【模拟修改意见】'+instruction
                        if kind=='package': content['prompt_mode']='override'
                    if op=='package':
                        kind='package'; target=p.get('existing_package')
                        refs=[{'id':a['id'],'version':a['version'],'purpose':a['content'].get('category','参考')} for a in p['assets']]
                        parts={'scene_prompt':content.get('scene',''),'content_prompt':content.get('description',''),'position_prompt':'【模拟】站位待确认','shot_prompt':content.get('shot','')+' / '+content.get('camera',''),'constraints':'【模拟】保持人物和场景连续性'}
                        content={k:content.get(k) for k in ('batch','episode','panel','characters','scene')}
                        content.update(parts,script_id=item['id'],script_version=item['version'],references=refs,prompt='\n\n'.join(parts.values()),prompt_mode='composed')
                    if op in ('image','repair'):
                        kind='image'; target=p['target_head'] if op=='repair' else p.get('existing_image')
                        raw=demo_image(item['content'].get('panel',1)-1)
                        content.update(url=store.file(db,pid,'模拟修改结果.png',raw,'image/png'),width=640,height=900,filename='模拟修改结果.png',issues=[],checked=False,applied_instruction=instruction)
                        if op=='image': content.update(package_id=item['id'],package_version=item['version'])
                    for k in ('candidate_for','input_version','adopted_into'): content.pop(k,None)
                    if target: content.update(candidate_for=target['id'],input_version=target['version'])
                    content['task_id']=tid
                    outputs.append(store.add(db,pid,kind,'候选 · '+item['title'],content,'mock'))
                p['output_ids']=[r['id'] for r in outputs]
                db.execute("UPDATE tasks SET status='succeeded',output_id=?,payload=?,updated=? WHERE id=?",(outputs[0]['id'],dump(p),now(),tid))
        except Exception:
            with store.db() as db: db.execute("UPDATE tasks SET status='failed',error='模拟任务失败；输入已保留，可显式重试',updated=? WHERE id=?",(now(),tid))

    @app.post('/api/projects/{pid}/production-jobs')
    def jobs(pid:str,body:JobIn,background:BackgroundTasks):
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE'); store.project(db,pid)
            prior=db.execute('SELECT response FROM workflow_submissions WHERE project_id=? AND token=?',(pid,body.submission_id)).fetchone()
            if prior: return json.loads(prior['response'])
            rows=all_records(db,pid); snapshots=[]; payloads=[]
            inflight=[json.loads(t['payload']) for t in db.execute("SELECT payload FROM tasks WHERE project_id=? AND status IN ('queued','running')",(pid,))]
            for ref in body.refs:
                current=store.get(db,pid,ref.id); r=store.get(db,pid,ref.id,ref.version)
                if body.operation!='repair' and current['version']!=ref.version: raise HTTPException(409,'输入版本已变化，请重新查看')
                if r['content'].get('candidate_for'): raise HTTPException(422,'请先采用候选结果')
                snapshots.append(r)
            if len({r['id'] for r in snapshots})!=len(snapshots): raise HTTPException(422,'选择重复')
            conversation=None
            if body.conversation_id:
                conversation=store.get(db,pid,body.conversation_id,body.conversation_version)
                if conversation['kind']!='conversation' or ref_key(conversation['content']['refs'])!=ref_key([r.model_dump() for r in body.refs]): raise HTTPException(422,'对话不属于当前选择及版本')
                if store.get(db,pid,conversation['id'])['version']!=body.conversation_version: raise HTTPException(409,'对话已有新消息，请核对方案')
            common={'workflow':True,'operation':body.operation,'instruction':body.instruction,'conversation':conversation,'group_id':body.submission_id,'source':'mock'}
            if body.operation=='range':
                outline=store.get(db,pid,body.outline_id)
                index=find_index(db,pid,body.outline_id)
                if outline['kind']!='outline' or outline['version']!=body.outline_version or not index or index['version']!=body.index_version or index['content']['outline_version']!=outline['version']: raise HTTPException(409,'请先核对并保存当前细纲话索引')
                if body.end<body.start or body.end-body.start>=100: raise HTTPException(422,'单次请选择1至100话')
                originals=[r for r in rows if r['kind']=='original']
                if not originals: raise HTTPException(422,'请先导入整部原著')
                entries={e['episode']:e for e in index['content']['entries']}
                missing=[n for n in range(body.start,body.end+1) if n not in entries]
                if missing: raise HTTPException(422,'细纲缺少话号：'+','.join(map(str,missing)))
                for n in range(body.start,body.end+1):
                    if any(t.get('operation')=='range' and t.get('episode')==n for t in inflight): raise HTTPException(409,f'第{n}话正在生成，请等待任务完成')
                    existing=[r for r in rows if r['kind']=='script' and r['content'].get('episode')==n and not r['content'].get('candidate_for') and not r['content'].get('pending_for')]
                    if existing: raise HTTPException(409,f'第{n}话已有脚本，请使用选格修改，不重复生成整话')
                    payloads.append({**common,'kind':'script','episode':n,'panel':1,'batch':(n-1)//10+1,'snapshots':[],'entry':entries[n],'outline_id':outline['id'],'outline_version':outline['version'],'outline':outline,'originals':originals,'skeletons':[r for r in rows if r['kind']=='skeleton'],'existing':[]})
            else:
                expected={'rewrite':('script','package'),'package':('script',),'image':('package',),'repair':('image',)}[body.operation]
                if not snapshots or any(r['kind'] not in expected for r in snapshots): raise HTTPException(422,'当前操作的选择类型无效')
                for r in snapshots:
                    content=r['content']; episode=content.get('episode',1); panel=content.get('panel',1)
                    if body.operation in ('package','image') and any(t.get('operation')==body.operation and t.get('episode')==episode and t.get('panel')==panel for t in inflight): raise HTTPException(409,f'第{episode}话第{panel}格正在生成，请等待任务完成')
                    annotations=None
                    if body.operation=='repair':
                        ann=db.execute('SELECT version,items FROM annotations WHERE record_id=? AND image_version=?',(r['id'],r['version'])).fetchone()
                        annotations={'version':ann['version'] if ann else 0,'items':json.loads(ann['items']) if ann else []}
                        if r['id'] not in body.annotation_versions: raise HTTPException(422,'请先读取并核对底图批注')
                        if body.annotation_versions[r['id']]!=annotations['version']: raise HTTPException(409,'区域批注已变化，请重新核对后生成')
                    def existing(kind): return next((x for x in rows if x['kind']==kind and x['content'].get('episode')==episode and x['content'].get('panel')==panel and not x['content'].get('candidate_for') and not x['content'].get('pending_for')),None)
                    assets=[]
                    if body.operation=='package': assets=[store.get(db,pid,a['id'],a['adopted']) for a in rows if a['kind']=='asset']
                    if body.operation=='image':
                        if not content.get('prompt','').strip(): raise HTTPException(422,f'第{episode}话第{panel}格缺少完整提示词')
                        for ref in content.get('references',[]): assets.append(store.get(db,pid,ref['id'],ref['version']))
                    payloads.append({**common,'kind':'repair' if body.operation=='repair' else r['kind'] if body.operation=='rewrite' else body.operation,'episode':episode,'panel':panel,'batch':content.get('batch',(episode-1)//10+1),'snapshots':[r],'target_head':store.get(db,pid,r['id']),'instruction':body.instruction+ ('\n该格补充：'+body.per_item[r['id']] if body.per_item.get(r['id']) else ''),'annotation_snapshot':annotations,'assets':assets,'context':[x for x in rows if x['kind']=='script' and x['content'].get('episode')==episode and not x['content'].get('candidate_for')],'existing_package':existing('package'),'existing_image':existing('image')})
            ids=[]
            for payload in payloads:
                tid=uid(); stamp=now(); ids.append(tid)
                db.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?)',(tid,pid,'queued',dump(payload),None,'',stamp,stamp))
            result={'ids':ids,'status':'queued','source':'mock'}
            db.execute('INSERT INTO workflow_submissions VALUES(?,?,?)',(pid,body.submission_id,dump(result)))
        for tid in ids: background.add_task(run,tid)
        return result

    @app.post('/api/projects/{pid}/production-review')
    def review_selected(pid:str,body:SelectedReviewIn):
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            snapshots=[]
            for ref in body.refs:
                r=store.get(db,pid,ref.id)
                if r['version']!=ref.version: raise HTTPException(409,'所选脚本已有新版本，本次审核未写入，请重新核对')
                if r['kind']!='script' or r['content'].get('candidate_for'): raise HTTPException(422,'请选择当前脚本，候选请先采用')
                snapshots.append(r)
            for r in snapshots:
                db.execute('INSERT INTO reviews VALUES(?,?,?,?,?,?,?)',(uid(),r['id'],r['version'],body.decision,body.note,r['source'],now()))
            return {'reviewed':len(snapshots)}

    @app.post('/api/projects/{pid}/candidates/{rid}/adopt')
    def adopt_candidate(pid:str,rid:str):
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            r=store.get(db,pid,rid); content=r['content'].copy()
            target=content.get('candidate_for')
            if not target or content.get('adopted_into'): raise HTTPException(409,'此候选已采用或没有对应原稿')
            old=store.get(db,pid,target)
            if old['version']!=content['input_version']: raise HTTPException(409,'原稿已有新版本，请重新修改；旧候选仍保留供比较')
            for k in ('candidate_for','input_version'): content.pop(k,None)
            result=store.save(db,pid,target,old['version'],content,source=r['source'])
            db.execute('UPDATE records SET adopted=? WHERE id=?',(result['version'],target))
            store.save(db,pid,rid,r['version'],{**r['content'],'adopted_into':{'id':target,'version':result['version']}},source=r['source'])
            return store.get(db,pid,target)
    return run
