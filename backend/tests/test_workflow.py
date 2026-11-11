from fastapi.testclient import TestClient
from backend.app import create_app


def setup(tmp_path,configured=True):
    c=TestClient(create_app(tmp_path)); p=c.post('/api/projects',json={'name':'制作测试'}).json()['id']; b=f'/api/projects/{p}'
    if configured:
        import json
        from backend.tests.test_production_text import panel
        app=c.app
        app.state.graph_engine.vault_get=lambda purpose:'fake-production-credential'
        with app.state.store.db() as db:db.execute('INSERT INTO settings VALUES(1,?)',(json.dumps({'text':{'purpose':'text','url':'http://fixture.invalid/v1','model':'fixture'}}),))
        async def request(command,**data):
            payload=json.loads(data['prompt'].split('固定输入：\n',1)[1].split('\n本次启用流程规则：',1)[0])
            op=payload['operation']
            value={'panels':[panel(),panel(2)]} if op=='range' else {'scene_prompt':'旧院','content_prompt':'阿青推门','position_prompt':'门口','shot_prompt':'中景','constraints':'身份一致'} if op=='package' else {'patch':{'description':'雨夜旧院'}} if payload['snapshots'][0]['kind']=='script' else {'patch':{'prompt':'优化后的画面提示'}}
            return {'type':'result','data':{'text':json.dumps(value,ensure_ascii=False),'usage':None}}
        app.state.pi_runtime.request=request
    def add(kind,content): return c.post(b+'/records',json={'kind':kind,'title':'测试','content':content}).json()
    return c,b,add


def test_discussion_does_not_generate_and_snapshot_is_frozen(tmp_path):
    c,b,add=setup(tmp_path)
    r=add('script',{'episode':31,'panel':1,'batch':4,'description':'原稿'})
    refs=[{'id':r['id'],'version':1}]
    chat=c.post(b+'/conversations',json={'refs':refs,'message':'只改场景','expected_version':0}).json()
    assert chat.get('version')==1
    assert c.get(b+'/tasks').json()==[]
    body={'operation':'rewrite','refs':refs,'instruction':'改为雨夜','submission_id':'once','conversation_id':chat['id'],'conversation_version':1}
    first=c.post(b+'/production-jobs',json=body)
    assert first.status_code==200,first.text
    again=c.post(b+'/production-jobs',json=body).json()
    assert again==first.json()
    assert c.get(b+'/records/'+r['id']).json()['version']==1
    tasks=c.get(b+'/tasks').json(); assert len(tasks)==1
    assert tasks[0]['payload']['conversation']['version']==1
    assert tasks[0]['payload']['snapshots'][0]['content']['description']=='原稿'
    out=tasks[0]['output_id']; candidate=c.get(b+'/records/'+out).json()
    assert candidate['content']['candidate_for']==r['id']
    adopted=c.post(b+'/candidates/'+out+'/adopt',json={}).json()
    assert adopted['id']==r['id'] and adopted['content']['panel']==1
    assert adopted['source']=='mock'
    assert c.post(b+'/candidates/'+out+'/adopt',json={}).status_code==409


def test_outline_mapping_range_and_isolation(tmp_path):
    c,b,add=setup(tmp_path)
    original=c.post(b+'/text',files={'file':('原著.txt','全书原著'.encode(),'text/plain')}).json()
    o=add('outline',{'html':'<h3>第十话</h3><p>甲</p><h3>第十一话</h3><p>乙</p>'})
    entries=[{'episode':10,'title':'甲','text':'甲','source_range':'第一章'},{'episode':11,'title':'乙','text':'乙'}]
    url=b+'/outline-index/'+o['id']
    assert c.put(url,json={'outline_version':1,'expected_version':0,'entries':entries+entries[:1]}).status_code==422
    mapped=c.put(url,json={'outline_version':1,'expected_version':0,'entries':entries}); assert mapped.status_code==200,mapped.text
    body={'operation':'range','outline_id':o['id'],'outline_version':1,'index_version':1,'start':10,'end':11,'submission_id':'range','refs':[]}
    result=c.post(b+'/production-jobs',json=body); assert result.status_code==200,result.text
    rows=c.get(b+'/records?kind=script').json(); assert {r['content']['episode'] for r in rows}=={10,11}
    assert {r['content']['batch'] for r in rows}=={1,2}
    body.update(end=12,submission_id='missing'); assert c.post(b+'/production-jobs',json=body).status_code==422
    p2=c.post('/api/projects',json={'name':'other'}).json()['id']
    assert c.post(f'/api/projects/{p2}/production-jobs',json={'operation':'rewrite','refs':[{'id':rows[0]['id'],'version':1}],'submission_id':'cross'}).status_code==404


def test_only_selected_panels_change_and_stale_candidate_rejected(tmp_path):
    c,b,add=setup(tmp_path)
    a=add('script',{'episode':1,'panel':1,'description':'甲'}); z=add('script',{'episode':1,'panel':2,'description':'乙'})
    res=c.post(b+'/production-jobs',json={'operation':'rewrite','refs':[{'id':a['id'],'version':1}],'instruction':'改场景','submission_id':'a'})
    assert res.status_code==200,res.text
    task=c.get(b+'/tasks').json()[0]
    assert len(task['payload']['context'])==2
    c.put(b+'/records/'+a['id'],json={'expected_version':1,'content':{**a['content'],'description':'新稿'}})
    assert c.post(b+'/candidates/'+task['output_id']+'/adopt',json={}).status_code==409
    assert c.get(b+'/records/'+z['id']).json()['content']['description']=='乙'


def test_historical_image_comments_frozen_and_only_explicit_adoption(tmp_path):
    import io
    from PIL import Image
    c,b,add=setup(tmp_path)
    buf=io.BytesIO();Image.new('RGB',(40,60),'red').save(buf,'PNG')
    a=c.post(b+'/images',files={'file':('图.png',buf.getvalue(),'image/png')}).json()
    c.post(b+'/images',data={'record_id':a['id'],'expected_version':1},files={'file':('新图.png',buf.getvalue(),'image/png')})
    c.put(b+'/records/'+a['id']+'/annotations',json={'image_version':1,'expected_version':0,'items':[{'id':'p','type':'point','x':2,'y':3,'note':'眼睛'}]})
    result=c.post(b+'/production-jobs',json={'operation':'repair','refs':[{'id':a['id'],'version':1}],'instruction':'保持其他部分','per_item':{a['id']:'改眼睛'},'submission_id':'image','annotation_versions':{a['id']:1}})
    assert result.status_code==200,result.text
    task=c.get(b+'/tasks').json()[0]
    assert task['payload']['annotation_snapshot']['items'][0]['note']=='眼睛'
    assert '改眼睛' in task['payload']['instruction']
    assert c.get(b+'/records/'+a['id']).json()['version']==2
    adopted=c.post(b+'/candidates/'+task['output_id']+'/adopt',json={})
    assert adopted.status_code==200,adopted.text
    assert adopted.json()['adopted']==3
    assert c.get(b+'/records/'+a['id']+'/annotations?image_version=3').json()['items']==[]


def test_repair_rejects_annotations_changed_since_preview(tmp_path):
    import io
    from PIL import Image
    c,b,add=setup(tmp_path);buf=io.BytesIO();Image.new('RGB',(20,20)).save(buf,'PNG')
    r=c.post(b+'/images',files={'file':('图.png',buf.getvalue(),'image/png')}).json()
    c.put(b+'/records/'+r['id']+'/annotations',json={'image_version':1,'expected_version':0,'items':[{'id':'p','type':'point','x':1,'y':1,'note':'新批注'}]})
    res=c.post(b+'/production-jobs',json={'operation':'repair','refs':[{'id':r['id'],'version':1}],'submission_id':'ann-conflict','annotation_versions':{r['id']:0}})
    assert res.status_code==409,res.text


def test_concurrent_first_packages_do_not_duplicate_primary(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    c,b,add=setup(tmp_path);s=add('script',{'episode':1,'panel':1})
    def submit(i):return c.post(b+'/production-jobs',json={'operation':'package','refs':[{'id':s['id'],'version':1}],'submission_id':str(i)})
    with ThreadPoolExecutor(2) as pool: results=list(pool.map(submit,[1,2]))
    primary=[r for r in c.get(b+'/records?kind=package').json() if not r['content'].get('candidate_for')]
    assert len(primary)==1
    assert all(r.status_code in (200,409) for r in results)


def test_selected_review_is_atomic_across_episode_groups(tmp_path):
    c,b,add=setup(tmp_path);a=add('script',{'episode':10,'panel':1});z=add('script',{'episode':11,'panel':1})
    refs=[{'id':a['id'],'version':1},{'id':z['id'],'version':99}]
    assert c.post(b+'/production-review',json={'refs':refs,'decision':'approved','note':'通过'}).status_code==409
    assert c.get(b+'/records/'+a['id']).json()['review']=='pending'
    refs[1]['version']=1
    assert c.post(b+'/production-review',json={'refs':refs,'decision':'approved','note':'通过'}).status_code==200
    assert c.get(b+'/records/'+a['id']).json()['review']=='approved'


def test_discussion_accepts_five_episode_150_panel_selection(tmp_path):
    c,b,_=setup(tmp_path)
    pid=b.split('/')[-1];store=c.app.state.store
    with store.db() as db:
        rows=[store.add(db,pid,'package',f'格{i}',{'episode':i//30+1,'panel':i%30+1,'prompt':'提示词'}) for i in range(150)]
    response=c.post(b+'/conversations',json={'refs':[{'id':r['id'],'version':1} for r in rows],'message':'五话统一场景色温','expected_version':0})
    assert response.status_code==200,response.text
    assert len(response.json()['content']['refs'])==150
    assert c.get(b+'/tasks').json()==[]


def test_text_generation_requires_provider_and_never_silently_simulates(tmp_path):
    c,b,add=setup(tmp_path,configured=False);r=add('script',{'episode':1,'panel':1,'description':'原稿'})
    response=c.post(b+'/production-jobs',json={'operation':'rewrite','refs':[{'id':r['id'],'version':1}],'submission_id':'no-config'})
    assert response.status_code==422
    assert c.get(b+'/tasks').json()==[]
    assert c.get(b+'/records/'+r['id']).json()['version']==1


def test_first_package_is_unadopted_until_explicit_use_and_blocks_stale_inputs(tmp_path):
    c,b,add=setup(tmp_path);r=add('script',{'episode':1,'panel':1,'description':'原稿'})
    response=c.post(b+'/production-jobs',json={'operation':'package','refs':[{'id':r['id'],'version':1}],'submission_id':'first'})
    assert response.status_code==200,response.text
    task=c.get(b+'/tasks').json()[0];out=c.get(b+'/records/'+task['output_id']).json()
    assert task['source']=='ai' and out['source']=='ai'
    assert task['payload']['output_versions'][out['id']]==1
    assert out['adopted']==0 and out['content']['creation_candidate'] is True
    assert out['content']['batch']==1
    blocked=c.post(b+'/production-jobs',json={'operation':'image','refs':[{'id':out['id'],'version':1}],'submission_id':'blocked'})
    assert blocked.status_code==422
    adopted=c.post(b+'/candidates/'+out['id']+'/adopt',json={})
    assert adopted.status_code==200,adopted.text
    assert adopted.json()['adopted']==2 and adopted.json()['review']=='pending'
    assert not adopted.json()['content'].get('creation_candidate')
    assert c.post(b+'/candidates/'+out['id']+'/adopt',json={}).status_code==409


def test_new_package_stale_source_cannot_be_adopted(tmp_path):
    c,b,add=setup(tmp_path);r=add('script',{'episode':1,'panel':1,'description':'原稿'})
    c.post(b+'/production-jobs',json={'operation':'package','refs':[{'id':r['id'],'version':1}],'submission_id':'first'})
    out=c.get(b+'/tasks').json()[0]['output_id']
    c.put(b+'/records/'+r['id'],json={'expected_version':1,'content':{**r['content'],'description':'新稿'}})
    assert c.post(b+'/candidates/'+out+'/adopt',json={}).status_code==409
    assert c.get(b+'/records/'+out).json()['adopted']==0


def test_mock_context_is_inherited_even_with_real_generation_entry(tmp_path):
    c,b,add=setup(tmp_path);pid=b.split('/')[-1]
    with c.app.state.store.db() as db:r=c.app.state.store.add(db,pid,'script','模拟依赖',{'episode':1,'panel':1,'description':'样例'},'mock')
    c.post(b+'/production-jobs',json={'operation':'package','refs':[{'id':r['id'],'version':1}],'submission_id':'mock-source'})
    task=c.get(b+'/tasks').json()[0]
    assert c.get(b+'/records/'+task['output_id']).json()['source']=='mock'


def test_cancelled_text_task_discards_late_model_output(tmp_path):
    import asyncio,json,threading
    from concurrent.futures import ThreadPoolExecutor
    from backend.tests.test_production_text import panel
    c,b,add=setup(tmp_path);r=add('script',{'episode':1,'panel':1,'description':'原稿'})
    started=threading.Event();release=threading.Event()
    async def request(command,**data):
        if command=='cancel':return {'type':'result','data':{'cancelled':True}}
        started.set();await asyncio.to_thread(release.wait,5)
        return {'type':'result','data':{'text':json.dumps({'patch':{'description':'迟到内容'}}),'usage':None}}
    c.app.state.pi_runtime.request=request
    with ThreadPoolExecutor(1) as pool:
        future=pool.submit(c.post,b+'/production-jobs',json={'operation':'rewrite','refs':[{'id':r['id'],'version':1}],'submission_id':'late'})
        assert started.wait(3)
        task=c.get(b+'/tasks').json()[0]
        assert c.post(b+f'/production-jobs/{task["id"]}/cancel',json={}).status_code==200
        release.set();assert future.result(timeout=5).status_code==200
    task=c.get(b+'/tasks').json()[0]
    assert task['status']=='cancelled' and task['output_id'] is None
    assert len(c.get(b+'/records').json())==1


def test_invalid_json_repairs_only_once_and_receipts_are_project_scoped(tmp_path):
    c,b,add=setup(tmp_path);r=add('script',{'episode':1,'panel':1,'description':'原稿'});calls=[]
    async def request(command,**data):
        calls.append(data);return {'type':'result','data':{'text':'invalid structure','usage':None}}
    c.app.state.pi_runtime.request=request
    c.post(b+'/production-jobs',json={'operation':'rewrite','refs':[{'id':r['id'],'version':1}],'submission_id':'invalid'})
    task=c.get(b+'/tasks').json()[0]
    assert task['status']=='failed' and len(calls)==2 and not task['output_id']
    assert len(c.get(b+'/records').json())==1
    receipts=c.get(b+f'/production-jobs/{task["id"]}/attempts').json()
    assert [r['status'] for r in receipts]==['invalid','invalid']
    assert all(r['raw']=='invalid structure' for r in receipts)
    p2=c.post('/api/projects',json={'name':'other'}).json()['id']
    assert c.get(f'/api/projects/{p2}/production-jobs/{task["id"]}/attempts').status_code==404


def test_rejected_first_candidate_cannot_be_adopted_and_can_be_regenerated(tmp_path):
    c,b,add=setup(tmp_path);r=add('script',{'episode':1,'panel':1,'description':'原稿'})
    body={'operation':'package','refs':[{'id':r['id'],'version':1}],'submission_id':'first'}
    assert c.post(b+'/production-jobs',json=body).status_code==200
    out=c.get(b+'/tasks').json()[0]['output_id']
    assert c.post(b+'/production-jobs',json={**body,'submission_id':'blocked'}).status_code==409
    assert c.post(b+'/candidates/'+out+'/reject',json={}).status_code==200
    assert c.post(b+'/candidates/'+out+'/adopt',json={}).status_code==409
    assert c.get(b+'/records/'+r['id']).json()['version']==1
    assert c.post(b+'/production-jobs',json={**body,'submission_id':'new'}).status_code==200


def test_package_segment_rewrite_preserves_manual_full_override(tmp_path):
    import json
    c,b,add=setup(tmp_path);r=add('package',{'episode':1,'panel':1,'prompt':'人工完整覆盖','prompt_mode':'override','shot_prompt':'原镜头'})
    async def request(command,**data):return {'type':'result','data':{'text':json.dumps({'patch':{'shot_prompt':'近景'}}),'usage':None}}
    c.app.state.pi_runtime.request=request
    c.post(b+'/production-jobs',json={'operation':'rewrite','refs':[{'id':r['id'],'version':1}],'submission_id':'segment'})
    task=c.get(b+'/tasks').json()[0];candidate=c.get(b+'/records/'+task['output_id']).json()
    assert candidate['content']['prompt']=='人工完整覆盖'
    assert candidate['content']['shot_prompt']=='近景'
    assert c.get(b+'/records/'+r['id']).json()['version']==1


def test_package_references_review_the_adopted_asset_version(tmp_path):
    c,b,add=setup(tmp_path);pid=b.split('/')[-1]
    script=add('script',{'episode':1,'panel':1,'description':'原稿'})
    asset=add('asset',{'prompt':'已采用参考'})
    c.post(b+'/records/'+asset['id']+'/reviews',json={'version':1,'decision':'approved','note':'固定资产通过'})
    c.put(b+'/records/'+asset['id'],json={'expected_version':1,'content':{'prompt':'未采用的新修改'}})
    c.post(b+'/production-jobs',json={'operation':'package','refs':[{'id':script['id'],'version':1}],'submission_id':'asset-ref'})
    task=c.get(b+'/tasks').json()[0];candidate=c.get(b+'/records/'+task['output_id']).json()
    assert candidate['content']['references']==[{'id':asset['id'],'version':1,'purpose':'参考'}]


def test_changed_candidate_cannot_be_adopted_from_frozen_generation_view(tmp_path):
    c,b,add=setup(tmp_path);script=add('script',{'episode':1,'panel':1,'batch':1,'description':'原稿'})
    c.post(b+'/production-jobs',json={'operation':'package','refs':[{'id':script['id'],'version':1}],'submission_id':'frozen'})
    out=c.get(b+'/tasks').json()[0]['output_id'];candidate=c.get(b+'/records/'+out).json()
    changed=c.put(b+'/records/'+out,json={'expected_version':1,'content':{**candidate['content'],'prompt':'后来改写的候选'}})
    assert changed.status_code==200,changed.text
    response=c.post(b+'/candidates/'+out+'/adopt',json={})
    assert response.status_code==409,response.text
    assert c.get(b+'/records/'+out).json()['adopted']==0
