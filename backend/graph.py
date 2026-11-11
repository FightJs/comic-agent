"""Graph/document API: ordinary JSON, immutable source references, optimistic revisions."""
import copy
import json
import time
from pathlib import Path
import httpx
from fastapi import UploadFile, File, Form, HTTPException
from .store import uid, now, dump, is_primary
from . import graph_documents as docs
from . import graph_store as gs
from .graph_engine import GraphEngine, public_job, outline_text, outline_chapters


def register_graph(app,store,vault_get):
    with store.db() as db: docs.schema(db); gs.schema(db)
    engine=GraphEngine(app,store,vault_get); app.state.graph_engine=engine
    with store.db() as db: docs.migrate_legacy(store,db)
    store.graph_record_changed=engine.record_changed
    app.router.add_event_handler('startup',engine.start)
    app.router.add_event_handler('shutdown',engine.stop)

    def parse_file(raw,title,encoding):
        try:
            parsed=docs.parse_bytes(raw,title,encoding)
            if Path(title).suffix.lower()!='.pdf' or not any('PDF 页面无可提取文字' in w for w in parsed[2]): return parsed
        except HTTPException:
            if Path(title).suffix.lower()!='.pdf': raise
            parsed=('',[],[],'unicode')
        return parsed[0],parsed[1],['[waiting_ocr] PDF 含扫描页或不可提取页；等待 MinerU 完整解析，禁止跳过缺页发布。'],'unicode'

    def job(db,pid,jid):
        store.project(db,pid)
        row=db.execute('SELECT * FROM graph_jobs WHERE id=? AND project_id=?',(jid,pid)).fetchone()
        if not row: raise HTTPException(404,'图谱任务不存在')
        return row

    def selection(db,pid):
        store.project(db,pid)
        row=db.execute('SELECT * FROM graph_outline WHERE project_id=?',(pid,)).fetchone()
        return {'record_id':row['record_id'],'version':row['version'],'status':row['status']} if row else {'record_id':None,'version':None,'status':'unselected'}

    def changed_document(db,pid,d):
        db.execute("UPDATE graph_jobs SET status='superseded',error='新的解析版本已创建' WHERE document_id=? AND parse_version<>? AND status IN ('queued','running','waiting_config','waiting_ocr','paused','interrupted')",(d['id'],d['parse_version']))
        row=db.execute('SELECT record_id FROM documents WHERE id=?',(d['id'],)).fetchone()
        r=store.get(db,pid,row['record_id']); content={**r['content'],'parse_version':d['parse_version'],'chapters':d['chapters'],'char_count':d['char_count']}
        store.save(db,pid,r['id'],r['version'],content,source='import')
        engine.create_job(db,pid,d['id'])
        return d

    @app.get('/api/projects/{pid}/documents')
    def documents(pid:str):
        with store.db() as db:
            store.project(db,pid)
            return [docs.get_document(store,db,pid,r['id']) for r in db.execute('SELECT id FROM documents WHERE project_id=? ORDER BY created',(pid,))]

    @app.post('/api/projects/{pid}/documents')
    async def import_document(pid:str,file:UploadFile=File(...),encoding:str=Form('auto')):
        raw=await file.read(docs.MAX_UPLOAD+1)
        if len(raw)>docs.MAX_UPLOAD: raise HTTPException(413,'文档最大 128MB')
        parsed=parse_file(raw,file.filename or 'novel.txt',encoding)
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            d=docs.import_document(store,db,pid,file.filename or 'novel.txt',raw,encoding,parsed)
            engine.create_job(db,pid,d['id']); return d

    @app.get('/api/projects/{pid}/documents/{did}/text')
    def document_text(pid:str,did:str,parse_version:int|None=None,chapter:int|None=None,start:int|None=None,end:int|None=None):
        with store.db() as db:
            d=docs.get_document(store,db,pid,did,parse_version,True); text=d['_text']; c=None
            if chapter is not None:
                c=next((v for v in d['chapters'] if v['index']==chapter),None)
                if not c: raise HTTPException(404,'章节不存在')
            lo=c['start'] if c else 0; hi=c['end'] if c else len(text)
            start=lo if start is None else start; end=hi if end is None else end
            if not lo<=start<=end<=hi: raise HTTPException(422,'正文范围超出指定章节或文档')
            return {'text':text[start:end],'start':start,'end':end,**({'chapter':chapter,'title':c['title']} if c else {})}

    @app.get('/api/projects/{pid}/documents/{did}/search')
    def search_document(pid:str,did:str,q:str,parse_version:int|None=None):
        if not 1<=len(q)<=200: raise HTTPException(422,'搜索词需要 1 至 200 个字符')
        with store.db() as db:
            d=docs.get_document(store,db,pid,did,parse_version,True); text=d['_text']; matches=[]; total=0; offset=0; chapter_index=0
            while True:
                start=text.find(q,offset)
                if start<0: break
                total+=1
                while chapter_index+1<len(d['chapters']) and d['chapters'][chapter_index+1]['start']<=start: chapter_index+=1
                if len(matches)<1000: matches.append({'start':start,'end':start+len(q),'chapter':d['chapters'][chapter_index]['index'] if d['chapters'] else None})
                offset=start+max(1,len(q))
            return {'matches':matches,'total':total,'truncated':total>len(matches)}

    @app.post('/api/projects/{pid}/documents/{did}/reparse')
    def reparse(pid:str,did:str):
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE'); docs.get_document(store,db,pid,did)
            row=db.execute('SELECT * FROM documents WHERE id=?',(did,)).fetchone()
            raw=(store.root/'files'/row['file_id']).read_bytes()
            text,chapters,warnings,encoding=parse_file(raw,row['title'],row['encoding'])
            d=docs.save_parse(store,db,pid,did,text,chapters,warnings)
            return changed_document(db,pid,d)

    @app.put('/api/projects/{pid}/documents/{did}/chapters')
    def split_chapters(pid:str,did:str,body:dict):
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE'); d=docs.get_document(store,db,pid,did,include_text=True)
            if body.get('parse_version')!=d['parse_version']: raise HTTPException(409,'解析版本已变化，请刷新后校正')
            chapters=body.get('chapters')
            if not isinstance(chapters,list) or any(not isinstance(v,dict) for v in chapters): raise HTTPException(422,'章节格式无效')
            chapters=docs.chapter_ranges(chapters,d['char_count'])
            d=docs.save_parse(store,db,pid,did,d['_text'],chapters,[w for w in d['warnings'] if not w.startswith('未识别章节标题')])
            return changed_document(db,pid,d)

    @app.get('/api/projects/{pid}/graph')
    def graph(pid:str,layer:str='adaptation',at:int|None=None):
        if layer not in ('original','adaptation') or at is not None and at<1: raise HTTPException(422,'图谱视角或时间范围无效')
        with store.db() as db: return gs.project_graph(store,db,pid,layer,at)

    @app.patch('/api/projects/{pid}/graph')
    def edit_graph(pid:str,body:dict):
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            return gs.apply_ops(store,db,pid,body.get('expected_revision'),body.get('operations'))

    @app.get('/api/projects/{pid}/graph/history')
    def history(pid:str):
        with store.db() as db:
            store.project(db,pid)
            return [dict(r) for r in db.execute('SELECT revision,created,summary FROM graph_history WHERE project_id=? ORDER BY revision DESC',(pid,))]

    @app.post('/api/projects/{pid}/graph/restore')
    def restore(pid:str,body:dict):
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE'); revision,_=gs.load(store,db,pid)
            if revision!=body.get('expected_revision'): raise HTTPException(409,'图谱已更新，请刷新后恢复')
            row=db.execute('SELECT content FROM graph_history WHERE project_id=? AND revision=?',(pid,body.get('revision'))).fetchone()
            if not row: raise HTTPException(404,'图谱历史版本不存在')
            state=json.loads(row['content'])
            target=state['adaptation'] if state['adaptation'] is not None else state['original']
            node_ids={n['id'] for n in target['nodes']}; pairs={(n['id'],s['id']) for n in target['nodes'] for s in n['states']}
            current=gs.project_graph(store,db,pid)
            for n in current['nodes']:
                for s in n['states']:
                    if any(a.get('valid') for a in s['assets']) and (n['id'],s['id']) not in pairs: raise HTTPException(409,'历史恢复会移除后续已确认资产的实体或状态；请先处理关联资产')
            for asset in db.execute("SELECT id FROM records WHERE project_id=? AND kind='asset'",(pid,)).fetchall():
                content=store.get(db,pid,asset['id'])['content']; entity=content.get('entity_id'); state_id=content.get('state_id')
                if entity and (entity not in node_ids or state_id and (entity,state_id) not in pairs): raise HTTPException(409,'历史恢复会移除后续资产记录关联的实体或状态；请先处理关联资产')
            gs.publish(store,db,pid,state,'恢复历史版本 '+str(body['revision']))
            # Active jobs must not silently undo a deliberate restore.
            db.execute("UPDATE graph_jobs SET status='superseded',error='图谱已由人工恢复历史版本' WHERE project_id=? AND status IN ('queued','running','waiting_config','paused','interrupted')",(pid,))
            db.execute("UPDATE graph_outline SET status='restored',due=0,generation=generation+1 WHERE project_id=?",(pid,))
            return gs.project_graph(store,db,pid)

    @app.get('/api/projects/{pid}/graph/entities/{entity_id}')
    def entity(pid:str,entity_id:str,layer:str='adaptation',at:int|None=None):
        g=graph(pid,layer,at); n=next((v for v in g['nodes'] if v['id']==entity_id),None)
        if not n: raise HTTPException(404,'实体未出现或不属于当前图谱视角')
        return n

    @app.post('/api/projects/{pid}/graph/evidence')
    def locate_evidence(pid:str,body:dict):
        with store.db() as db:
            gs.validate_evidence(store,db,pid,[body])
            if body.get('source_kind')=='outline':
                r=store.get(db,pid,body['record_id'],body['record_version']); text=outline_text(r['content']); title=r['title']
            else:
                d=docs.get_document(store,db,pid,body['document_id'],body['parse_version'],True); text=d['_text']; title=d['title']
            start=max(0,body['start']-180); end=min(len(text),body['end']+180)
            return {'text':text[start:end],'start':start,'end':end,'title':title,'chapter':body.get('chapter'),'quote_start':body['start'],'quote_end':body['end']}

    @app.get('/api/projects/{pid}/graph/context')
    def context(pid:str,entity_id:str,layer:str='adaptation',at:int|None=None):
        g=graph(pid,layer,at)
        if entity_id not in {n['id'] for n in g['nodes']}: raise HTTPException(404,'实体未出现或不属于当前图谱视角')
        edges=[e for e in g['edges'] if entity_id in (e['source'],e['target'])]; ids={entity_id}|{e['source'] for e in edges}|{e['target'] for e in edges}
        g['nodes']=[n for n in g['nodes'] if n['id'] in ids]; g['edges']=edges
        g['evidence']=[v for n in g['nodes'] for v in n['evidence']]+[v for e in edges for v in e['evidence']]
        return g

    @app.get('/api/projects/{pid}/graph/jobs')
    def jobs(pid:str):
        with store.db() as db:
            store.project(db,pid)
            return [public_job(row) for row in db.execute('SELECT * FROM graph_jobs WHERE project_id=? ORDER BY created DESC',(pid,))]

    @app.post('/api/projects/{pid}/graph/jobs')
    def create_job(pid:str,body:dict):
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            return engine.create_job(db,pid,body.get('document_id')) if body.get('document_id') else (_ for _ in ()).throw(HTTPException(422,'请选择源文档'))

    @app.post('/api/projects/{pid}/graph/jobs/{jid}/{action}')
    def control_job(pid:str,jid:str,action:str):
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE'); row=job(db,pid,jid)
            allowed={'pause':{'queued','running','waiting_config','waiting_ocr'},'resume':{'paused','interrupted','waiting_config','waiting_ocr'},'cancel':{'queued','running','waiting_config','waiting_ocr','paused','interrupted','failed'},'retry':{'failed','cancelled','interrupted'}}
            if action not in allowed: raise HTTPException(404,'未知任务操作')
            if row['status'] not in allowed[action]: raise HTTPException(409,'当前任务状态不能执行此操作')
            if action in ('resume','retry'):
                if row['document_id'] and docs.get_document(store,db,pid,row['document_id'])['parse_version']!=row['parse_version']: raise HTTPException(409,'解析版本已变化，请新建任务')
                if row['kind']=='outline':
                    selected=selection(db,pid)
                    if selected['record_id']!=row['record_id'] or selected['version']!=row['record_version']: raise HTTPException(409,'当前细纲版本已变化，请重新选择')
                db.execute("UPDATE graph_units SET status='queued',attempts=0,error=NULL WHERE job_id=? AND status IN ('failed','running')",(jid,))
            status='paused' if action=='pause' else 'cancelled' if action=='cancel' else 'queued' if engine.config(db,'parse' if row['kind']=='parse' else 'text') else 'waiting_ocr' if row['kind']=='parse' else 'waiting_config'
            db.execute('UPDATE graph_jobs SET status=?,error=NULL,updated=? WHERE id=?',(status,now(),jid))
            return public_job(job(db,pid,jid))

    @app.get('/api/projects/{pid}/graph/outline')
    def get_outline(pid:str):
        with store.db() as db: return selection(db,pid)

    @app.put('/api/projects/{pid}/graph/outline')
    def choose_outline(pid:str,body:dict):
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE'); store.project(db,pid)
            rid=body.get('record_id'); version=body.get('version')
            previous=db.execute('SELECT generation FROM graph_outline WHERE project_id=?',(pid,)).fetchone(); generation=(previous['generation'] if previous else 0)+1
            if rid is not None:
                r=store.get(db,pid,rid)
                if r['kind']!='outline' or r['source']=='mock': raise HTTPException(422,'请选择正式细纲')
                if not is_primary(r):raise HTTPException(422,'请先采用有效细纲，候选或拒绝结果不能更新正式图谱')
                if r['version']!=version: raise HTTPException(409,'细纲版本已改变，请刷新后选择')
                outline_chapters(outline_text(r['content']))
            elif version is not None: raise HTTPException(422,'清空细纲时版本应为空')
            db.execute('INSERT INTO graph_outline VALUES(?,?,?,?,?,?) ON CONFLICT(project_id) DO UPDATE SET record_id=excluded.record_id,version=excluded.version,status=excluded.status,due=excluded.due,generation=excluded.generation',(pid,rid,version,'pending' if rid else 'cleared',time.time(),generation))
            db.execute("UPDATE graph_jobs SET status='superseded',error='当前细纲选择已改变' WHERE project_id=? AND kind='outline' AND status IN ('queued','running','waiting_config','paused','interrupted')",(pid,))
            if rid is not None:
                engine.create_job(db,pid,record=r,generation=generation)
                db.execute("UPDATE graph_outline SET status='extracting' WHERE project_id=?",(pid,))
            if rid is None:
                _,state=gs.load(store,db,pid); state['adaptation']={'nodes':[],'edges':[]}; state['outline_id']=None; state['outline_version']=None; state['adaptation_cleared']=True
                gs.publish(store,db,pid,state,'明确清空当前细纲')
            return selection(db,pid)

    def target_state(db,pid,entity_id,state_id):
        revision,state=gs.load(store,db,pid)
        if state['adaptation'] is None: state['adaptation']=copy.deepcopy(state['original'])
        n=next((n for n in state['adaptation']['nodes'] if n['id']==entity_id and n['id'] not in state['suppressed_nodes']),None)
        if not n: raise HTTPException(404,'图谱实体不存在')
        s=next((s for s in n['states'] if s['id']==state_id),None)
        if not s: raise HTTPException(404,'图谱状态不存在')
        return state,n,s

    @app.post('/api/projects/{pid}/graph/assets/draft')
    def draft_asset(pid:str,body:dict):
        with store.db() as db:
            state,n,s=target_state(db,pid,body.get('entity_id'),body.get('state_id'))
            style=db.execute("SELECT record_id,version FROM selections WHERE project_id=? AND kind='style'",(pid,)).fetchone()
            content={'entity_id':n['id'],'state_id':s['id'],'category':{'PERSON':'人物','LOCATION':'场景','OBJECT':'物件'}.get(n['type'],'其他'),'characters':n['label'] if n['type']=='PERSON' else '', 'scene':n['label'] if n['type']=='LOCATION' else '', 'state':s['label'],'description':s['attributes'].get('description',s['attributes'].get('描述','')),'visual_fields':{k:v for k,v in s['attributes'].items() if k in gs.VISUAL},'graph_revision':gs.load(store,db,pid)[0]}
            if style:
                chosen=store.get(db,pid,style['record_id'],style['version']); content['style_reference']={**dict(style),'source':chosen['source']}
            return store.add(db,pid,'asset',n['label']+' · '+s['label'],content,'manual')

    @app.post('/api/projects/{pid}/graph/assets/confirm')
    def confirm_asset(pid:str,body:dict):
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE'); state,n,s=target_state(db,pid,body.get('entity_id'),body.get('state_id'))
            r=store.get(db,pid,body.get('asset_id')); version=body.get('version'); role=body.get('role')
            if r['kind']!='asset' or r['adopted']!=version: raise HTTPException(409,'请采用并核验资产当前精确版本')
            r=store.get(db,pid,r['id'],version)
            if r['source']=='mock' or r['review']!='approved' or not r['content'].get('url'): raise HTTPException(409,'资产当前精确版本必须具有图片并通过正式审核')
            if not isinstance(role,str) or not role.strip(): raise HTTPException(422,'资产用途不能为空')
            rebind=body.get('rebind',False)
            if type(rebind) is not bool: raise HTTPException(422,'重新绑定选项格式无效')
            prior=[]; override=False
            for other in state['adaptation']['nodes']:
                for os in other['states']:
                    refs=[a for a in os.get('assets',[]) if a['asset_id']==r['id']]
                    for ref in refs:
                        prior.extend(ref.get('_binding_history',[]))
                        prior.append({'entity_id':other['id'],'state_id':os['id'],'version':ref['version']})
                        if (other['id'],os['id'])==(n['id'],s['id']) and ref['version']==version and ref.get('_binding_override'): override=True
                    if (other['id'],os['id'])!=(n['id'],s['id']) and refs and not rebind: raise HTTPException(409,'资产已关联其他实体状态；重新绑定需明确确认')
            mismatch=r['content'].get('entity_id') not in [None,n['id'],*n.get('original_ids',[])] or r['content'].get('state_id') not in (None,s['id'])
            if mismatch and not (rebind or override): raise HTTPException(409,'资产已绑定其他实体或状态；重新绑定需明确确认')
            if rebind:
                if r['content'].get('entity_id'): prior.append({'entity_id':r['content']['entity_id'],'state_id':r['content'].get('state_id'),'version':version,'source':'immutable_asset_version'})
                for other in state['adaptation']['nodes']:
                    for os in other['states']:
                        os['assets']=[a for a in os.get('assets',[]) if a['asset_id']!=r['id']]
                        if os is not s:
                            for key,ref in list(os.get('_visual_sources',{}).items()):
                                if ref['asset_id']==r['id']:
                                    os['attributes'].pop(key,None); os.get('_visual',{}).pop(key,None); os['_visual_sources'].pop(key,None)
            candidate={'asset_id':r['id'],'version':version,'role':role,'valid':True,'_binding_override':rebind or override,'_binding_history':prior}; s['assets']=[a for a in s.get('assets',[]) if a['asset_id']!=r['id']]
            if role=='main':
                for a in s['assets']:
                    if a['role']=='main': a['role']='supplemental'
            s['assets'].append(candidate); gs.refresh_assets(store,db,pid,n)
            if not candidate['valid']: raise HTTPException(409,candidate['reason'])
            visual={k:v for k,v in r['content'].get('visual_fields',{}).items() if k in gs.VISUAL and isinstance(v,str)}
            for k in gs.VISUAL:
                if isinstance(r['content'].get(k),str): visual[k]=r['content'][k]
            s['attributes'].update(visual); s['_visual']={**s.get('_visual',{}),**visual}
            s['_visual_sources']={**s.get('_visual_sources',{}),**{k:{'asset_id':r['id'],'version':version} for k in visual}}
            # Confirmation locks only visual state fields, never narrative identity.
            gs.publish(store,db,pid,state,'确认资产精确版本并回写视觉字段')
            return gs.project_graph(store,db,pid)
    return engine
