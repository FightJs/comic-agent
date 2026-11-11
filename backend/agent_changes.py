"""Validated AI proposals are separate from adopted business versions."""
import copy
import html
import json
from fastapi import HTTPException
from .store import uid,now,dump,is_primary
from . import graph_store as gs
from .graph_engine import outline_text
from . import script_changes

FIELDS={
    'skeleton':{'text'},'outline':{'text'},
    'script':{'characters','scene','weather','time','shot','camera','description','dialogue','sfx','note'},
    'package':{'scene_prompt','content_prompt','position_prompt','shot_prompt','constraints','prompt'},
    'style':{'prompt','description','note'},'asset':{'prompt','description','note'},
}
PARTS=[('scene_prompt','场景提示词'),('content_prompt','内容提示词'),('position_prompt','站位提示词'),('shot_prompt','分镜'),('constraints','其他约束')]


def schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS agent_proposals(id TEXT PRIMARY KEY,project_id TEXT,run_id TEXT,title TEXT,status TEXT,source TEXT,changes TEXT,result TEXT,created TEXT)')


def get(store,db,pid,proposal_id):
    store.project(db,pid)
    row=db.execute('SELECT * FROM agent_proposals WHERE id=? AND project_id=?',(proposal_id,pid)).fetchone()
    if not row:raise HTTPException(404,'修改候选不存在')
    value=dict(row);value['changes']=json.loads(value['changes']);value['result']=json.loads(value['result']) if value['result'] else None
    return value


def propose(store,db,pid,run_id,frozen,value):
    if not isinstance(value,dict) or set(value)-{'title','changes'} or not isinstance(value.get('title'),str) or not 1<=len(value['title'].strip())<=200:raise HTTPException(422,'候选标题格式无效')
    changes=value.get('changes')
    if not isinstance(changes,list) or not 1<=len(changes)<=100 or len(dump(value))>200000:raise HTTPException(422,'修改候选范围过大或为空')
    run=db.execute('SELECT status FROM agent_runs WHERE id=? AND project_id=?',(run_id,pid)).fetchone()
    if not run or run['status']!='running':raise HTTPException(409,'当前运行不能提交候选')
    writable={r['id']:r['version'] for r in frozen.get('write_refs',[])}
    source='mock' if frozen.get('inherited_mock') or any(store.get(db,pid,rid,v)['source']=='mock' for rid,v in writable.items()) else 'ai'
    # A model reading mock content cannot launder it into a formal candidate.
    for call in db.execute('SELECT result FROM agent_tool_calls WHERE run_id=?',(run_id,)):
        if json.loads(call['result']).get('source')=='mock':source='mock'
    selection=frozen.get('text_selection')
    if selection and (len(changes)!=1 or not isinstance(changes[0],dict) or changes[0].get('target')!='record' or not isinstance(changes[0].get('id'),str) or changes[0].get('id') not in writable or not isinstance(changes[0].get('patch'),dict) or set(changes[0]['patch'])!={'text'}):raise HTTPException(403,'精确选段只能提出单一目标的替换纯文本')
    prepared=[];seen=set()
    snapshot=db.execute('SELECT content FROM graph_history WHERE project_id=? AND revision=?',(pid,frozen.get('graph_revision',0))).fetchone()
    fixed=json.loads(snapshot['content']) if snapshot else gs.empty()
    graph=fixed['adaptation'] if fixed['adaptation'] is not None else fixed['original']
    for change in changes:
        if not isinstance(change,dict) or set(change)!={'target','id','patch'} or not isinstance(change['id'],str) or not isinstance(change['patch'],dict) or not change['patch']:raise HTTPException(422,'修改项格式无效')
        target,rid,patch=change['target'],change['id'],copy.deepcopy(change['patch'])
        key=(target,rid,dump(patch.get('panel'))) if target=='script_create' else (target,rid)
        if key in seen:raise HTTPException(422,'同一对象请合并为一个修改项')
        seen.add(key)
        if target in ('script_create','script_delete'):
            prepared.append(script_changes.prepare(store,db,pid,frozen,change))
        elif target=='record':
            if rid not in writable:raise HTTPException(403,'只能修改本次会话明确附加的固定版本资料，请新建讨论选择目标')
            record=store.get(db,pid,rid,writable[rid]);kind=record['kind']
            if kind!=frozen.get('stage') or kind not in FIELDS or set(patch)-FIELDS[kind]:raise HTTPException(403,'修改字段不属于当前阶段；身份、来源、引用和审核字段不能改动')
            if any(not isinstance(v,str) or len(v)>150000 for v in patch.values()):raise HTTPException(422,'修改字段须为受限文本')
            before={k:(outline_text(record['content']) if k=='text' else record['content'].get(k,'')) for k in patch}
            if selection:
                from .text_selections import validate
                validate(record,selection)
                before={'text':selection['text']}
            prepared.append({**({'selection':selection} if selection else {}),**change,'version':record['version'],'kind':kind,'title':record['title'],'before':before,'source':record['source'],'location':{k:record['content'][k] for k in ('episode','panel','batch') if k in record['content']},'full_prompt_preserved':bool(kind=='package' and 'prompt' not in patch and (record['content'].get('prompt_mode')=='override' or record['content'].get('prompt') and not record['content'].get('prompt_mode')))})
        elif target in ('graph_node','graph_edge'):
            if frozen.get('stage')!='memory':raise HTTPException(403,'图谱修改只在理解与记忆阶段提交')
            field='nodes' if target=='graph_node' else 'edges'
            old=next((v for v in graph[field] if v['id']==rid),None)
            if not old:raise HTTPException(404,'对象不在固定版本图谱中')
            allowed={'label','type','summary','aliases','attributes','important'} if field=='nodes' else {'relation','reason','inferred','story_time'}
            if set(patch)-allowed:raise HTTPException(403,'不允许修改图谱身份、证据、资产或内部字段')
            for k,v in patch.items():
                valid=isinstance(v,bool) if k in ('important','inferred') else isinstance(v,list) and len(v)<=100 and all(isinstance(x,str) and len(x)<=200 for x in v) if k=='aliases' else isinstance(v,dict) and len(v)<=100 and all(isinstance(a,str) and isinstance(b,str) and len(a)<=200 and len(b)<=20000 for a,b in v.items()) if k=='attributes' else isinstance(v,str) and len(v)<=20000
                if not valid:raise HTTPException(422,'图谱修改字段类型或长度无效')
            (gs.node if field=='nodes' else gs.edge)({**old,**patch})
            prepared.append({**change,'revision':frozen['graph_revision'],'title':old.get('label') or old.get('relation'),'before':{k:old.get(k) for k in patch}})
        else:raise HTTPException(403,'未知修改目标')
    structural=[c for c in prepared if c['target'] in ('script_create','script_delete')]
    reserved=set();deleted=set()
    for c in structural:
        if c['target']=='script_create':
            key=(c['location']['episode'],c['patch']['panel'])
            if key in reserved:raise HTTPException(422,'新增脚本格号重复')
            reserved.add(key)
        else:
            ids={r['id'] for r in c['dependencies']}
            if deleted & ids:raise HTTPException(422,'删除影响范围重复，请分开核对')
            deleted.update(ids)
    if any(c['id'] in deleted for c in prepared if c['target']!='script_delete'):raise HTTPException(422,'不能在同一候选中删除并修改或引用同一目标')
    pid_value=uid()
    db.execute('INSERT INTO agent_proposals VALUES(?,?,?,?,?,?,?,?,?)',(pid_value,pid,run_id,value['title'],'pending',source,dump(prepared),None,now()))
    return {'id':pid_value,'status':'pending','changes':len(prepared),'message':'候选已保存，尚未改动成品；请用户核对后明确采用'}


def adopt(store,db,pid,proposal_id):
    proposal=get(store,db,pid,proposal_id)
    if proposal['status']=='adopted':return proposal['result']
    if proposal['status']!='pending':raise HTTPException(409,'此候选已被拒绝')
    run=db.execute('SELECT status FROM agent_runs WHERE id=?',(proposal['run_id'],)).fetchone()
    if not run or run['status']!='completed':raise HTTPException(409,'请等待本次回复完整完成后采用；中断或取消的运行不能直接采用')
    changes=proposal['changes'];operations=[]
    if any(c.get('selection') for c in changes):raise HTTPException(409,'精确选段须从原文编辑器核对并采用，不能按整篇正文写入')
    for change in changes:
        if change['target'] in ('script_create','script_delete'):
            script_changes.validate(store,db,pid,change)
        elif change['target']=='record':
            old=store.get(db,pid,change['id'])
            if old['version']!=change['version']:raise HTTPException(409,'原稿已有新版本，旧候选仍保留；请更新附加资料后重新提出修改候选')
        else:
            if proposal['source']=='mock':raise HTTPException(409,'模拟依赖的候选不能修改正式图谱')
            if gs.load(store,db,pid)[0]!=change['revision']:raise HTTPException(409,'图谱已有新版本，旧候选仍保留供核对')
            is_node=change['target']=='graph_node'
            operations.append({'op':'update_node' if is_node else 'update_edge','node_id' if is_node else 'edge_id':change['id'],'patch':change['patch']})
    result={'records':[],'graph':None}
    for change in changes:
        if change['target'] in ('script_create','script_delete'):
            saved=script_changes.apply(store,db,pid,proposal['run_id'],proposal['source'],change)
            result['records'].extend({'id':r['id'],'version':r['version']} for r in saved)
            continue
        if change['target']!='record':continue
        old=store.get(db,pid,change['id']);content={**old['content'],**change['patch'],'ai_run_id':proposal['run_id']}
        if change['kind'] in ('outline','skeleton'):
            text=change['patch']['text'];content.pop('text',None)
            content['html']=''.join('<p>'+html.escape(line)+'</p>' for line in text.splitlines()) or '<p></p>'
        if change['kind']=='package':
            if 'prompt' in change['patch']:content['prompt_mode']='override'
            elif old['content'].get('prompt_mode')=='override' or old['content'].get('prompt') and not old['content'].get('prompt_mode'):content['prompt_mode']='override'
            else:content['prompt']='\n\n'.join(label+'：'+content[key] for key,label in PARTS if content.get(key,'').strip())
        saved=store.save(db,pid,old['id'],old['version'],content,source=proposal['source'])
        # Adopting wording is not a production adoption decision. Keep pending,
        # rejected and replacement candidates outside the primary record stream.
        if is_primary(old):
            db.execute('UPDATE records SET adopted=? WHERE id=?',(saved['version'],saved['id']))
        result['records'].append({'id':saved['id'],'version':saved['version']})
    if operations:
        updated_graph=gs.apply_ops(store,db,pid,changes[0]['revision'],operations)
        result['graph']={'revision':updated_graph['revision']}
        db.execute('UPDATE graph_history SET summary=? WHERE project_id=? AND revision=?',('采用AI修改候选：'+proposal['title'],pid,result['graph']['revision']))
    db.execute("UPDATE agent_proposals SET status='adopted',result=? WHERE id=?",(dump(result),proposal_id))
    return result
