import asyncio
import json
import pytest
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.store import uid,now,dump
from backend.tests.test_api import project,record,png

@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path)) as c: yield c

def test_reference_source_and_cross_project_isolation(client):
    p,q=project(client),project(client)
    mock=record(client,p,'asset',{'description':'演示'},source='mock')
    result=record(client,p,'package',{'references':[{'id':mock['id'],'version':1,'purpose':'身份'}]})
    assert result['source']=='mock'
    assert client.post(f'/api/projects/{q}/records',json={'kind':'package','title':'包','content':{'references':[{'id':mock['id'],'version':1}]}}).status_code==404

def test_mock_script_source_is_inherited_by_package(client):
    p=project(client)
    script=record(client,p,'script',{'batch':1,'episode':1,'panel':1},source='mock')
    result=record(client,p,'package',{'script_id':script['id'],'script_version':1})
    assert result['source']=='mock'

def test_mock_edit_stays_mock_after_manual_save(client):
    p=project(client);r=record(client,p);path=f'/api/projects/{p}/records/{r["id"]}'
    v=client.post(path+'/mock-edit',json={'expected_version':1,'content':{'html':'模拟改写'}}).json()
    assert v['source']=='mock'
    v=client.put(path,json={'expected_version':2,'content':{'html':'人工重写'}}).json()
    assert v['source']=='mock'

def test_image_adoption_and_annotations_are_version_scoped(client):
    p=project(client)
    r=client.post(f'/api/projects/{p}/images',files={'file':('a.png',png(),'image/png')}).json()
    path=f'/api/projects/{p}/records/{r["id"]}'
    client.put(path+'/annotations',json={'expected_version':0,'image_version':1,'items':[{'id':'a','type':'point','x':10,'y':20}]})
    v2=client.post(f'/api/projects/{p}/images',data={'record_id':r['id'],'expected_version':'1'},files={'file':('b.png',png(),'image/png')}).json()
    assert v2['version']==2 and v2['adopted']==1
    assert client.get(path+'/annotations?image_version=2').json()['items']==[]
    assert client.post(path+'/adopt',json={'version':2}).json()['adopted']==2
    invalid=client.put(path+'/annotations',json={'expected_version':0,'image_version':2,'items':[{'id':'b','type':'rect','x':90,'y':20,'width':30,'height':20}]})
    assert invalid.status_code==422

def test_task_restart_marks_interrupted(tmp_path):
    app=create_app(tmp_path)
    with TestClient(app) as c:
        p=project(c)
        with app.state.store.db() as db:
            db.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?)',(uid(),p,'running',dump({'kind':'memory'}),None,'',now(),now()))
    with TestClient(create_app(tmp_path)) as c:
        assert c.get(f'/api/projects/{p}/tasks').json()[0]['status']=='interrupted'

def test_rejected_keychain_write_does_not_store_secret(client,monkeypatch):
    import backend.app as module
    class BadVault:
        def set_password(self,*args): raise RuntimeError('locked')
        def get_password(self,*args): raise RuntimeError('locked')
    monkeypatch.setattr(module,'vault',BadVault())
    response=client.put('/api/settings',json={'secret':'do-not-leak','url':'https://example.com','model':'x','purpose':'text'})
    assert response.status_code==503
    assert 'do-not-leak' not in response.text
    with client.app.state.store.db() as db:
        assert db.execute('SELECT count(*) FROM settings').fetchone()[0]==0

def test_stale_async_result_is_saved_separately(tmp_path):
    import httpx
    app=create_app(tmp_path)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as c:
            p=(await c.post('/api/projects',json={'name':'并发'})).json()['id']
            r=(await c.post(f'/api/projects/{p}/records',json={'kind':'outline','title':'细纲','content':{'html':'旧文'}})).json()
            path=f'/api/projects/{p}/records/{r["id"]}'
            task=asyncio.create_task(c.post(f'/api/projects/{p}/tasks',json={'kind':'outline','target_id':r['id'],'input_version':1}))
            await asyncio.sleep(.1)
            changed=await c.put(path,json={'expected_version':1,'content':{'html':'新文'}})
            assert changed.status_code==200
            await task
            assert (await c.get(path)).json()['content']['html']=='新文'
            tasks=(await c.get(f'/api/projects/{p}/tasks')).json()
            assert tasks[0]['status']=='pending'
            assert tasks[0]['output_id']!=r['id']
    asyncio.run(scenario())

def test_external_origin_and_different_host_rejected(client):
    assert client.post('/api/projects',json={'name':'恶意'},headers={'origin':'https://evil.example'}).status_code==403
    assert client.get('/api/projects',headers={'host':'evil.example'}).status_code==403

def test_archive_restore_and_whitespace_validation(client):
    p=project(client)
    assert client.put(f'/api/projects/{p}',json={'name':'更新','archived':True}).json()['archived']==1
    assert client.put(f'/api/projects/{p}',json={'name':'更新','archived':False}).json()['archived']==0
    assert client.post('/api/projects',json={'name':'   '}).status_code==422

def test_configuration_is_separate_for_each_model_purpose(client,monkeypatch):
    import backend.app as module
    class Vault:
        values={}
        def set_password(self,service,user,password): self.values[user]=password
        def get_password(self,service,user): return self.values.get(user)
    monkeypatch.setattr(module,'vault',Vault())
    for purpose,model in [('text','text-model'),('image','image-model')]:
        assert client.put('/api/settings',json={'purpose':purpose,'model':model,'secret':purpose+'-secret'}).status_code==200
    assert client.get('/api/settings?purpose=text').json()['model']=='text-model'
    assert client.get('/api/settings?purpose=image').json()['model']=='image-model'
    assert client.get('/api/settings?purpose=vision').json()['has_secret'] is False

def test_recording_image_review_keeps_annotations_on_identical_base(client):
    p=project(client)
    image=client.post(f'/api/projects/{p}/images',files={'file':('a.png',png(),'image/png')}).json()
    path=f'/api/projects/{p}/records/{image["id"]}'
    items=[{'id':'a','type':'point','x':10,'y':20,'note':'保留'}]
    client.put(path+'/annotations',json={'expected_version':0,'image_version':1,'items':items})
    r=client.put(path,json={'expected_version':1,'content':{**image['content'],'checked':True,'issues':[]}}).json()
    assert client.get(path+f'/annotations?image_version={r["version"]}').json()['items']==items

def test_repair_freezes_selected_historical_base_and_annotations(client):
    p=project(client)
    first=client.post(f'/api/projects/{p}/images',files={'file':('a.png',png(),'image/png')}).json()
    path=f'/api/projects/{p}/records/{first["id"]}'
    client.put(path+'/annotations',json={'expected_version':0,'image_version':1,'items':[{'id':'a','type':'point','x':10,'y':20}]})
    client.post(f'/api/projects/{p}/images',data={'record_id':first['id'],'expected_version':'1'},files={'file':('b.png',png(),'image/png')})
    response=client.post(f'/api/projects/{p}/tasks',json={'kind':'repair','target_id':first['id'],'input_version':2,'base_image_version':1,'instruction':'仅修改标注目标'})
    assert response.status_code==200
    task=client.get(f'/api/projects/{p}/tasks').json()[0]
    assert task['payload']['base_image_version']==1
    assert task['payload']['annotation_snapshot']['items'][0]['x']==10
    assert task['payload']['base_image_url']==first['content']['url']

def test_gates_ignore_other_batches_and_demo_records(client):
    p=project(client)
    client.post(f'/api/projects/{p}/text',files={'file':('story.txt','第一章\n原著'.encode(),'text/plain')})
    image=client.post(f'/api/projects/{p}/images',files={'file':('a.png',png(),'image/png')}).json()
    for kind in ['skeleton','outline','style','asset','script','trial']:
        r=record(client,p,kind,{'batch':1,**({'references':[{'id':image['id'],'version':1}]} if kind=='trial' else {})})
        client.post(f'/api/projects/{p}/records/{r["id"]}/reviews',json={'version':1,'decision':'approved','note':'人工确认'})
        if kind=='style': client.post(f'/api/projects/{p}/style-selection',json={'record_id':r['id'],'version':1})
    record(client,p,'script',{'batch':2})
    record(client,p,'asset',{'state':'演示'},source='mock')
    assert client.get(f'/api/projects/{p}/gates?batch=1').json()['ready'] is True
    assert client.get(f'/api/projects/{p}/gates?batch=2').json()['ready'] is False

def test_text_preface_is_not_lost_before_first_chapter(client):
    p=project(client)
    r=client.post(f'/api/projects/{p}/text',files={'file':('序章.txt','这是前言。\n第一章 入院\n正文'.encode(),'text/plain')}).json()
    assert r['content']['chapters'][0]['offset']==0
    assert r['content']['chapters'][0]['title']=='前言'

def test_style_selection_and_trial_become_stale_when_inputs_change(client):
    p=project(client)
    style=record(client,p,'style',{'description':'画风A'})
    path=f'/api/projects/{p}/records/{style["id"]}'
    client.post(path+'/reviews',json={'version':1,'decision':'approved','note':'选定'})
    selected=client.post(f'/api/projects/{p}/style-selection',json={'record_id':style['id'],'version':1})
    assert selected.status_code==200
    assert '画风审核' not in client.get(f'/api/projects/{p}/gates').json()['reasons']
    client.put(path,json={'expected_version':1,'content':{'description':'画风修改'}})
    assert '画风审核' in client.get(f'/api/projects/{p}/gates').json()['reasons']
    image=client.post(f'/api/projects/{p}/images',files={'file':('a.png',png(),'image/png')}).json()
    trial=record(client,p,'trial',{'references':[{'id':image['id'],'version':1,'purpose':'首话'}]})
    client.post(f'/api/projects/{p}/records/{trial["id"]}/reviews',json={'version':1,'decision':'approved','note':'确认'})
    assert '首话试制确认' not in client.get(f'/api/projects/{p}/gates').json()['reasons']
    newer=client.post(f'/api/projects/{p}/images',data={'record_id':image['id'],'expected_version':'1'},files={'file':('b.png',png(),'image/png')}).json()
    client.post(f'/api/projects/{p}/records/{image["id"]}/adopt',json={'version':newer['version']})
    assert '首话试制确认' in client.get(f'/api/projects/{p}/gates').json()['reasons']

def test_batch_review_is_atomic_and_bound_to_versions(client):
    p=project(client)
    a=record(client,p,'script',{'batch':1,'episode':1,'panel':1})
    b=record(client,p,'script',{'batch':1,'episode':1,'panel':2},source='mock')
    payload={'batch':1,'records':[{'id':a['id'],'version':1},{'id':b['id'],'version':1}],'decision':'approved','note':'批次审核'}
    response=client.post(f'/api/projects/{p}/batch-review',json=payload)
    assert response.status_code==200
    client.put(f'/api/projects/{p}/records/{b["id"]}',json={'expected_version':1,'content':b['content']})
    assert client.post(f'/api/projects/{p}/batch-review',json=payload).status_code==409
    assert len(client.get(f'/api/projects/{p}/records/{a["id"]}/reviews').json())==1

def test_brush_width_is_saved_in_image_units_and_validated(client):
    p=project(client)
    image=client.post(f'/api/projects/{p}/images',files={'file':('a.png',png(),'image/png')}).json()
    path=f'/api/projects/{p}/records/{image["id"]}/annotations'
    item={'id':'brush','type':'brush','points':[10,20,30,40],'brushWidth':32}
    assert client.put(path,json={'expected_version':0,'image_version':1,'items':[item]}).status_code==200
    assert client.get(path+'?image_version=1').json()['items'][0]['brushWidth']==32
    item['brushWidth']=-1
    assert client.put(path,json={'expected_version':1,'image_version':1,'items':[item]}).status_code==422

def test_invalid_configuration_never_echoes_rejected_secret(client):
    secret='sensitive-key-'*1000
    response=client.put('/api/settings',json={'secret':secret})
    assert response.status_code==422
    assert 'sensitive-key' not in response.text
