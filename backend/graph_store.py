"""Project scoped revisioned graph snapshots and conservative temporal projection."""
import copy
import json
from fastapi import HTTPException
from .store import uid, now, dump
from .graph_documents import get_document

TYPES={'PERSON','LOCATION','ORGANIZATION','OBJECT','OTHER'}
VISUAL={'appearance','hair','face','clothing','colors','body','age','description','外貌','发型','头发','面部','服装','颜色','体型','年龄','外观','描述'}


def schema(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS graph_heads(project_id TEXT PRIMARY KEY,revision INTEGER,content TEXT);
    CREATE TABLE IF NOT EXISTS graph_history(project_id TEXT,revision INTEGER,created TEXT,summary TEXT,content TEXT,PRIMARY KEY(project_id,revision));
    CREATE TABLE IF NOT EXISTS graph_outline(project_id TEXT PRIMARY KEY,record_id TEXT,version INTEGER,status TEXT,due REAL,generation INTEGER);
    ''')


def empty():
    return {'original':{'nodes':[],'edges':[]},'adaptation':None,'conflicts':[],'suppressed_nodes':[],'suppressed_edges':[],'outline_id':None,'outline_version':None}


def load(store,db,pid):
    store.project(db,pid)
    row=db.execute('SELECT * FROM graph_heads WHERE project_id=?',(pid,)).fetchone()
    return (row['revision'],json.loads(row['content'])) if row else (0,empty())


def publish(store,db,pid,state,summary):
    revision,_=load(store,db,pid); revision+=1
    db.execute('INSERT INTO graph_heads VALUES(?,?,?) ON CONFLICT(project_id) DO UPDATE SET revision=excluded.revision,content=excluded.content',(pid,revision,dump(state)))
    db.execute('INSERT INTO graph_history VALUES(?,?,?,?,?)',(pid,revision,now(),summary,dump(state)))
    return revision


def validate_evidence(store,db,pid,items,source=None):
    if not isinstance(items,list): raise HTTPException(422,'证据必须为列表')
    output=[]
    for item in items:
        if not isinstance(item,dict): raise HTTPException(422,'证据格式无效')
        start=item.get('start'); end=item.get('end'); quote=item.get('quote')
        if type(start) is not int or type(end) is not int or not isinstance(quote,str) or not quote or start<0 or end<=start: raise HTTPException(422,'证据范围无效')
        if item.get('source_kind')=='outline':
            record=store.get(db,pid,item.get('record_id'),item.get('record_version'))
            if record['kind']!='outline' or record['source']=='mock': raise HTTPException(422,'细纲证据来源无效')
            # The canonical text is stored in immutable job payload, not browser HTML offsets.
            from .graph_engine import outline_text,outline_chapters
            text=outline_text(record['content'])
            if text[start:end]!=quote: raise HTTPException(422,'细纲引用与指定版本正文不一致')
            chapter=next((c for c in outline_chapters(text) if c['start']<=start<end<=c['end']),None)
            if not chapter or chapter['index']!=item.get('chapter'): raise HTTPException(422,'细纲证据不属于指定话号')
        else:
            doc=get_document(store,db,pid,item.get('document_id'),item.get('parse_version'),True)
            if doc['_text'][start:end]!=quote: raise HTTPException(422,'原著引用与指定解析版本不一致')
            chapter=next((c for c in doc['chapters'] if c['start']<=start<end<=c['end']),None)
            if not chapter or chapter['index']!=item.get('chapter'): raise HTTPException(422,'证据不属于指定章节')
        output.append(copy.deepcopy(item))
    return output


def node(value,manual=False):
    if not isinstance(value,dict) or value.get('type','OTHER') not in TYPES or not isinstance(value.get('label'),str) or not value['label'].strip(): raise HTTPException(422,'实体名称和类型无效')
    n={'id':value.get('id') or uid(),'label':value['label'],'type':value.get('type','OTHER'),'aliases':[],'summary':'','important':False,'attributes':{},'states':[],'evidence':[],'known_from':None,'source':'manual' if manual else 'original','locked_fields':[]}
    n.update(copy.deepcopy(value))
    if not isinstance(n['id'],str) or not n['id'] or not isinstance(n['aliases'],list) or any(not isinstance(a,str) for a in n['aliases']) or not isinstance(n['attributes'],dict) or any(not isinstance(v,str) for v in n['attributes'].values()) or not isinstance(n['states'],list): raise HTTPException(422,'实体字段格式无效')
    if n['known_from'] is not None and (type(n['known_from']) is not int or n['known_from']<1): raise HTTPException(422,'首次出现须为正整数或空')
    states=[]
    for s in n['states']:
        if not isinstance(s,dict) or not isinstance(s.get('label'),str): raise HTTPException(422,'状态格式无效')
        states.append({'id':s.get('id') or uid(),'attributes':{},'known_from':None,'assets':[],**s})
    n['states']=states
    if manual and type(n['known_from']) is int and '_known' not in n:
        n['_known']={'label':n['known_from']}
        n['_history']={'label':[{'at':n['known_from'],'value':n['label']}]}
    if manual: n['source']='manual'; n['locked_fields']=sorted(set(n.get('locked_fields',[]))|set(value)-{'id','locked_fields'})
    return n


def edge(value,manual=False):
    if not isinstance(value,dict) or any(not isinstance(value.get(k),str) or not value[k] for k in ('source','target','relation')): raise HTTPException(422,'关系端点或名称无效')
    e={'id':value.get('id') or uid(),'inferred':False,'reason':'','evidence':[],'known_from':None,'story_time':'','origin':'manual' if manual else 'original','locked_fields':[]}
    e.update(copy.deepcopy(value))
    if e['inferred'] and not e['reason']: raise HTTPException(422,'推断关系必须填写推断依据')
    if manual: e['origin']='manual'; e['locked_fields']=sorted(set(value)-{'id','locked_fields'})
    return e


def refresh_assets(store,db,pid,n):
    choice=db.execute("SELECT record_id,version FROM selections WHERE project_id=? AND kind='style'",(pid,)).fetchone()
    style=dict(choice) if choice else None
    for s in n['states']:
        for a in s.get('assets',[]):
            reason=None
            try:
                r=store.get(db,pid,a['asset_id']); snap=store.get(db,pid,a['asset_id'],a['version'])
                selected=store.get(db,pid,style['record_id']) if style else None
                ref=snap['content'].get('style_reference',{})
                if a.get('_needs_reconfirm'): reason='实体合并后需重新确认资产与状态'
                elif r['adopted']!=a['version']: reason='资产版本已变化或未采用精确版本'
                elif snap['review']!='approved' or snap['source']=='mock': reason='资产精确版本尚未通过正式审核'
                elif not selected or selected['version']!=style['version'] or selected['source']=='mock' or selected['review']!='approved': reason='当前画风未通过有效审核'
                elif {k:ref.get(k) for k in ('record_id','version')}!=style: reason='资产绑定画风已失效'
                a['url']=snap['content'].get('url')
            except HTTPException: reason='关联资产或画风不存在'
            a['valid']=reason is None
            if reason: a['reason']=reason
            else: a.pop('reason',None)


def temporal_item(item,at):
    return at is None or type(item.get('known_from')) is int and item['known_from']<=at


def project_graph(store,db,pid,layer='adaptation',at=None):
    revision,state=load(store,db,pid)
    raw=state['original'] if layer=='original' else state['adaptation'] if state['adaptation'] is not None else state['original']
    # No guessed source chapter -> episode conversion: source fallback has no episode view.
    if layer=='adaptation' and state['adaptation'] is None and at is not None: raw={'nodes':[],'edges':[]}
    if at is not None:
        raw=copy.deepcopy(raw)
        known_ids={n['id'] for n in raw['nodes']}
        for merge in reversed(raw.get('_merged_nodes',[])):
            if at<merge['disclosed'] and merge['node']['id'] not in known_ids:
                raw['nodes'].append(merge['node']); known_ids.add(merge['node']['id'])
        for relation in raw['edges']:
            for prior in reversed(relation.get('_endpoint_history',[])):
                if at<prior['at']: relation['source']=prior['source']; relation['target']=prior['target']
    nodes=[]
    for value in raw['nodes']:
        if value['id'] in state['suppressed_nodes'] and layer!='original': continue
        if not temporal_item(value,at): continue
        n=copy.deepcopy(value)
        if at is not None:
            clocks=n.get('_known',{})
            labels=[v for v in n.get('_history',{}).get('label',[]) if type(v.get('at')) is int and v['at']<=at]
            if type(clocks.get('label')) is not int or clocks['label']>at:
                if labels: n['label']=max(labels,key=lambda v:v['at'])['value']
                else: continue
            if type(clocks.get('important')) is not int or clocks['important']>at: n['important']=False
            n['aliases']=[a for a in n['aliases'] if type(clocks.get('aliases',{}).get(a)) is int and clocks['aliases'][a]<=at]
            n['attributes']={k:v for k,v in n['attributes'].items() if type(clocks.get('attributes',{}).get(k)) is int and clocks['attributes'][k]<=at}
            if not (type(clocks.get('summary')) is int and clocks['summary']<=at): n['summary']=''
            history=n.get('_history',{})
            summaries=[f for f in history.get('summary',[]) if type(f.get('at')) is int and f['at']<=at]
            if summaries: n['summary']=max(summaries,key=lambda f:f['at'])['value']
            for key,values in history.get('attributes',{}).items():
                values=[f for f in values if type(f.get('at')) is int and f['at']<=at]
                if values: n['attributes'][key]=max(values,key=lambda f:f['at'])['value']
            n['evidence']=[e for e in n['evidence'] if type(e.get('_known_from',e.get('chapter') if layer=='original' else None)) is int and e.get('_known_from',e.get('chapter'))<=at]
            n['states']=[s for s in n['states'] if temporal_item(s,at)]
            for s in n['states']:
                known=s.get('_known',{})
                s['attributes']={k:v for k,v in s.get('attributes',{}).items() if type(known.get(k)) is int and known[k]<=at}
                for key,facts in s.get('_attribute_history',{}).items():
                    facts=[f for f in facts if f['at']<=at]
                    if facts: s['attributes'][key]=max(facts,key=lambda f:f['at'])['value']
                s['assets']=[] # assets have no safe chapter/episode provenance
        refresh_assets(store,db,pid,n)
        nodes.append(n)
    ids={n['id'] for n in nodes}; edges=[]
    for e in raw['edges']:
        if e['source'] not in ids or e['target'] not in ids or not temporal_item(e,at) or layer!='original' and e['id'] in state['suppressed_edges']: continue
        e=copy.deepcopy(e)
        if at is not None:
            e['evidence']=[v for v in e['evidence'] if type(v.get('_known_from',v.get('chapter') if layer=='original' else None)) is int and v.get('_known_from',v.get('chapter'))<=at]
            # Narrative descriptions can mention later reveals even when relation starts earlier.
            if e.get('_reason_known',e.get('known_from',10**12))>at: e['reason']=''; e['story_time']=''
        edges.append(e)
    def public(value):
        if isinstance(value,dict): return {k:public(v) for k,v in value.items() if not k.startswith('_')}
        if isinstance(value,list): return [public(v) for v in value]
        return value
    return public({'revision':revision,'status':'ready' if nodes or edges else 'empty','nodes':nodes,'edges':edges,'conflicts':state['conflicts'] if at is None else [],'outline_id':state['outline_id'],'outline_version':state['outline_version']})


def apply_ops(store,db,pid,expected,operations):
    revision,state=load(store,db,pid)
    if revision!=expected: raise HTTPException(409,'图谱已更新，请刷新后比较修改')
    if not isinstance(operations,list) or len(operations)>1000: raise HTTPException(422,'操作列表无效')
    if state['adaptation'] is None: state['adaptation']=copy.deepcopy(state['original'])
    graph=state['adaptation']
    def find(kind,id):
        result=next((v for v in graph[kind] if v['id']==id),None)
        if not result: raise HTTPException(404,'图谱实体或关系不存在')
        return result
    for op in operations:
        kind=op.get('op')
        if kind=='add_node':
            n=node(op.get('node'),True)
            if any(x['id']==n['id'] for x in graph['nodes']): raise HTTPException(409,'实体标识已存在')
            n['evidence']=validate_evidence(store,db,pid,n['evidence']); graph['nodes'].append(n)
        elif kind=='add_edge':
            e=edge(op.get('edge'),True); find('nodes',e['source']); find('nodes',e['target'])
            if any(x['id']==e['id'] for x in graph['edges']): raise HTTPException(409,'关系标识已存在')
            e['evidence']=validate_evidence(store,db,pid,e['evidence']); graph['edges'].append(e)
        elif kind in ('update_node','update_edge'):
            field='nodes' if kind=='update_node' else 'edges'; id=op.get('node_id' if field=='nodes' else 'edge_id'); old=find(field,id); patch=op.get('patch')
            if not isinstance(patch,dict) or any(k.startswith('_') or k in ('id','source','locked_fields') if field=='nodes' else k.startswith('_') or k in ('id','locked_fields') for k in patch): raise HTTPException(422,'不可修改内部或身份字段')
            updated=(node if field=='nodes' else edge)({**old,**patch})
            if 'evidence' in patch: updated['evidence']=validate_evidence(store,db,pid,patch['evidence'])
            if field=='edges': find('nodes',updated['source']); find('nodes',updated['target'])
            updated['locked_fields']=sorted(set(old['locked_fields'])|set(patch))
            for field in patch:
                updated.get('_known',{}).pop(field,None)
                if field!='label': updated.get('_history',{}).pop(field,None)
            old.clear(); old.update(updated)
        elif kind in ('delete_node','delete_edge'):
            field='nodes' if kind=='delete_node' else 'edges'; id=op.get('node_id' if field=='nodes' else 'edge_id'); find(field,id)
            graph[field]=[x for x in graph[field] if x['id']!=id]
            state['suppressed_nodes' if field=='nodes' else 'suppressed_edges'].append(id)
            if field=='nodes': graph['edges']=[e for e in graph['edges'] if id not in (e['source'],e['target'])]
        elif kind=='merge_nodes':
            ids=op.get('node_ids',[]); target=find('nodes',op.get('target_id'))
            if len(set(ids))<2 or target['id'] not in ids: raise HTTPException(422,'合并需至少两个实体且目标在其中')
            values=[find('nodes',id) for id in ids]
            target['original_ids']=sorted({v for n in values for v in n.get('original_ids',[n['id']])})
            target['aliases']=list(dict.fromkeys(target['aliases']+[v for n in values for v in [n['label'],*n['aliases']] if v!=target['label']]))
            for n in values:
                if n is not target:
                    target['states']+=n['states']; target['evidence']+=n['evidence']; state['suppressed_nodes'].append(n['id'])
            for merged_state in target['states']:
                for asset in merged_state.get('assets',[]): asset['_needs_reconfirm']=True
            target['locked_fields']=sorted(set(target['locked_fields'])|{'aliases','original_ids','states'})
            graph['nodes']=[n for n in graph['nodes'] if n['id'] not in ids or n is target]
            for e in graph['edges']:
                if e['source'] in ids: e['source']=target['id']
                if e['target'] in ids: e['target']=target['id']
        elif kind=='unlock':
            if bool(op.get('node_id'))==bool(op.get('edge_id')): raise HTTPException(422,'请选择单个实体或关系解锁')
            n=find('nodes' if op.get('node_id') else 'edges',op.get('node_id') or op.get('edge_id')); fields=op.get('fields',[])
            if not isinstance(fields,list): raise HTTPException(422,'解锁字段无效')
            n['locked_fields']=[x for x in n['locked_fields'] if x not in fields]
        elif kind=='resolve_conflict':
            conflict=next((c for c in state['conflicts'] if c['id']==op.get('conflict_id')),None)
            if not conflict or op.get('choice') not in ('manual','incoming'): raise HTTPException(422,'冲突或选择无效')
            if op['choice']=='incoming':
                if conflict['field']=='__presence' and conflict['incoming'] is None:
                    target=conflict['target_id']
                    graph['nodes']=[n for n in graph['nodes'] if n['id']!=target]
                    graph['edges']=[e for e in graph['edges'] if target not in (e['source'],e['target'])]
                    if target not in state['suppressed_nodes']: state['suppressed_nodes'].append(target)
                else:
                    obj=next((x for x in graph['nodes']+graph['edges'] if x['id']==conflict['target_id']),None)
                    if obj: obj[conflict['field']]=conflict['incoming']; obj['locked_fields']=[f for f in obj['locked_fields'] if f!=conflict['field']]
            state['conflicts']=[c for c in state['conflicts'] if c['id']!=conflict['id']]
        else: raise HTTPException(422,'未知图谱操作')
    publish(store,db,pid,state,'人工编辑图谱')
    return project_graph(store,db,pid)


def protected_merge(old,incoming,conflicts,source):
    """Manual fields survive model refreshes, including explicit empty values."""
    result=copy.deepcopy(incoming)
    for field in old.get('locked_fields',[]):
        if field in old:
            if incoming.get(field)!=old[field]: conflicts.append({'id':uid(),'target_id':old['id'],'field':field,'manual':old[field],'incoming':incoming.get(field),'source':source,'evidence':copy.deepcopy(incoming.get('evidence',[]))})
            result[field]=copy.deepcopy(old[field])
            result.get('_known',{}).pop(field,None); result.get('_history',{}).pop(field,None)
    result['locked_fields']=old.get('locked_fields',[])
    # Stable state links retain imported assets and visual confirmations.
    states={s['id']:s for s in old.get('states',[])}
    for s in result.get('states',[]):
        if s['id'] in states:
            s['assets']=states[s['id']].get('assets',[])
            for k,v in states[s['id']].get('_visual',{}).items(): s['attributes'][k]=v
            if states[s['id']].get('_visual'): s['_visual']=states[s['id']]['_visual']; s['_visual_sources']=states[s['id']].get('_visual_sources',{})
    return result
