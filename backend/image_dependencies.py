"""Explicit fixed-version continuity edges; generated pictures never become identity authority."""
from fastapi import HTTPException
from .store import is_primary

FIELDS=('generation_dependencies','previous_image_dependencies')


def declarations(content):
    result={}
    for key in FIELDS:
        refs=content.get(key,[])
        if not isinstance(refs,list) or len(refs)>8:raise HTTPException(422,'每类前图依赖须为最多8项的记录版本列表')
        seen=set()
        for ref in refs:
            if not isinstance(ref,dict) or set(ref)!={'id','version'} or not isinstance(ref['id'],str) or not ref['id'] or type(ref['version']) is not int or ref['version']<1:raise HTTPException(422,'前图依赖须明确记录id和version；不能用话格号猜测')
            if ref['id'] in seen:raise HTTPException(422,'同一类前图依赖不能重复')
            seen.add(ref['id'])
        result[key]=refs
    return result


def matches(content,plan):
    try:return declarations(content)==plan['declarations']
    except (HTTPException,KeyError):return False


def graph(store,db,pid,packages):
    selected={r['id']:r for r in packages};plans={};ordered=[];visiting=set();visited=set()
    for package in packages:
        ds=declarations(package['content']);future=[];known=[]
        for ref in ds['generation_dependencies']:
            if ref['id'] not in selected:raise HTTPException(422,'生成依赖的生图包必须包含在同一批次选择中')
            parent=selected[ref['id']]
            if parent['version']!=ref['version']:raise HTTPException(409,'生成依赖与所选生图包版本不一致')
            future.append({**ref,'title':parent['title'],'source':parent['source']})
        for ref in ds['previous_image_dependencies']:
            image=store.get(db,pid,ref['id'],ref['version']);head=store.get(db,pid,ref['id'])
            if image['kind']!='image' or not is_primary(head) or head['version']!=ref['version'] or head['adopted']!=ref['version'] or image['review']!='approved' or not image['content'].get('url'):raise HTTPException(409,'已有前图须为当前已采用并审核通过的实际话格图片')
            known.append({**ref,'title':image['title'],'source':image['source']})
        base_refs=package['content'].get('references',[])
        if not isinstance(base_refs,list):raise HTTPException(422,'生图包参考须为列表')
        if len(base_refs)+len(future)+len(known)>16:raise HTTPException(422,'资产与前图依赖合计不能超过16张参考')
        plans[package['id']]={'declarations':ds,'packages':future,'images':known}
    def visit(rid):
        if rid in visiting:raise HTTPException(422,'前图生成依赖存在循环，不能提交')
        if rid in visited:return
        visiting.add(rid)
        for parent in plans[rid]['packages']:visit(parent['id'])
        visiting.remove(rid);visited.add(rid);ordered.append(rid)
        plan=plans[rid]
        ancestors={}
        for parent in plan['packages']:
            ancestors[parent['id']]={'id':parent['id'],'version':parent['version']}
            for ref in plans[parent['id']]['ancestors']:ancestors[ref['id']]=ref
        plan['ancestors']=list(ancestors.values())
        plan['source']='mock' if selected[rid]['source']=='mock' or any(r['source']=='mock' for r in plan['images']) or any(plans[r['id']]['source']=='mock' for r in plan['packages']) else 'ai'
    for rid in selected:visit(rid)
    return plans,ordered


def compiled_prompt(prompt,plan):
    count=len(plan['images'])+len(plan['packages'])
    if not count:return prompt
    labels=[r['title']+' · v'+str(r['version']) for r in plan['images']+plan['packages']]
    return prompt+'\n\n【宿主固定：前图连续性参考】\n最后'+str(count)+'张参考图依次对应：'+'；'.join(labels)+'。仅用于动作、空间和状态连续性；人物身份与画风仍以已批准资产为准，不将前图当作身份或画风权威。前图实际像素须在采用并审核通过后绑定；不得以旧图或文字占位替代。'


def resolve(store,db,pid,plan,by_package,images,provider):
    """Resolve only the exact original call's pixels, following explicit adoption receipts."""
    refs=[];bindings=[]
    for parent in plan['packages']:
        producer=images.job(db,pid,by_package[parent['id']])
        post=producer['payload'].get('postprocess')
        if post:
            if post['status']!='completed':raise HTTPException(409,parent['title']+'：等待固定检查/返修流程结束，再核对采用与审核')
            if post['final_job_id']!=producer['id']:
                final=images.job(db,pid,post['final_job_id'])
                if final['payload'].get('repair_of')!=producer['id'] or final['payload'].get('image_batch_id')!=producer['payload'].get('image_batch_id'):raise HTTPException(409,'返修输出不属于原依赖生产者')
                producer=final
        if producer['status']!='succeeded' or not producer['output_id']:raise HTTPException(409,parent['title']+'：原生成尚未成功；依赖格未提交')
        call=provider.get(pid,producer['call_id']);candidate=store.get(db,pid,producer['output_id'])
        adopted=candidate['content'].get('adopted_into')
        record=store.get(db,pid,adopted['id'],adopted['version']) if adopted else candidate
        head=store.get(db,pid,record['id'])
        if call['status']!='completed' or not is_primary(head) or head['version']!=record['version'] or head['adopted']!=record['version'] or record['review']!='approved' or record['content'].get('image_call_id')!=call['id'] or record['content'].get('url')!=call['result']['url']:raise HTTPException(409,parent['title']+'：须采用并审核原调用的实际图片；依赖格未提交')
        ref={'id':record['id'],'version':record['version']};actual=provider._reference(db,pid,ref)
        if actual['sha256']!=call['result']['sha256']:raise HTTPException(409,'前图文件与原调用返回不一致，未提交依赖格')
        refs.append(ref);bindings.append({**actual,'producer_job_id':producer['id'],'producer_call_id':call['id'],'role':'continuity'})
    return refs,bindings
