"""Freeze the package's real prompt, panel identity and approved image references."""
from fastapi import HTTPException
from .store import is_primary
from . import image_dependencies


def dependencies_pending(content):
    # Until actual predecessor bytes are bound, no entry point may drop this input.
    return any(key in content and (not isinstance(content[key],list) or bool(content[key])) for key in ('generation_dependencies','previous_image_dependencies'))


def heads(store,db,pid,episode,panel):
    rows=[store.get(db,pid,r['id']) for r in db.execute("SELECT id FROM records WHERE project_id=? AND kind='image'",(pid,))]
    return [r for r in rows if is_primary(r) and r['content'].get('episode')==episode and r['content'].get('panel')==panel]


def prepare(store,db,pid,body,payload,dependency_plan=None):
    if not body.basis or body.references:raise HTTPException(422,'逐格生图须指定生图包；参考请先在包内保存，不在此临时替换')
    package=store.get(db,pid,body.basis.id);c=package['content']
    if package['kind']!='package' or package['version']!=body.basis.version or not is_primary(package):raise HTTPException(409,'生图包已变化或尚未采用；请关闭面板并刷新生图包后重新预览')
    if dependencies_pending(c) and (dependency_plan is None or not image_dependencies.matches(c,dependency_plan)):raise HTTPException(422,'生图包含前图依赖或依赖格式无效；请从包含依赖包的批次预览，不能忽略依赖提交')
    if not isinstance(c.get('prompt'),str) or not c['prompt'].strip() or body.prompt!=c['prompt']:raise HTTPException(422,'必须使用生图包固定版本的完整提示词；修改请先保存生图包')
    if any(type(c.get(k)) is not int or c[k]<1 for k in ('episode','panel')):raise HTTPException(422,'生图包话格身份不完整')
    batch=c.get('batch',(c['episode']-1)//10+1)
    if type(batch) is not int or batch<1:raise HTTPException(422,'生图包批次身份无效')
    payload['input_refs'][package['id']]=package['version'];source=package['source']
    if c.get('script_id'):
        script=store.get(db,pid,c['script_id'])
        if script['kind']!='script' or script['version']!=c.get('script_version') or not is_primary(script) or script['review']!='approved':raise HTTPException(409,'绑定脚本已变化或尚未审核通过，请更新并核对生图包')
        if any(script['content'].get(k)!=c[k] for k in ('episode','panel')):raise HTTPException(422,'绑定脚本与生图包的话格不一致')
        payload['input_refs'][script['id']]=script['version']
        if script['source']=='mock':source='mock'
    refs=[];versions={}
    raw=c.get('references',[])
    if not isinstance(raw,list) or len(raw)>16:raise HTTPException(422,'生图包参考格式无效或超过16张')
    for ref in raw:
        if not isinstance(ref,dict) or not isinstance(ref.get('id'),str) or type(ref.get('version')) is not int:raise HTTPException(422,'生图包参考需要明确记录及版本')
        r=store.get(db,pid,ref['id'],ref['version']);head=store.get(db,pid,r['id'])
        if r['kind'] not in ('style','asset') or not is_primary(head) or head['adopted']!=r['version'] or r['review']!='approved' or not r['content'].get('url'):raise HTTPException(409,'包内图像参考须仍为已采用且审核通过的实际图片，请重新核对')
        if r['id'] in versions and versions[r['id']]!=r['version']:raise HTTPException(422,'同一参考不能混用不同版本')
        versions[r['id']]=r['version'];refs.append({'id':r['id'],'version':r['version']})
    if dependency_plan:
        for ref in dependency_plan.get('ancestors',dependency_plan['packages']):payload['input_refs'][ref['id']]=ref['version']
        for ref in dependency_plan['images']:
            r=store.get(db,pid,ref['id']);exact={'id':ref['id'],'version':ref['version']}
            if r['version']!=ref['version'] or r['adopted']!=ref['version'] or r['review']!='approved' or not is_primary(r):raise HTTPException(409,'已有前图状态已变化，请重新预览')
            refs.append(exact)
        payload['dependency_plan']=dependency_plan
        payload['dependencies_bound']=not bool(dependency_plan['packages'])
    current=heads(store,db,pid,c['episode'],c['panel'])
    target=body.target.model_dump() if body.target else None
    if target:
        if not any(r['id']==target['id'] and r['version']==target['version'] for r in current):raise HTTPException(409,'目标图片不属于当前话格或已有新版本')
    elif len(current)>1:raise HTTPException(409,'同一话格有多份当前图片，请明确处理目标后再生成')
    elif current:target={'id':current[0]['id'],'version':current[0]['version']}
    payload['image_slot']={'episode':c['episode'],'panel':c['panel'],'heads':{r['id']:{'version':r['version'],'adopted':r['adopted']} for r in current}}
    payload['image_content']={k:c[k] for k in ('episode','panel','characters','scene','script_id','script_version') if k in c}
    payload['image_content'].update(batch=batch,package_id=package['id'],package_version=package['version'])
    payload['package_title']=package['title']
    return target,refs,'mock' if source=='mock' else 'ai'
