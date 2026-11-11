"""Host-owned script identities and reversible retirement of dependent records."""
from fastapi import HTTPException
from .store import is_primary

TEXT_FIELDS={'characters','scene','weather','time','shot','camera','description','dialogue','sfx','note'}


def affected(rows,anchor,target,new_panel=None):
    rows=[r for r in rows if not r['content'].get('deleted_by_script')] if target=='script_delete' else rows
    episode=anchor['content']['episode'];panel=anchor['content']['panel']
    if target=='script_create':
        return [r for r in rows if r['content'].get('episode')==episode and (r['kind']=='script' or r['kind'] in ('package','image') and r['content'].get('panel')==new_panel)]
    matched=[r for r in rows if r['kind'] in ('script','package','image') and r['content'].get('episode')==episode and r['content'].get('panel')==panel]
    matched_ids={r['id'] for r in matched}
    packages=[r for r in rows if r['kind']=='package' and r['content'].get('script_id')==anchor['id'] and r['id'] not in matched_ids]
    matched.extend(packages)
    package_ids={r['id'] for r in matched if r['kind']=='package'}
    matched_ids.update(r['id'] for r in packages)
    matched.extend(r for r in rows if r['kind']=='image' and r['id'] not in matched_ids and (r['content'].get('script_id')==anchor['id'] or r['content'].get('package_id') in package_ids))
    image_ids={r['id'] for r in matched if r['kind']=='image'}
    return matched+[r for r in rows if r['kind']=='trial' and any(ref.get('id') in image_ids for ref in r['content'].get('references',[]) if isinstance(ref,dict))]


def prepare(store,db,pid,frozen,change):
    rid=change['id'];target=change['target'];patch=change['patch']
    refs={r['id']:r['version'] for r in frozen.get('write_refs',[])}
    if frozen.get('stage')!='script' or rid not in refs:raise HTTPException(403,'增删只允许附加的本阶段脚本，请明确选择目标')
    anchor=store.get(db,pid,rid,refs[rid]);c=anchor['content']
    if anchor['kind']!='script' or not is_primary(anchor):raise HTTPException(409,'增删需要当前已采用脚本作为目标')
    if any(type(c.get(k)) is not int or c[k]<1 for k in ('episode','panel')):raise HTTPException(422,'脚本话格身份不完整')
    rows=[store.get(db,pid,key,ref['version']) for key,ref in frozen['records'].items()]
    if target=='script_create':
        if set(patch)-TEXT_FIELDS-{'panel'} or type(patch.get('panel')) is not int or not 1<=patch['panel']<=10000:raise HTTPException(422,'新增格号须为1至10000的整数，只允许脚本文本字段')
        if not any(isinstance(patch.get(k),str) and patch[k].strip() for k in TEXT_FIELDS):raise HTTPException(422,'新增脚本需要正文')
        if any(not isinstance(v,str) or len(v)>150000 for k,v in patch.items() if k!='panel'):raise HTTPException(422,'新增脚本字段须为受限文本')
        if any(r['kind'] in ('script','package','image') and r['content'].get('episode')==c['episode'] and r['content'].get('panel')==patch['panel'] for r in rows):raise HTTPException(409,'格号已使用（含历史候选或已删格），请选择新格号；已有格号不会重排')
    elif set(patch)!={'reason'} or not isinstance(patch['reason'],str) or not 1<=len(patch['reason'].strip())<=2000:raise HTTPException(422,'删除需要1至2000字的原因，不允许其他字段')
    dependencies=affected(rows,anchor,target,patch.get('panel'))
    return {**change,'version':anchor['version'],'kind':'script','title':anchor['title'],'before':c,'location':{k:c[k] for k in ('episode','panel','batch') if k in c},'dependencies':[{'id':r['id'],'version':r['version'],'kind':r['kind'],'title':r['title']} for r in dependencies]}


def validate(store,db,pid,change):
    anchor=store.get(db,pid,change['id'])
    if anchor['version']!=change['version'] or not is_primary(anchor):raise HTTPException(409,'脚本已有变化，请更新资料重新提出增删候选')
    rows=[store.get(db,pid,r['id']) for r in db.execute('SELECT id FROM records WHERE project_id=?',(pid,))]
    current=affected(rows,anchor,change['target'],change['patch'].get('panel'))
    if {r['id']:r['version'] for r in current}!={r['id']:r['version'] for r in change['dependencies']}:raise HTTPException(409,'话格或下游资料已有变化，请重新核对增删影响')


def apply(store,db,pid,run_id,source,change):
    anchor=store.get(db,pid,change['id'])
    if change['target']=='script_create':
        c=anchor['content'];panel=change['patch']['panel']
        content={k:c[k] for k in ('episode','batch') if k in c}
        content.update(change['patch'],ai_run_id=run_id,created_from={'id':anchor['id'],'version':anchor['version']})
        return [store.add(db,pid,'script',f"第{c['episode']}话第{panel}格",content,source)]
    result=[]
    for ref in change['dependencies']:
        old=store.get(db,pid,ref['id'])
        saved=store.save(db,pid,old['id'],old['version'],{**old['content'],'deleted_by_script':anchor['id'],'deletion_reason':change['patch']['reason'],'ai_run_id':run_id},source=source)
        db.execute('UPDATE records SET adopted=0 WHERE id=?',(old['id'],))
        result.append(saved)
    return result
