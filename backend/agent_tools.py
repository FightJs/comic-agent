"""Host-owned read capabilities over a frozen project snapshot."""
import json
from fastapi import HTTPException
from .graph_documents import get_document,parse_coverage
from .novel_memory import freeze_summaries,read_summaries
from . import graph_store, preferences, frame_plan
from .store import is_primary
from .skills import frozen_skills,read_resource,resolve_cross_reference


def freeze_context(store,db,pid,refs=(),stage=None):
    store.project(db,pid)
    revision,_=graph_store.load(store,db,pid)
    frozen={
        'records':{r['id']:{'version':r['version'],'kind':r['kind'],'title':r['title']} for r in db.execute('SELECT id,version,kind,title FROM records WHERE project_id=?',(pid,))},
        'documents':{r['id']:r['parse_version'] for r in db.execute('SELECT id,parse_version FROM documents WHERE project_id=?',(pid,))},
        'graph_revision':revision,
        'skills':frozen_skills(store,db,pid,stage),
        'preferences':preferences.read(store,db,pid) if stage!='setup' else {'revision':0,'text':''},
    }
    if stage in ('style','asset'):
        choice=db.execute("SELECT record_id,version FROM selections WHERE project_id=? AND kind='style'",(pid,)).fetchone()
        frozen['image_style_selection']=dict(choice) if choice else None
    explicit_documents=set()
    for ref in refs:
        record=store.get(db,pid,ref['id'],ref['version'])
        frozen['records'][ref['id']]={'version':record['version'],'kind':record['kind'],'title':record['title']}
        if record['kind']=='original' and record['content'].get('document_id') and type(record['content'].get('parse_version')) is int:
            doc=get_document(store,db,pid,record['content']['document_id'],record['content']['parse_version'])
            frozen['documents'][doc['id']]=doc['parse_version']
            explicit_documents.add(doc['id'])
    frozen['frame_plan_sources']={};frozen['frame_plan_issues']=[]
    for rid,info in frozen['records'].items():
        if info['kind']!='script':continue
        head=store.get(db,pid,rid)
        if not is_primary(head):continue
        record=store.get(db,pid,rid,info['version']);content=record['content']
        if not is_primary(record) or not all(type(content.get(k)) is int and content[k]>0 for k in ('episode','panel')):
            frozen['frame_plan_issues'].append({'id':rid,'episode':content.get('episode') if type(content.get('episode')) is int and content['episode']>0 else None})
            continue
        frozen['frame_plan_sources'][rid]={'version':info['version'],'episode':content['episode'],'panel':content['panel'],'source':record['source']}
    preferred=next(iter(explicit_documents)) if len(explicit_documents)==1 else None
    if not explicit_documents:
        selected=db.execute('SELECT document_id FROM graph_source WHERE project_id=?',(pid,)).fetchone()
        if selected and selected['document_id'] in frozen['documents']:preferred=selected['document_id']
        else:preferred=next((r['id'] for r in db.execute('SELECT id FROM documents WHERE project_id=? ORDER BY created DESC,id DESC',(pid,)) if r['id'] in frozen['documents']),None)
    frozen['preferred_document']={'id':preferred,'parse_version':frozen['documents'][preferred]} if preferred else None
    frozen['novel_memory']=freeze_summaries(store,db,pid,frozen['documents'])
    return frozen


class ProjectTools:
    def __init__(self,store,pid,frozen):
        self.store,self.pid,self.frozen=store,pid,frozen
        self.calls=0

    def call(self,name,args):
        result=self._query(name,args)
        if len(json.dumps(result,ensure_ascii=False))>200000:raise HTTPException(422,'查询结果过大，请缩小范围、按具体资料编号查询或分段读取')
        return result

    def _query(self,name,args):
        self.calls+=1
        if self.calls>50: raise HTTPException(429,'运行工具额度已用完')
        if name!='project_query' or not isinstance(args,dict) or set(args)-{'action','id','query','start','limit','layer','plan'}:
            raise HTTPException(403,'工具或参数不在授权范围')
        if 'plan' in args and args.get('action')!='frame_plan':raise HTTPException(403,'此查询不接受画幅计划参数')
        action=args.get('action'); query=args.get('query',''); start=args.get('start',0); limit=args.get('limit',20)
        if not isinstance(query,str) or len(query)>(400 if action=='skill' else 200) or type(start) is not int or start<0 or type(limit) is not int or not 1<=limit<=50: raise HTTPException(422,'查询参数无效')
        with self.store.db() as db:
            self.store.project(db,self.pid)
            if action=='frame_plan':
                if 'plan' in args and args['plan'] is None:raise HTTPException(422,'plan不能为null，读取源序时请省略plan')
                return frame_plan.check(self.frozen,args.get('id'),args.get('plan'))
            if action=='skill':
                info=next((s for s in self.frozen.get('skills',[]) if s['hash']==args.get('id')),None)
                if not info:raise HTTPException(403,'Skill不在本次运行的固定流程中')
                if query=='@files':return {'hash':info['hash'],'files':info['files'][start:start+limit],'total':len(info['files'])}
                crossed=resolve_cross_reference(self.frozen.get('skills',[]),info,query)
                if crossed:
                    target,path=crossed
                    return {**read_resource(db,target['hash'],path,start),'referenced_from':info['hash']}
                return read_resource(db,info['hash'],query or info['entrypoint'],start)
            if action=='catalog':
                records=[{'id':rid,**v} for rid,v in self.frozen['records'].items() if not query or query in v['title'] or query in v['kind']]
                return {'records':records[start:start+limit],'total':len(records),'documents':self.frozen['documents'],'document_coverage':[parse_coverage(get_document(self.store,db,self.pid,did,version)) for did,version in self.frozen['documents'].items()],'preferred_document':self.frozen.get('preferred_document'),'novel_memory':{did:self.frozen.get('novel_memory',{}).get(did,{'status':'not_frozen'}) for did in self.frozen['documents']},'graph_revision':self.frozen['graph_revision'],'skills':[{**{k:v for k,v in s.items() if k!='files'},'file_count':len(s['files'])} for s in self.frozen.get('skills',[])]}
            if action=='novel_summary':
                return read_summaries(self.store,db,self.pid,self.frozen,args.get('id'),query,start,limit)
            if action=='record':
                ref=self.frozen['records'].get(args.get('id'))
                if not ref: raise HTTPException(404,'资料不在本次项目快照中')
                r=self.store.get(db,self.pid,args['id'],ref['version'])
                text=json.dumps(r['content'],ensure_ascii=False)
                # Large originals must be queried by source range, not silently truncated.
                if len(text)>30000: return {'id':r['id'],'version':r['version'],'kind':r['kind'],'title':r['title'],'source':r['source'],'text':text[start:start+10000],'start':start,'total_chars':len(text),'partial':True}
                return r
            if action in ('search_novel','source'):
                did=args.get('id')
                ids=[did] if did in self.frozen['documents'] else list(self.frozen['documents']) if did is None else []
                if not ids: raise HTTPException(404,'原著不在本次项目快照中')
                if action=='source' and did is None: raise HTTPException(422,'正文读取需要文档编号')
                matches=[];searched=[]
                documents=[get_document(self.store,db,self.pid,did,self.frozen['documents'][did],True) for did in ids]
                for doc in documents:
                    did=doc['id'];searched.append(did)
                    text=doc['_text']
                    record_id=db.execute('SELECT record_id FROM documents WHERE id=?',(did,)).fetchone()[0]
                    origin=self.store.get(db,self.pid,record_id)['source']
                    if action=='source':
                        lo=min(start,len(text));end=min(len(text),lo+10000)
                        chapters=[c for c in doc['chapters'] if c['start']<end and c['end']>lo]
                        return {'source':origin,'coverage':parse_coverage(doc),'document_id':did,'parse_version':doc['parse_version'],'start':lo,'end':end,'requested_start':start,'text':text[lo:end],'total_chars':len(text),'chapters':chapters[:50],'total_chapters':doc['chapter_count'],'chapters_truncated':len(chapters)>50}
                    if not query.strip(): raise HTTPException(422,'原著检索需要关键词')
                    offset=start
                    while len(matches)<limit:
                        pos=text.find(query,offset)
                        if pos<0: break
                        lo=max(0,pos-120); hi=min(len(text),pos+len(query)+200)
                        chapter=next((c['index'] for c in doc['chapters'] if c['start']<=pos<c['end']),None)
                        matches.append({'source':origin,'document_id':did,'parse_version':doc['parse_version'],'chapter':chapter,'start':lo,'end':hi,'quote':text[lo:hi],'match_start':pos,'match_end':pos+len(query)})
                        offset=pos+max(1,len(query))
                    if len(matches)>=limit: break
                return {'source':'mock' if any(m['source']=='mock' for m in matches) else 'original','matches':matches,'limit_reached':len(matches)==limit,'coverage':[parse_coverage(doc) for doc in documents],'searched_documents':searched,'search_start':start}
            if action=='graph':
                row=db.execute('SELECT content FROM graph_history WHERE project_id=? AND revision=?',(self.pid,self.frozen['graph_revision'])).fetchone()
                graph=json.loads(row['content']) if row else graph_store.empty()
                layer=args.get('layer','adaptation')
                if layer not in ('original','adaptation'):raise HTTPException(422,'图谱视角无效')
                view=graph['adaptation'] if layer=='adaptation' and graph['adaptation'] is not None else graph['original']
                nodes=view['nodes']
                nodes=[n for n in nodes if (not args.get('id') or n['id']==args['id']) and (not query or query in json.dumps(n,ensure_ascii=False))]
                selected=nodes[start:start+limit]; ids={n['id'] for n in selected}
                return {'revision':self.frozen['graph_revision'],'nodes':selected,'total':len(nodes),'edges':[e for e in view['edges'] if e['source'] in ids or e['target'] in ids][:100]}
        raise HTTPException(403,'该操作未授权')
