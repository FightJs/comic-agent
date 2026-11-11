"""Read-only adaptation of the legacy ratio distribution checker; no file or image IO."""
from collections import Counter
from fastapi import HTTPException

POLICY='content_balanced_ratios_v1'
RATIOS=('9:16','3:4','4:5','1:1','5:4','16:9')
PORTRAIT=RATIOS[:3]

def distribution(ratios):
    n=len(ratios);counts=Counter(ratios);portrait=sum(counts[r] for r in PORTRAIT);errors=[]
    if not n:errors.append({'code':'empty','message':'全话计划为空'})
    if portrait*4<=3*n:errors.append({'code':'portrait_share','message':'竖版格数须严格超过全话四分之三'})
    adjacent=[i+1 for i in range(1,n) if ratios[i]==ratios[i-1]]
    if adjacent:errors.append({'code':'adjacent','positions':adjacent,'message':'相邻格须使用不同画幅'})
    for group in (PORTRAIT,RATIOS[3:]):
        if max(counts[r] for r in group)-min(counts[r] for r in group)>1:
            errors.append({'code':'balance','group':list(group),'message':'同方向组的三种比例数量差须不超过1'})
    checks=[(r,lambda value,r=r:value==r,counts[r],2) for r in RATIOS]
    checks.append(('方形/横版',lambda value:value not in PORTRAIT,n-portrait,1))
    for label,chosen,total,slack in checks:
        used=0
        for pos,value in enumerate(ratios,1):
            used+=bool(chosen(value))
            if abs(used*n-total*pos)>slack*n:
                errors.append({'code':'prefix','ratio':label,'position':pos,'message':'比例在源序中集中堆积，须按内容均匀穿插'});break
    return {'valid':not errors,'errors':errors,'statistics':{'panel_count':n,'counts':{r:counts[r] for r in RATIOS},'portrait_count':portrait,'minimum_portrait_count':3*n//4+1 if n else 0}}

def check(frozen,anchor,plan=None):
    mapping=frozen.get('frame_plan_sources')
    if not isinstance(anchor,str):raise HTTPException(422,'脚本编号必须为字符串')
    issues=frozen.get('frame_plan_issues',[])
    if any(i['id']==anchor for i in issues):raise HTTPException(409,'该已采用脚本无法绑定有效话格，未检查缩减源序')
    if not isinstance(mapping,dict) or anchor not in mapping:raise HTTPException(403,'当前快照没有这份已采用脚本的画幅源序；未读取其他项目或新版本')
    episode=mapping[anchor]['episode']
    if any(i['episode'] in (None,episode) for i in issues):raise HTTPException(409,'固定主稿存在无法定位的已采用脚本，不能将漏格集合当整话；请核对源话格')
    sources=sorted(({'id':rid,**info} for rid,info in mapping.items() if info['episode']==episode),key=lambda s:(s['panel'],s['id']))
    if len(sources)>1000:raise HTTPException(422,'单话超过1000格，当前画幅检查未支持；未把分段当整话')
    if len({s['panel'] for s in sources})!=len(sources):raise HTTPException(409,'固定脚本中同话格号重复，不能猜测整话源序')
    origins={s['source'] for s in sources}
    result={'policy':POLICY,'source':'mock' if 'mock' in origins else next(iter(origins)) if len(origins)==1 else 'mixed','episode':episode,'sources':sources,'read_only':True,'adopted':False,'semantic_review':'当前固定主稿集合不证明原著已完整改编；未验证选幅理由、裁切可行性或实际图片；本结果不代表采用、审核或生成权限'}
    if plan is None:return result
    if not isinstance(plan,list) or not 1<=len(plan)<=1000:raise HTTPException(422,'需提交1至1000格的完整计划')
    for row in plan:
        if not isinstance(row,dict) or set(row)!={'id','ratio','reason'} or not isinstance(row['id'],str) or not isinstance(row['ratio'],str) or row['ratio'] not in RATIOS or not isinstance(row['reason'],str) or not row['reason'].strip() or len(row['reason'])>2000:raise HTTPException(422,'每格需准确id、支持的ratio与非空reason，不接受批准或额外字段')
    if [row['id'] for row in plan]!=[s['id'] for s in sources]:raise HTTPException(409,'计划必须逐一覆盖本次固定整话源序，不可漏格、重复、跨项目或重排')
    return {**result,**distribution([row['ratio'] for row in plan])}
