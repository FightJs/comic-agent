"""Production boundary: frozen inputs, explicit discussion and candidate adoption."""
import asyncio
import json
from typing import Literal
from fastapi import BackgroundTasks, HTTPException
from pydantic import BaseModel, Field
from .store import uid, now, dump, is_primary
from .simulation import demo_image
from .production_text import generate, schema as production_schema, PARTS, ProductionInputError, document_content
from .agent_tools import freeze_context, parse_coverage
from .graph_documents import get_document
from .skills import stage_instructions
from .agent import plan_receipt
from .image_jobs import image_inputs_stale
from . import production_resume, production_references, manual_pause, tool_receipts, tool_recovery, recovery_service

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
    refs: list[Ref] = Field(min_length=1,max_length=300)
    message: str = Field(min_length=1,max_length=20000)
    expected_version: int = Field(ge=0)
class SelectedReviewIn(BaseModel):
    refs: list[Ref] = Field(min_length=1,max_length=1000)
    decision: Literal['approved','changes']
    note: str = Field(default='',max_length=10000)

class JobIn(BaseModel):
    operation: Literal['range','rewrite','package','image','repair','document']
    document_kind: Literal['skeleton','outline'] | None = None
    basis: list[Ref] = Field(default_factory=list,max_length=1)
    refs: list[Ref] = Field(default_factory=list,max_length=300)
    instruction: str = Field(default='',max_length=20000)
    per_item: dict[str,str] = Field(default_factory=dict)
    annotation_versions: dict[str,int] = Field(default_factory=dict)
    submission_id: str = Field(min_length=1,max_length=100)
    conversation_id: str | None = None
    conversation_version: int | None = None
    agent_run_ids: list[str] = Field(default_factory=list,max_length=100)
    outline_id: str | None = None
    outline_version: int | None = None
    index_version: int | None = None
    start: int = Field(default=1,ge=1)
    end: int = Field(default=1,ge=1)

def register_workflow(app, store):
    production_schema(store,recover=True)
    with store.db() as db:
        manual_pause.schema(db)
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
            if not is_primary(r):raise HTTPException(409,'请先采用有效细纲，再校正话索引')
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

    def input_refs(payload):
        refs={}
        for key in ('snapshots','originals','skeletons','assets','context'):
            for r in payload.get(key,[]):refs[r['id']]=r['version']
        for key in ('outline','index'):
            if payload.get(key):refs[payload[key]['id']]=payload[key]['version']
        return refs

    def stale_inputs(db,pid,payload):
        if payload.get('frozen') and production_references.state_stale(store,db,pid,payload.get('assets',[])):return True
        if image_inputs_stale(store,db,pid,payload):return True
        if 'original_selection' in payload:
            current=db.execute('SELECT * FROM graph_source WHERE project_id=?',(pid,)).fetchone()
            if (dict(current) if current else None)!=payload['original_selection']:return True
        for rid,version in payload.get('input_refs',{}).items():
            if store.get(db,pid,rid)['version']!=version:return True
        if 'queried_graph_revision' in payload:
            from .graph_store import load
            if load(store,db,pid)[0]!=payload['queried_graph_revision']:return True
        for did,version in payload.get('document_refs',{}).items():
            row=db.execute('SELECT parse_version FROM documents WHERE id=? AND project_id=?',(did,pid)).fetchone()
            if not row or row['parse_version']!=version:return True
        return False

    async def run(tid):
        with store.db() as db:
            t=db.execute('SELECT * FROM tasks WHERE id=?',(tid,)).fetchone()
            if not t or t['status']!='queued':return
            pid=t['project_id'];p=json.loads(t['payload'])
            if not db.execute("UPDATE tasks SET status='running',updated=? WHERE id=? AND status='queued'",(now(),tid)).rowcount:return
        try:
            op=p['operation'];text_op=op in ('range','rewrite','package','document')
            if text_op:
                if not p.get('frozen'):raise ProductionInputError('旧模拟文本任务不能直接转为付费任务，请重新核对输入后提交')
                with store.db() as db:config=app.state.graph_engine.config(db)
                if not config or {k:config.get(k) for k in ('url','model','api')}!=p['provider']:raise ProductionInputError('文本模型配置已变化或缺失，请重新核对配置后提交')
                from .capacity import text_dispatch_guard
                resuming=bool(p.get('production_resume'))
                def before(db):
                    if resuming:production_resume.validate(store,db,pid,p,stale_inputs)
                    current=db.execute('SELECT status FROM tasks WHERE id=?',(tid,)).fetchone()
                    if not current or current['status']!='running':raise ProductionInputError('生产任务已停止，未提交模型')
                    if stale_inputs(db,pid,p):raise ProductionInputError('生产输入已变化，未提交模型；请重新核对输入')
                generated=await generate(app,store,pid,tid,p,config,before_dispatch=text_dispatch_guard(app,store,config,before))
            with store.db() as db:
                db.execute('BEGIN IMMEDIATE')
                if db.execute('SELECT status FROM tasks WHERE id=?',(tid,)).fetchone()['status']!='running':return
                item=p['snapshots'][0] if p['snapshots'] else None
                outputs=[]
                if text_op:
                    stale=stale_inputs(db,pid,p)
                    contents=[]
                    if op=='document':
                        contents.append((p['document_kind'],document_content(p['document_kind'],generated),item))
                    elif op=='range':
                        for panel in generated['panels']:
                            content={**panel,'episode':p['episode'],'batch':p['batch'],'episode_title':p['entry']['title'],'source_range':p['entry'].get('source_range',''),'outline_id':p['outline_id'],'outline_version':p['outline_version']}
                            contents.append(('script',content,None))
                    else:
                        content=item['content'].copy();kind=item['kind'];target=item
                        if op=='rewrite':
                            content.update(generated['patch'])
                            if kind=='package':
                                if 'prompt' in generated['patch']:content['prompt_mode']='override'
                                elif content.get('prompt_mode')=='override' or content.get('prompt') and not content.get('prompt_mode'):content['prompt_mode']='override'
                                else:content['prompt']='\n\n'.join(content.get(k,'') for k in PARTS)
                        else:
                            kind='package';target=p.get('existing_package')
                            content={k:content.get(k) for k in ('characters','scene')}
                            content.update(batch=p['batch'],episode=p['episode'],panel=p['panel'])
                            content.update(generated,script_id=item['id'],script_version=item['version'],references=[{'id':a['id'],'version':a['version'],'purpose':a['content'].get('category','参考')} for a in p['assets']],prompt='\n\n'.join(generated[k] for k in PARTS),prompt_mode='composed')
                        contents.append((kind,content,target))
                    for kind,content,target in contents:
                        for k in ('candidate_for','creation_candidate','input_version','adopted_into'):content.pop(k,None)
                        if target:content.update(candidate_for=target['id'],input_version=target['version'])
                        else:content['creation_candidate']=True
                        content.update(task_id=tid,input_stale=stale)
                        title='候选 · '+generated['title'] if op=='document' else f"候选 · 第{p['episode']}话第{content.get('panel',p['panel'])}格"
                        result=store.add(db,pid,kind,title,content,p['source'])
                        db.execute('UPDATE records SET adopted=0 WHERE id=?',(result['id'],))
                        outputs.append(store.get(db,pid,result['id']))
                else:
                    # Image execution remains an explicit fixture until the image adapter lands.
                    content=item['content'].copy();kind='image';target=p['target_head'] if op=='repair' else p.get('existing_image')
                    raw=demo_image(item['content'].get('panel',1)-1)
                    content.update(url=store.file(db,pid,'模拟修改结果.png',raw,'image/png'),width=640,height=900,filename='模拟修改结果.png',issues=[],checked=False,applied_instruction=p['instruction'])
                    if op=='image':content.update(package_id=item['id'],package_version=item['version'])
                    for k in ('candidate_for','input_version','adopted_into'):content.pop(k,None)
                    if target:content.update(candidate_for=target['id'],input_version=target['version'])
                    content['task_id']=tid
                    outputs.append(store.add(db,pid,kind,'候选 · '+item['title'],content,'mock'))
                p['output_ids']=[r['id'] for r in outputs]
                p['output_versions']={r['id']:r['version'] for r in outputs}
                db.execute("UPDATE tasks SET status='succeeded',output_id=?,payload=?,updated=? WHERE id=?",(outputs[0]['id'],dump(p),now(),tid))
        except production_resume.ProductionPaused as exc:
            with store.db() as db:db.execute("UPDATE tasks SET status='paused',payload=?,error=?,updated=? WHERE id=? AND status='running'",(dump(p),str(exc),now(),tid))
        except asyncio.CancelledError:
            with store.db() as db:db.execute("UPDATE tasks SET status='interrupted',error='运行中断，输入已保留；可明确重试',updated=? WHERE id=? AND status='running'",(now(),tid))
            raise
        except Exception as exc:
            message=str(exc) if isinstance(exc,ProductionInputError) else '模型调用或结果校验失败；输入与可用回执已保留，未发布部分成品'
            with store.db() as db:db.execute("UPDATE tasks SET status='failed',error=?,updated=? WHERE id=? AND status='running'",(message,now(),tid))

    @app.post('/api/projects/{pid}/production-jobs')
    def jobs(pid:str,body:JobIn,background:BackgroundTasks):
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE'); store.project(db,pid)
            prior=db.execute('SELECT response FROM workflow_submissions WHERE project_id=? AND token=?',(pid,body.submission_id)).fetchone()
            if prior: return json.loads(prior['response'])
            rows=all_records(db,pid); snapshots=[]; payloads=[]
            inflight=[json.loads(t['payload']) for t in db.execute("SELECT payload FROM tasks WHERE project_id=? AND status IN ('queued','running','paused')",(pid,))]
            for ref in body.refs:
                current=store.get(db,pid,ref.id); r=store.get(db,pid,ref.id,ref.version)
                if body.operation!='repair' and current['version']!=ref.version: raise HTTPException(409,'输入版本已变化，请重新查看')
                if not is_primary(r): raise HTTPException(422,'请先采用候选结果')
                snapshots.append(r)
            if len({r['id'] for r in snapshots})!=len(snapshots): raise HTTPException(422,'选择重复')
            conversation=None
            if body.conversation_id:
                conversation=store.get(db,pid,body.conversation_id,body.conversation_version)
                if conversation['kind']!='conversation' or ref_key(conversation['content']['refs'])!=ref_key([r.model_dump() for r in body.refs]): raise HTTPException(422,'对话不属于当前选择及版本')
                if store.get(db,pid,conversation['id'])['version']!=body.conversation_version: raise HTTPException(409,'对话已有新消息，请核对方案')
            if body.agent_run_ids and body.operation!='rewrite':raise HTTPException(422,'批次AI讨论回执目前仅用于文本修改')
            receipts=[plan_receipt(store,db,pid,rid,[r.model_dump() for r in body.refs]) for rid in dict.fromkeys(body.agent_run_ids)]
            common={'workflow':True,'operation':body.operation,'instruction':body.instruction,'conversation':conversation,'agent_discussions':receipts,'group_id':body.submission_id,'source':'mock'}
            if body.operation=='document':
                kind=body.document_kind
                if kind not in ('skeleton','outline') or len(snapshots)>1 or any(r['kind']!=kind for r in snapshots):raise HTTPException(422,'请选择骨架或细纲及至多一个同类改稿目标')
                if any(t.get('operation')=='document' and t.get('document_kind')==kind for t in inflight):raise HTTPException(409,'同类文档正在生成，请等待完成')
                if not snapshots and any(r['kind']==kind and r['content'].get('creation_candidate') and not r['content'].get('rejected') for r in rows):raise HTTPException(409,'已有待采用文档候选，请先核对采用或拒绝')
                originals=[r for r in rows if r['kind']=='original']
                if not originals:raise HTTPException(422,'请先导入原著，再生成骨架或细纲')
                selection=db.execute('SELECT * FROM graph_source WHERE project_id=?',(pid,)).fetchone()
                originals=[r for r in originals if r['content'].get('document_id')==selection['document_id']] if selection else [max(originals,key=lambda r:(r['created'],r['id']))]
                if not originals:raise HTTPException(422,'当前选定原著不可读取，请重新核对导入状态')
                for original in originals:
                    did=original['content'].get('document_id')
                    if not did or not parse_coverage(get_document(store,db,pid,did))['complete']:raise HTTPException(422,'当前原著尚未完整解析，请先完成OCR或重新导入完整正文')
                skeletons=[]
                for ref in body.basis:
                    basis=store.get(db,pid,ref.id)
                    if kind!='outline' or basis['kind']!='skeleton' or basis['version']!=ref.version or not is_primary(basis):raise HTTPException(409,'参考骨架已变化或尚未采用，请重新核对')
                    skeletons.append(basis)
                payloads.append({**common,'kind':kind,'document_kind':kind,'original_selection':dict(selection) if selection else None,'snapshots':snapshots,'originals':originals,'skeletons':skeletons,'episode':1,'panel':1,'batch':1})
            elif body.operation=='range':
                outline=store.get(db,pid,body.outline_id)
                index=find_index(db,pid,body.outline_id)
                if outline['kind']!='outline' or not is_primary(outline) or outline['version']!=body.outline_version or not index or index['version']!=body.index_version or index['content']['outline_version']!=outline['version']: raise HTTPException(409,'请先核对并保存当前细纲话索引')
                if body.end<body.start or body.end-body.start>=100: raise HTTPException(422,'单次请选择1至100话')
                originals=[r for r in rows if r['kind']=='original']
                if not originals: raise HTTPException(422,'请先导入整部原著')
                entries={e['episode']:e for e in index['content']['entries']}
                missing=[n for n in range(body.start,body.end+1) if n not in entries]
                if missing: raise HTTPException(422,'细纲缺少话号：'+','.join(map(str,missing)))
                for n in range(body.start,body.end+1):
                    if any(t.get('operation')=='range' and t.get('episode')==n for t in inflight): raise HTTPException(409,f'第{n}话正在生成，请等待任务完成')
                    if any(r['kind']=='script' and r['content'].get('episode')==n and r['content'].get('creation_candidate') and not r['content'].get('rejected') for r in rows):raise HTTPException(409,f'第{n}话已有待采用候选，请先核对采用或拒绝')
                    existing=[r for r in rows if r['kind']=='script' and r['content'].get('episode')==n and not r['content'].get('candidate_for') and not r['content'].get('pending_for') and not r['content'].get('creation_candidate')]
                    if existing: raise HTTPException(409,f'第{n}话已有脚本，请使用选格修改，不重复生成整话')
                    payloads.append({**common,'kind':'script','episode':n,'panel':1,'batch':(n-1)//10+1,'snapshots':[],'entry':entries[n],'outline_id':outline['id'],'outline_version':outline['version'],'outline':outline,'index':index,'originals':originals,'skeletons':[r for r in rows if r['kind']=='skeleton' and is_primary(r)],'existing':[]})
            else:
                expected={'rewrite':('script','package'),'package':('script',),'image':('package',),'repair':('image',)}[body.operation]
                if not snapshots or any(r['kind'] not in expected for r in snapshots): raise HTTPException(422,'当前操作的选择类型无效')
                for r in snapshots:
                    content=r['content']; episode=content.get('episode',1); panel=content.get('panel',1)
                    if body.operation in ('package','image') and any(t.get('operation')==body.operation and t.get('episode')==episode and t.get('panel')==panel for t in inflight): raise HTTPException(409,f'第{episode}话第{panel}格正在生成，请等待任务完成')
                    if body.operation=='package' and any(x['kind']=='package' and x['content'].get('episode')==episode and x['content'].get('panel')==panel and x['content'].get('creation_candidate') and not x['content'].get('rejected') for x in rows):raise HTTPException(409,'此格已有待采用生图包，请先核对采用或拒绝')
                    annotations=None
                    if body.operation=='repair':
                        ann=db.execute('SELECT version,items FROM annotations WHERE record_id=? AND image_version=?',(r['id'],r['version'])).fetchone()
                        annotations={'version':ann['version'] if ann else 0,'items':json.loads(ann['items']) if ann else []}
                        if r['id'] not in body.annotation_versions: raise HTTPException(422,'请先读取并核对底图批注')
                        if body.annotation_versions[r['id']]!=annotations['version']: raise HTTPException(409,'区域批注已变化，请重新核对后生成')
                    def existing(kind): return next((x for x in rows if x['kind']==kind and x['content'].get('episode')==episode and x['content'].get('panel')==panel and not x['content'].get('candidate_for') and not x['content'].get('pending_for') and not x['content'].get('creation_candidate')),None)
                    assets=[]
                    if body.operation=='package':
                        for asset in rows:
                            if asset['kind']=='asset' and is_primary(asset):
                                adopted=store.get(db,pid,asset['id'],asset['adopted'])
                                if adopted['review']=='approved':assets.append(adopted)
                    if body.operation=='image':
                        if not content.get('prompt','').strip(): raise HTTPException(422,f'第{episode}话第{panel}格缺少完整提示词')
                        for ref in content.get('references',[]): assets.append(store.get(db,pid,ref['id'],ref['version']))
                    payloads.append({**common,'kind':'repair' if body.operation=='repair' else r['kind'] if body.operation=='rewrite' else body.operation,'episode':episode,'panel':panel,'batch':content.get('batch',(episode-1)//10+1),'snapshots':[r],'target_head':store.get(db,pid,r['id']),'instruction':body.instruction+ ('\n该格补充：'+body.per_item[r['id']] if body.per_item.get(r['id']) else ''),'annotation_snapshot':annotations,'assets':assets,'context':[x for x in rows if x['kind']=='script' and x['content'].get('episode')==episode and is_primary(x)],'existing_package':existing('package'),'existing_image':existing('image')})
            if body.operation in ('range','rewrite','package','document'):
                config=app.state.graph_engine.config(db)
                if not config:raise HTTPException(422,'请先配置文本模型与密钥，再生成正式文本候选')
                for payload in payloads:
                    stage=payload['document_kind'] if body.operation=='document' else 'script' if body.operation=='range' or body.operation=='rewrite' and payload['kind']=='script' else 'package'
                    frozen=freeze_context(store,db,pid,stage=stage)
                    readable={r['id'] for r in rows if is_primary(r)}
                    frozen['records']={rid:r for rid,r in frozen['records'].items() if rid in readable}
                    if body.operation=='document':
                        dids={r['content']['document_id'] for r in payload['originals']}
                        rids=set(input_refs(payload))
                        frozen['documents']={did:v for did,v in frozen['documents'].items() if did in dids}
                        frozen['novel_memory']={did:info for did,info in frozen['novel_memory'].items() if did in dids}
                        if frozen.get('preferred_document',{} ) and frozen['preferred_document']['id'] not in dids:frozen['preferred_document']=None
                        frozen['records']={rid:r for rid,r in frozen['records'].items() if rid in rids}
                    # Validate rule size before authorizing any calls.
                    stage_instructions(db,frozen['skills'])
                    selected_source=db.execute('SELECT * FROM graph_source WHERE project_id=?',(pid,)).fetchone()
                    payload.setdefault('original_selection',dict(selected_source) if selected_source else None)
                    frozen['frame_plan_sources']={rid:info for rid,info in frozen.get('frame_plan_sources',{}).items() if rid in frozen['records']}
                    payload.update(frozen=frozen,skills=frozen['skills'],provider={k:config.get(k) for k in ('url','model','api')},source='ai')
                    payload['input_refs']=input_refs(payload)
                    payload['document_refs']=frozen['documents']
                    dependencies=[store.get(db,pid,rid,version) for rid,version in payload['input_refs'].items()]
                    if any(r['source']=='mock' for r in dependencies) or conversation and conversation['source']=='mock' or any(r['source']=='mock' for r in receipts):payload['source']='mock'
            ids=[]
            for payload in payloads:
                tid=uid(); stamp=now(); ids.append(tid)
                db.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?)',(tid,pid,'queued',dump(payload),None,'',stamp,stamp))
            result={'ids':ids,'status':'queued','source':'mock' if any(p['source']=='mock' for p in payloads) else 'ai'}
            db.execute('INSERT INTO workflow_submissions VALUES(?,?,?)',(pid,body.submission_id,dump(result)))
        for tid in ids: background.add_task(run,tid)
        return result

    @app.get('/api/projects/{pid}/production-jobs/{tid}/attempts')
    def attempts(pid:str,tid:str):
        with store.db() as db:
            if not db.execute('SELECT 1 FROM tasks WHERE id=? AND project_id=?',(tid,pid)).fetchone():raise HTTPException(404,'任务不存在')
            return [{**dict(r),'checkpoint':json.loads(cp[0]) if (cp:=db.execute('SELECT content FROM production_checkpoints WHERE attempt_id=?',(r['id'],)).fetchone()) else None,'continuation':{'parent_id':parent[0] if (parent:=db.execute('SELECT parent_id FROM production_continuations WHERE child_id=?',(r['id'],)).fetchone()) else None,'child_id':child[0] if (child:=db.execute('SELECT child_id FROM production_continuations WHERE parent_id=?',(r['id'],)).fetchone()) else None},'usage':json.loads(r['usage']) if r['usage'] else None,'tools':[{'name':t['name'],'arguments':json.loads(t['arguments']),'result':json.loads(t['result'])} for t in db.execute('SELECT * FROM production_tool_calls WHERE attempt_id=? ORDER BY created',(r['id'],))]} for r in db.execute('SELECT * FROM production_attempts WHERE task_id=? ORDER BY created',(tid,))]

    @app.get('/api/projects/{pid}/production-jobs/{tid}/attempts/{aid}/tool-receipts')
    async def production_receipts(pid:str,tid:str,aid:str):
        with store.db() as db:
            task=db.execute('SELECT id FROM tasks WHERE id=? AND project_id=?',(tid,pid)).fetchone()
            attempt=db.execute('SELECT id FROM production_attempts WHERE id=? AND task_id=?',(aid,tid)).fetchone()
            if not task or not attempt:raise HTTPException(404,'生产任务或运行段不属于当前项目')
            compiled=production_resume.request(db,aid)
            host=tool_receipts.summaries(db,pid,'production',aid)
        try:response=await app.state.pi_runtime.request('checkpoint_details',project_id=pid,session_id=compiled['session_id'],run_id=aid,timeout=10)
        except Exception:raise HTTPException(503,'Pi回执暂不可读取；未重新调用模型或工具')
        if response.get('type')!='result':raise HTTPException(409,'检查点缺失或未通过核对；不推断工具未执行')
        value=response.get('data',{}).get('checkpoint',{})
        if value.get('run_id')!=aid or value.get('session_id')!=compiled['session_id']:raise HTTPException(409,'检查点归属不匹配')
        with store.db() as db:
            available=recovery_service.available(db,pid,'production',aid,db.execute('SELECT status FROM production_attempts WHERE id=?',(aid,)).fetchone()[0],{**value,'_interrupted':response.get('data',{}).get('interrupted') is True})
            try: recovery_production_current(db,pid,tid,aid)
            except HTTPException: available=False
            return {'attempt_id':aid,'receipts':tool_receipts.compare(host,value),'read_only':True,'recovery_available':available,'recovery':tool_recovery.metadata(db,pid,'production',aid)}

    def recovery_production_current(db,pid,tid,aid):
        row=db.execute('SELECT * FROM tasks WHERE id=? AND project_id=?',(tid,pid)).fetchone()
        parent=db.execute('SELECT * FROM production_attempts WHERE id=? AND task_id=?',(aid,tid)).fetchone()
        if not row or not parent:raise HTTPException(404,'生产任务或运行段不属于当前项目')
        if row['status'] not in ('failed','interrupted','paused') or parent['status'] not in ('error','failed','interrupted','paused'):raise HTTPException(409,'原生产段不可恢复')
        if db.execute('SELECT 1 FROM production_continuations WHERE parent_id=?',(aid,)).fetchone() or db.execute("SELECT 1 FROM production_attempts WHERE task_id=? AND (status IN ('queued','running') OR rowid>(SELECT rowid FROM production_attempts WHERE id=?)) AND id!=?",(tid,aid,aid)).fetchone():raise HTTPException(409,'生产段已有后继或在途调用')
        payload=json.loads(row['payload'])
        if not payload.get('frozen'):raise HTTPException(409,'缺少冻结输入')
        production_resume.validate(store,db,pid,payload,stale_inputs)
        compiled=production_resume.request(db,aid)
        if not compiled.get('request_prompt') or not compiled.get('config'):raise HTTPException(409,'缺少原始生产请求')
        return row,parent,payload,compiled

    @app.post('/api/projects/{pid}/production-jobs/{tid}/attempts/{aid}/recover-tools')
    async def recover_production(pid:str,tid:str,aid:str,body:recovery_service.RecoverProduction):
        with store.db() as db:
            row,parent,payload,compiled=recovery_production_current(db,pid,tid,aid)
            meta=tool_recovery.metadata(db,pid,'production',aid)
            if meta and meta['status']=='completed':return {'id':tid,'status':row['status'],'attempt_id':aid,'recovery':meta}
        def publish(db,cp):
            row,parent,payload,unused=recovery_production_current(db,pid,tid,aid)
            cp={k:v for k,v in cp.items() if k!='tools'}
            payload['production_checkpoint']={'attempt_id':aid,**cp}
            db.execute('INSERT OR REPLACE INTO production_checkpoints VALUES(?,?)',(aid,dump(cp)))
            db.execute("UPDATE production_attempts SET status='paused' WHERE id=?",(aid,))
            db.execute("UPDATE tasks SET status='paused',payload=?,error='tools_recovered',updated=? WHERE id=?",(dump(payload),now(),tid))
            return {'id':tid,'status':'paused','attempt_id':aid,'checkpoint':cp,'recovery':tool_recovery.metadata(db,pid,'production',aid)}
        return await recovery_service.recover(store,app.state.pi_runtime,pid,'production',aid,compiled['session_id'],lambda db:recovery_production_current(db,pid,tid,aid),publish)

    @app.post('/api/projects/{pid}/production-jobs/{tid}/attempts/{aid}/continue')
    async def continue_production(pid:str,tid:str,aid:str,body:production_resume.ContinueProduction,background:BackgroundTasks):
        if not body.confirm:raise HTTPException(422,'请明确授权新增最多20次模型请求和50次工具派发；费用未知')
        def current(db):
            row=db.execute('SELECT * FROM tasks WHERE id=? AND project_id=?',(tid,pid)).fetchone()
            parent=db.execute('SELECT * FROM production_attempts WHERE id=? AND task_id=?',(aid,tid)).fetchone()
            if not row or not parent:raise HTTPException(404,'生产任务或运行段不属于当前项目')
            linked=db.execute('SELECT child_id FROM production_continuations WHERE parent_id=?',(aid,)).fetchone()
            if linked:return row,parent,json.loads(row['payload']),linked[0]
            if row['status']!='paused' or parent['status']!='paused':raise HTTPException(409,'只能续接已保存暂停的生产段；普通失败或未知调用不恢复')
            payload=json.loads(row['payload'])
            if payload.get('production_checkpoint',{}).get('attempt_id')!=aid:raise HTTPException(409,'此检查点不是当前暂停段')
            production_resume.validate(store,db,pid,payload,stale_inputs)
            return row,parent,payload,None
        with store.db() as db:
            row,parent,payload,child=current(db)
            if child:return {'id':tid,'status':row['status'],'attempt_id':child}
            compiled=production_resume.request(db,aid)
            recovery_service.unlocked(db,pid,compiled['session_id'])
        try:response=await app.state.pi_runtime.request('checkpoint',project_id=pid,session_id=compiled['session_id'],run_id=aid,timeout=10)
        except Exception:raise HTTPException(503,'检查点暂不可用；未提交新模型')
        cp=response.get('data',{}).get('checkpoint',{})
        if cp.get('run_id')!=aid or cp.get('session_id')!=compiled['session_id'] or not production_resume.clean(cp):raise HTTPException(409,'检查点缺失、有未决调用或已续接；未提交新模型')
        from .capacity import text_dispatch_guard
        text_dispatch_guard(app,store,compiled['config'])()
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE');row,parent,payload,child=current(db)
            recovery_service.unlocked(db,pid,compiled['session_id'])
            if child:return {'id':tid,'status':row['status'],'attempt_id':child}
            child=uid();stamp=now()
            db.execute('INSERT INTO production_attempts VALUES(?,?,?,?,?,?,?)',(child,tid,parent['attempt'],'queued','',None,stamp))
            db.execute('INSERT INTO production_requests VALUES(?,?)',(child,dump(compiled)))
            db.execute('INSERT INTO production_continuations VALUES(?,?)',(aid,child))
            db.execute("UPDATE production_attempts SET status='continued' WHERE id=?",(aid,))
            payload['production_resume']={'parent_id':aid,'child_id':child}
            payload['production_continuation']=True
            payload.pop('production_checkpoint',None)
            manual_pause.clear(db,'production',tid)
            db.execute("UPDATE tasks SET status='queued',payload=?,error='',updated=? WHERE id=?",(dump(payload),stamp,tid))
        background.add_task(run,tid)
        return {'id':tid,'status':'queued','attempt_id':child}

    @app.post('/api/projects/{pid}/production-jobs/{tid}/pause')
    async def pause_production(pid:str,tid:str,body:manual_pause.PauseIn):
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM tasks WHERE id=? AND project_id=?',(tid,pid)).fetchone()
            if not row:raise HTTPException(404,'任务不存在')
            payload=json.loads(row['payload'])
            if payload.get('operation') not in ('document','range','rewrite','package') or not payload.get('frozen'):raise HTTPException(409,'此任务不是可暂停的Pi文本生产；图像与模拟任务使用其原控制入口')
            if row['status'] not in ('queued','running'):return {'id':tid,'status':row['status'],'pause_requested':manual_pause.requested(db,'production',tid)}
            manual_pause.mark(db,'production',tid)
            active=db.execute("SELECT id FROM production_attempts WHERE task_id=? AND status IN ('queued','running') ORDER BY created DESC LIMIT 1",(tid,)).fetchone()
        if active:
            try:await app.state.pi_runtime.request('pause',run_id=active['id'],timeout=10)
            except Exception:raise HTTPException(503,'暂停意图已保存，但运行层暂不可确认；请核对原回执，不表示已经暂停')
        with store.db() as db:
            row=db.execute('SELECT status FROM tasks WHERE id=? AND project_id=?',(tid,pid)).fetchone()
            return {'id':tid,'status':row['status'],'pause_requested':True}

    @app.post('/api/projects/{pid}/production-jobs/{tid}/cancel')
    async def cancel_job(pid:str,tid:str):
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM tasks WHERE id=? AND project_id=?',(tid,pid)).fetchone()
            if not row:raise HTTPException(404,'任务不存在')
            if row['status'] not in ('queued','running','paused','failed','interrupted'):raise HTTPException(409,'任务已结束')
            db.execute('DELETE FROM pi_recovery_locks WHERE project_id=? AND owner_id IN (SELECT id FROM production_attempts WHERE task_id=?)',(pid,tid))
            db.execute("UPDATE tasks SET status='cancelled',error='用户已取消；迟到结果不会发布',updated=? WHERE id=?",(now(),tid))
            active=db.execute("SELECT id FROM production_attempts WHERE task_id=? AND status='running' ORDER BY created DESC LIMIT 1",(tid,)).fetchone()
        if active:
            try:await app.state.pi_runtime.request('cancel',run_id=active['id'],timeout=3)
            except Exception:pass
        return {'id':tid,'status':'cancelled'}

    @app.post('/api/projects/{pid}/production-review')
    def review_selected(pid:str,body:SelectedReviewIn):
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            snapshots=[]
            for ref in body.refs:
                r=store.get(db,pid,ref.id)
                if r['version']!=ref.version: raise HTTPException(409,'所选脚本已有新版本，本次审核未写入，请重新核对')
                if r['kind']!='script' or not is_primary(r): raise HTTPException(422,'请选择当前脚本，候选请先采用')
                snapshots.append(r)
            for r in snapshots:
                db.execute('INSERT INTO reviews VALUES(?,?,?,?,?,?,?)',(uid(),r['id'],r['version'],body.decision,body.note,r['source'],now()))
            return {'reviewed':len(snapshots)}

    @app.post('/api/projects/{pid}/candidates/{rid}/reject')
    def reject_candidate(pid:str,rid:str):
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE');r=store.get(db,pid,rid)
            if r['content'].get('adopted_into') or not (r['content'].get('candidate_for') or r['content'].get('creation_candidate')):raise HTTPException(409,'此内容已采用或不是待采用候选')
            if r['content'].get('rejected'):return r
            return store.save(db,pid,rid,r['version'],{**r['content'],'rejected':True},source=r['source'])

    def adopt_document_index(db,pid,record):
        if record['kind']!='outline' or not record['content'].get('generated_entries'):return
        content={'outline_id':record['id'],'outline_version':record['version'],'entries':record['content']['generated_entries']}
        old=find_index(db,pid,record['id'])
        if old:store.save(db,pid,old['id'],old['version'],content,source=record['source'])
        else:store.add(db,pid,'outline_index','细纲话索引',content,record['source'])

    @app.post('/api/projects/{pid}/candidates/{rid}/adopt')
    def adopt_candidate(pid:str,rid:str):
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            r=store.get(db,pid,rid); content=r['content'].copy()
            if content.get('rejected'):raise HTTPException(409,'此候选已拒绝，请建立新的生成任务')
            origin_task=db.execute('SELECT status,payload FROM image_jobs WHERE id=? AND project_id=?',(content['image_job_id'],pid)).fetchone() if content.get('image_job_id') else db.execute('SELECT status,payload FROM tasks WHERE id=? AND project_id=?',(content.get('task_id'),pid)).fetchone()
            if not origin_task or origin_task['status']!='succeeded':raise HTTPException(409,'候选没有有效的已完成生产回执')
            if origin_task:
                manifest=json.loads(origin_task['payload'])
                if rid not in manifest.get('output_ids',[]):raise HTTPException(409,'候选不属于此生产回执')
                if manifest.get('frozen') and r['version']!=manifest.get('output_versions',{}).get(rid,1):raise HTTPException(409,'候选内容已变化，历史生成稿仍保留；请重新生成并核对')
            target=content.get('candidate_for')
            if content.get('creation_candidate'):
                if content.get('adopted_into'):raise HTTPException(409,'此候选已采用')
                task=origin_task
                if not task or task['status']!='succeeded':raise HTTPException(409,'候选所属任务尚未成功')
                payload=json.loads(task['payload'])
                if stale_inputs(db,pid,payload):raise HTTPException(409,'生成输入已变化，旧候选保留；请重新生成')
                for other in all_records(db,pid,r['kind']):
                    if r['kind'] in ('script','package','image') and other['id']!=rid and not other['content'].get('candidate_for') and not other['content'].get('creation_candidate') and other['content'].get('episode')==content.get('episode') and other['content'].get('panel')==content.get('panel'):raise HTTPException(409,'此话格已有正式内容，候选不能覆盖')
                content.pop('creation_candidate');content.pop('input_stale',None)
                result=store.save(db,pid,rid,r['version'],content,title=r['title'].removeprefix('候选 · '),source=r['source'])
                db.execute('UPDATE records SET adopted=? WHERE id=?',(result['version'],rid))
                adopt_document_index(db,pid,result)
                return store.get(db,pid,rid)
            if not target or content.get('adopted_into'): raise HTTPException(409,'此候选已采用或没有对应原稿')
            task=origin_task
            if task and stale_inputs(db,pid,json.loads(task['payload'])):raise HTTPException(409,'生成输入已变化，旧候选仍保留')
            old=store.get(db,pid,target)
            if old['kind']=='original' or old['kind']!=r['kind']:raise HTTPException(409,'候选不能覆盖原著或不同类型内容')
            if old['version']!=content['input_version']: raise HTTPException(409,'原稿已有新版本，请重新修改；旧候选仍保留供比较')
            for k in ('candidate_for','input_version'): content.pop(k,None)
            result=store.save(db,pid,target,old['version'],content,source=r['source'])
            db.execute('UPDATE records SET adopted=? WHERE id=?',(result['version'],target))
            adopt_document_index(db,pid,result)
            store.save(db,pid,rid,r['version'],{**r['content'],'adopted_into':{'id':target,'version':result['version']}},source=r['source'])
            return store.get(db,pid,target)
    return run
