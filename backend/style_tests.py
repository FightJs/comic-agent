"""An immutable trio of comparable style proposals, with no image-call permission."""
import json
from fastapi import HTTPException
from pydantic import BaseModel,ConfigDict,Field
from .store import uid,now,dump,is_primary
from . import graph_store,preferences,vision_grounding
from .skills import frozen_skills

class Data(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
class Representative(Data):
    character:str=Field(min_length=1,max_length=200)
    appearance:str=Field(min_length=1,max_length=3000)
    scene:str=Field(min_length=1,max_length=200)
    setting:str=Field(min_length=1,max_length=3000)
    action:str=Field(min_length=1,max_length=3000)
class Direction(Data):
    name:str=Field(min_length=1,max_length=80)
    line:str=Field(min_length=1,max_length=800)
    proportions:str=Field(min_length=1,max_length=800)
    color:str=Field(min_length=1,max_length=800)
    shadow:str=Field(min_length=1,max_length=800)
class SourceRange(Data):
    document_id:str
    parse_version:int=Field(ge=1)
    start:int=Field(ge=0)
    end:int=Field(gt=0)
class TestIn(Data):
    title:str=Field(min_length=1,max_length=120)
    outline_id:str
    representative:Representative
    directions:list[Direction]=Field(min_length=3,max_length=3)
    source_ranges:list[SourceRange]=Field(min_length=1,max_length=5)


def schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS style_test_sets(id TEXT PRIMARY KEY,project_id TEXT,run_id TEXT,title TEXT,source TEXT,content TEXT,created TEXT)')


def stale(store,db,pid,basis):
    ref=basis['outline']
    try:
        current=store.get(db,pid,ref['id'])
        if any(current[k]!=ref[k] for k in ('version','adopted','review')) or not is_primary(current):return True
        if vision_grounding.sources_stale(store,db,pid,basis['sources']):return True
        selected=db.execute('SELECT * FROM graph_source WHERE project_id=?',(pid,)).fetchone()
        if (dict(selected) if selected else None)!=basis['original_selection']:return True
        if graph_store.load(store,db,pid)[0]!=basis['graph_revision']:return True
        if preferences.read(store,db,pid)['revision']!=basis['preferences_revision']:return True
        return [s['hash'] for s in frozen_skills(store,db,pid,'style')]!=basis['skills']
    except HTTPException as exc:
        if exc.status_code in (404,409,422):return True
        raise


def propose(store,db,pid,run_id,frozen,value):
    tools=frozen.get('allowed_tools')
    if frozen.get('stage')!='style' or not isinstance(tools,list) or 'propose_style_tests' not in tools:raise HTTPException(403,'本次运行未开放三套画风方案，旧检查点不自动扩权')
    try:body=TestIn.model_validate(value)
    except ValueError:raise HTTPException(422,'三套方案须包含同组人物/场景、原著范围、细纲编号和恰好三个画风方向；不接受模型、密钥或任意参数')
    if any(not field.strip() for field in [body.title,*body.representative.model_dump().values(),*(v for d in body.directions for v in d.model_dump().values())]):raise HTTPException(422,'共有输入和画风特征不能为空')
    if len({dump(d.model_dump(exclude={'name'})) for d in body.directions})!=3:raise HTTPException(422,'三个方向须有不同的可观察画风特征，不可只换名称')
    info=frozen.get('records',{}).get(body.outline_id)
    if not info or info['kind']!='outline':raise HTTPException(403,'细纲须在本次固定项目资料中')
    outline=store.get(db,pid,body.outline_id)
    if outline['version']!=info['version'] or not is_primary(outline) or outline['review']!='approved':raise HTTPException(409,'请先采用并审核当前细纲，再重新讨论三套画风')
    preferred=frozen.get('preferred_document')
    ranges=[r.model_dump() for r in body.source_ranges]
    if not preferred or any(r['document_id']!=preferred['id'] or r['parse_version']!=preferred['parse_version'] for r in ranges):raise HTTPException(403,'画风原著证据须来自本次固定的首选小说版本')
    sources=vision_grounding.freeze_sources(store,db,pid,ranges)
    if any(s['head_parse_version']!=s['parse_version'] or frozen.get('records',{}).get(s['record_id'],{}).get('version')!=s['record_version'] for s in sources):raise HTTPException(409,'原著在本次讨论后已有新版本，不能在旧讨论中改绑证据，请重新讨论')
    quotes='\n'.join(s['quote'] for s in sources)
    if body.representative.character not in quotes or body.representative.scene not in quotes:raise HTTPException(422,'人物与场景名称须能在所选原著引文中定位；不能用摘要伪作原文')
    basis={'outline':{k:outline[k] for k in ('id','title','version','adopted','review','source')},'sources':sources,'original_selection':frozen.get('original_selection'),'graph_revision':frozen['graph_revision'],'preferences_revision':frozen.get('preferences',{}).get('revision',0),'skills':[s['hash'] for s in frozen.get('skills',[])]}
    if stale(store,db,pid,basis):raise HTTPException(409,'原著或创作依据已变化，请重新讨论；未创建方案')
    shared=body.representative.model_dump();prompts=[]
    for direction in body.directions:
        prompt='二维漫画画风试验板，不是正文格。各区域是同一人物与同一场景的测试，不引入其他主人公或主场景。\n本组三套完全相同的内容依据（不得被画风差异替换）：\n'+dump(shared)+'\n本套可观察画风：\n'+dump(direction.model_dump())+'\n同一张测试板清楚分区：身份全身；同衣装正面/侧面/背面多视角；同一人物两种表情；该人物在上述主场景执行上述剧情动作。统一各区域人物身份、衣装和场景结构。二维线条、比例、上色、阴影按本套特征一致表达。此为画风比较，不增加、删除或改写小说剧情；文字事实与补充外观须由用户核对。'
        if len(prompt)>32000:raise HTTPException(422,'测试板提示词超过32000字符，未截断或创建半组')
        prompts.append(prompt)
    from . import agent_image_plans
    source='mock' if frozen.get('inherited_mock') or outline['source']=='mock' or any(s['source']=='mock' for s in sources) else 'ai'
    effective={**frozen,**({'inherited_mock':True} if source=='mock' else {})}
    group_id=uid();plan_ids=[]
    db.execute('SAVEPOINT style_trio')
    try:
        for index,(direction,prompt) in enumerate(zip(body.directions,prompts)):
            plan=agent_image_plans.propose(store,db,pid,run_id,effective,{'title':body.title+' · '+chr(65+index)+' · '+direction.name,'prompt':prompt})
            content=json.loads(db.execute('SELECT content FROM agent_image_plans WHERE id=?',(plan['id'],)).fetchone()[0])
            content['style_test']={'id':group_id,'option':chr(65+index),'representative':shared,'features':direction.model_dump(),'basis':basis}
            db.execute('UPDATE agent_image_plans SET content=? WHERE id=?',(dump(content),plan['id']))
            plan_ids.append(plan['id'])
            if plan['source']=='mock':source='mock'
        test={'representative':shared,'directions':[d.model_dump() for d in body.directions],'basis':basis,'plan_ids':plan_ids}
        db.execute('INSERT INTO style_test_sets VALUES(?,?,?,?,?,?,?)',(group_id,pid,run_id,body.title,source,dump(test),now()))
        db.execute('RELEASE style_trio')
    except BaseException:
        db.execute('ROLLBACK TO style_trio');db.execute('RELEASE style_trio');raise
    return {'id':group_id,'source':source,'message':'三套同组画风方案已保存，每套一张测试板；未调用图像模型。请核对共有依据及差异，再逐套预览、明确授权生成，候选仍未采用。'}


def register(app,store):
    @app.get('/api/projects/{pid}/agent/style-tests/{gid}')
    def read(pid:str,gid:str):
        from . import agent_image_plans
        with store.db() as db:
            store.project(db,pid)
            row=db.execute('SELECT * FROM style_test_sets WHERE id=? AND project_id=?',(gid,pid)).fetchone()
            if not row:raise HTTPException(404,'画风测试组不属于本项目')
            value=dict(row);value['test']=json.loads(value.pop('content'))
            value['stale']=stale(store,db,pid,value['test']['basis'])
            value['plans']=[agent_image_plans.get(store,db,pid,rid) for rid in value['test']['plan_ids']]
        for plan in value['plans']:
            if plan['job_id']:plan['job']=app.state.image_jobs.public(pid,plan['job_id'])
        from .style_batches import matches
        with store.db() as db:batch=db.execute('SELECT id,payload,input_hash FROM image_batches WHERE project_id=? AND token=?',(pid,'style-test-'+gid)).fetchone()
        if matches(batch,gid):value['batch']=app.state.image_batches.public(pid,batch['id'])
        return value
