from fastapi.testclient import TestClient
from backend.app import create_app


def setup(tmp_path):
    c=TestClient(create_app(tmp_path)); p=c.post('/api/projects',json={'name':'制作测试'}).json()['id']; b=f'/api/projects/{p}'
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
