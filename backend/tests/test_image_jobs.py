import asyncio
import base64
import io
import json
import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from backend.app import create_app


def fixture(tmp_path,monkeypatch):
    import backend.app as module
    monkeypatch.setattr(module.vault,'get_password',lambda *args:'fixture-key')
    app=create_app(tmp_path);calls=[]
    def provider(request):
        calls.append(request);buf=io.BytesIO();Image.new('RGB',(8,8),'red').save(buf,format='PNG')
        return httpx.Response(200,json={'data':[{'b64_json':base64.b64encode(buf.getvalue()).decode()}]})
    app.state.image_provider.transport=httpx.MockTransport(provider)
    with app.state.store.db() as db:db.execute('INSERT INTO settings VALUES(1,?)',(json.dumps({'image':{'url':'http://fixture/v1','model':'gpt-image-1.5','api':'openai-images'}}),))
    return app,calls


def test_style_preview_explicit_start_candidate_and_adoption(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'画风'}).json()['id'];base=f'/api/projects/{pid}'
        body={'kind':'style','title':'水墨方向','prompt':'水墨画风与清晰轮廓','submission_id':'first'}
        preview=c.post(base+'/image-jobs',json=body)
        assert preview.status_code==200,preview.text
        job=preview.json();assert job['status']=='preview' and not calls
        assert c.get(base+'/records').json()==[]
        started=c.post(base+'/image-jobs/'+job['id']+'/start',json={});assert started.status_code==200,started.text
        completed=c.get(base+'/image-jobs/'+job['id']).json()
        assert completed['status']=='succeeded' and len(calls)==1
        output=c.get(base+'/records/'+completed['output_id']).json()
        assert output['adopted']==0 and output['content']['creation_candidate'] and output['content']['checked'] is False
        assert c.post(base+'/style-selection',json={'record_id':output['id'],'version':1}).status_code==409
        adopted=c.post(base+'/candidates/'+output['id']+'/adopt',json={})
        assert adopted.status_code==200,adopted.text
        assert adopted.json()['adopted']==2
        assert c.post(base+'/image-jobs/'+job['id']+'/start',json={}).status_code==200 and len(calls)==1


def test_regeneration_never_overwrites_target_and_detects_stale_adoption(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'改图'}).json()['id'];base=f'/api/projects/{pid}'
        target=c.post(base+'/records',json={'kind':'style','title':'原画风','content':{'prompt':'旧提示'}}).json()
        job=c.post(base+'/image-jobs',json={'kind':'style','title':'改画风','prompt':'新提示','target':{'id':target['id'],'version':1},'submission_id':'edit'}).json()
        assert c.post(base+'/image-jobs/'+job['id']+'/start',json={}).status_code==200
        result=c.get(base+'/image-jobs/'+job['id']).json()
        assert c.get(base+'/records/'+target['id']).json()['version']==1
        c.put(base+'/records/'+target['id'],json={'expected_version':1,'content':{'prompt':'人工新稿'}})
        assert c.post(base+'/candidates/'+result['output_id']+'/adopt',json={}).status_code==409
        assert c.get(base+'/records/'+target['id']).json()['content']['prompt']=='人工新稿'


def test_asset_requires_confirmed_style_and_freezes_style_selection(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'资产'}).json()['id'];base=f'/api/projects/{pid}'
        body={'kind':'asset','title':'主角','prompt':'青年主角人设','submission_id':'asset'}
        assert c.post(base+'/image-jobs',json=body).status_code==409
        style=c.post(base+'/records',json={'kind':'style','title':'画风','content':{}}).json()
        c.post(base+'/style-selection',json={'record_id':style['id'],'version':1})
        # Confirmed styles without an image cannot masquerade as image references.
        assert c.post(base+'/image-jobs',json=body).status_code==422 and not calls


def test_unknown_job_blocks_other_previews_and_never_resubmits(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch)
    def uncertain(request):calls.append(request);raise httpx.ReadTimeout('fixture',request=request)
    app.state.image_provider.transport=httpx.MockTransport(uncertain)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'未知'}).json()['id'];b=f'/api/projects/{pid}'
        body={'kind':'style','title':'同一方向','prompt':'雨夜','submission_id':'one'}
        first=c.post(b+'/image-jobs',json=body).json()
        second=c.post(b+'/image-jobs',json={**body,'submission_id':'two'}).json()
        c.post(b+'/image-jobs/'+first['id']+'/start',json={})
        assert c.get(b+'/image-jobs/'+first['id']).json()['status']=='unknown'
        assert c.post(b+'/image-jobs/'+second['id']+'/start',json={}).status_code==409
        assert len(calls)==1
        assert c.post(b+'/image-jobs',json={**body,'submission_id':'three'}).status_code==409
        assert c.post(b+'/image-jobs/'+first['id']+'/resolve',json={'outcome':'no_image','note':'已核对供应商账单与请求编号，无图','confirmed':True}).status_code==200
        assert c.post(b+'/image-jobs',json={**body,'submission_id':'four'}).status_code==200


def test_cancelled_inflight_unknown_still_requires_reconciliation(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch);state={}
    def uncertain(request):
        calls.append(request)
        with app.state.store.db() as db:
            row=db.execute('SELECT payload FROM image_jobs WHERE id=?',(state['id'],)).fetchone();payload=json.loads(row['payload']);payload['cancel_requested']=True
            db.execute("UPDATE image_jobs SET status='cancelled',payload=? WHERE id=?",(json.dumps(payload),state['id']))
        raise httpx.ReadTimeout('fixture',request=request)
    app.state.image_provider.transport=httpx.MockTransport(uncertain)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'取消'}).json()['id'];b=f'/api/projects/{pid}'
        body={'kind':'style','title':'同一目标','prompt':'雨夜','submission_id':'one'}
        first=c.post(b+'/image-jobs',json=body).json();state['id']=first['id']
        c.post(b+'/image-jobs/'+first['id']+'/start',json={})
        assert c.get(b+'/image-jobs/'+first['id']).json()['status']=='unknown'
        assert c.post(b+'/image-jobs',json={**body,'submission_id':'two'}).status_code==409


def test_regenerating_imported_picture_records_ai_source_on_new_version(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'导入图再生成'}).json()['id'];b=f'/api/projects/{pid}'
        buf=io.BytesIO();Image.new('RGB',(8,8),'blue').save(buf,format='PNG')
        with app.state.store.db() as db:
            url=app.state.store.file(db,pid,'import.png',buf.getvalue(),'image/png');target=app.state.store.add(db,pid,'style','导入画风',{'url':url,'prompt':'旧提示'},'import')
        job=c.post(b+'/image-jobs',json={'kind':'style','title':'再生成','prompt':'保留线条修改色彩','target':{'id':target['id'],'version':1},'submission_id':'import-edit'}).json()
        c.post(b+'/image-jobs/'+job['id']+'/start',json={})
        output=c.get(b+'/image-jobs/'+job['id']).json()['output_id']
        adopted=c.post(b+'/candidates/'+output+'/adopt',json={})
        assert adopted.status_code==200,adopted.text
        assert adopted.json()['source']=='ai'
        assert c.get(b+'/records/'+target['id']+'?version=1').json()['source']=='import'


def test_publication_failure_recovers_saved_return_without_second_image_request(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'恢复'}).json()['id'];b=f'/api/projects/{pid}'
        job=c.post(b+'/image-jobs',json={'kind':'style','title':'恢复图','prompt':'雨夜','submission_id':'recover'}).json()
        original=app.state.store.add
        def fail(*args,**kwargs):raise OSError('publication fixture')
        monkeypatch.setattr(app.state.store,'add',fail)
        c.post(b+'/image-jobs/'+job['id']+'/start',json={})
        assert c.get(b+'/image-jobs/'+job['id']).json()['status']=='interrupted' and len(calls)==1
        monkeypatch.setattr(app.state.store,'add',original)
        assert c.post(b+'/image-jobs/'+job['id']+'/recover',json={}).status_code==200
        recovered=c.get(b+'/image-jobs/'+job['id']).json()
        assert recovered['status']=='succeeded' and recovered['output_id'] and len(calls)==1
        assert len(c.get(b+'/records').json())==1


def test_cancel_during_call_keeps_return_but_never_publishes_candidate(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch);original=app.state.image_provider.transport;state={}
    def cancel_and_return(request):
        with app.state.store.db() as db:
            row=db.execute('SELECT payload FROM image_jobs WHERE id=?',(state['id'],)).fetchone();p=json.loads(row['payload']);p['cancel_requested']=True
            db.execute("UPDATE image_jobs SET status='cancelled',payload=? WHERE id=?",(json.dumps(p),state['id']))
        return original.handler(request)
    app.state.image_provider.transport=httpx.MockTransport(cancel_and_return)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'取消保存'}).json()['id'];b=f'/api/projects/{pid}'
        job=c.post(b+'/image-jobs',json={'kind':'style','title':'取消图','prompt':'雨夜','submission_id':'cancel'}).json();state['id']=job['id']
        c.post(b+'/image-jobs/'+job['id']+'/start',json={})
        result=c.get(b+'/image-jobs/'+job['id']).json()
        assert result['status']=='cancelled' and result['call']['status']=='completed'
        assert result['call']['result']['url'] and not result['output_id'] and len(calls)==1
        assert c.get(b+'/records').json()==[]


def test_style_switch_during_generation_keeps_old_binding_and_blocks_adoption(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch);original=app.state.image_provider.transport;state={}
    def change_and_return(request):
        with app.state.store.db() as db:db.execute("UPDATE selections SET record_id=? WHERE project_id=? AND kind='style'",(state['second'],state['pid']))
        return original.handler(request)
    app.state.image_provider.transport=httpx.MockTransport(change_and_return)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'画风切换'}).json()['id'];b=f'/api/projects/{pid}';state['pid']=pid
        buf=io.BytesIO();Image.new('RGB',(8,8),'blue').save(buf,format='PNG')
        with app.state.store.db() as db:
            url=app.state.store.file(db,pid,'style.png',buf.getvalue(),'image/png')
            first=app.state.store.add(db,pid,'style','画风一',{'url':url},'import');second=app.state.store.add(db,pid,'style','画风二',{'url':url},'import')
        state['second']=second['id'];c.post(b+'/style-selection',json={'record_id':first['id'],'version':1})
        job=c.post(b+'/image-jobs',json={'kind':'asset','title':'主角','prompt':'主角人设','submission_id':'switch'}).json()
        c.post(b+'/image-jobs/'+job['id']+'/start',json={})
        result=c.get(b+'/image-jobs/'+job['id']).json()
        assert result['status']=='succeeded' and result['output']['content']['style_reference']['record_id']==first['id']
        assert result['output']['content']['input_stale']
        assert c.post(b+'/candidates/'+result['output_id']+'/adopt',json={}).status_code==409


def test_style_regeneration_accepts_existing_custom_category(tmp_path,monkeypatch):
    app,_=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'自定义分类'}).json()['id'];b=f'/api/projects/{pid}'
        target=c.post(b+'/records',json={'kind':'style','title':'水墨','content':{'category':'水墨风格'}}).json()
        preview=c.post(b+'/image-jobs',json={'kind':'style','title':'水墨','category':'水墨风格','prompt':'保留水墨笔触','target':{'id':target['id'],'version':1},'submission_id':'category'})
        assert preview.status_code==200,preview.text


def test_restart_of_submitted_unknown_call_has_manual_resolution_path(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'重启未知'}).json()['id'];b=f'/api/projects/{pid}'
        job=c.post(b+'/image-jobs',json={'kind':'style','title':'重启图','prompt':'雨夜','submission_id':'restart'}).json()
        with app.state.store.db() as db:
            db.execute("UPDATE image_jobs SET status='running' WHERE id=?",(job['id'],))
            db.execute("UPDATE image_calls SET status='submitting' WHERE id=?",(job['call_id'],))
    reopened=create_app(tmp_path)
    with TestClient(reopened) as c:
        result=c.get(b+'/image-jobs/'+job['id']).json()
        assert result['status']=='unknown' and result['call']['status']=='unknown'
        response=c.post(b+'/image-jobs/'+job['id']+'/resolve',json={'outcome':'no_image','note':'人工核对该次请求后确认无图','confirmed':True})
        assert response.status_code==200,response.text
        assert not calls


def test_unknown_with_persisted_response_recovers_without_another_request(tmp_path,monkeypatch):
    app,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'重启前返回'}).json()['id'];b=f'/api/projects/{pid}'
        job=c.post(b+'/image-jobs',json={'kind':'style','title':'恢复图','prompt':'雨夜','submission_id':'saved'}).json()
        saved=asyncio.run(app.state.image_provider.execute(pid,job['call_id'],authorization_hash=job['input_hash']))
        with app.state.store.db() as db:
            db.execute("UPDATE image_jobs SET status='unknown' WHERE id=?",(job['id'],))
            db.execute("UPDATE image_calls SET status='unknown',result=NULL WHERE id=?",(job['call_id'],))
        result=c.get(b+'/image-jobs/'+job['id']).json()
        assert result['call']['has_saved_response'] is True
        response=c.post(b+'/image-jobs/'+job['id']+'/recover',json={})
        assert response.status_code==200,response.text
        recovered=c.get(b+'/image-jobs/'+job['id']).json()
        assert recovered['status']=='succeeded' and len(calls)==1
        assert recovered['call']['result']['url']==saved['result']['url']
