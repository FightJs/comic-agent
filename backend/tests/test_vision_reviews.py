import asyncio
import base64
import io
import json
import pytest
from PIL import Image
from fastapi import HTTPException
from backend.app import create_app


def fixture(tmp_path,monkeypatch):
    import backend.app as module
    monkeypatch.setattr(module.vault,'get_password',lambda *args:'vision-test-key')
    app=create_app(tmp_path)
    with app.state.store.db() as db:
        db.execute('INSERT INTO projects VALUES(?,?,?,?,?)',('p','视觉验收',0,'t','t'))
        db.execute('INSERT INTO settings VALUES(1,?)',(json.dumps({'vision':{'url':'http://127.0.0.1:1/v1','model':'fixture','api':'openai-completions'}}),))
        buf=io.BytesIO();Image.new('RGB',(16,24),'red').save(buf,format='PNG');pixels=buf.getvalue()
        url=app.state.store.file(db,'p','panel.png',pixels,'image/png')
        target=app.state.store.add(db,'p','image','第1格',{'url':url,'prompt':'主角在雨中','episode':1,'panel':1},'ai')
        ref=app.state.store.add(db,'p','asset','主角',{'url':url},'import')
        db.execute("INSERT INTO reviews VALUES(?,?,?,?,?,?,?)",('rv',ref['id'],1,'approved','核对','import','t'))
    return app,target,ref,pixels


def result():
    return {'summary':'头发颜色偏离参考','issues':[{'severity':'major','category':'identity','description':'发色与批准图不一致','evidence':'图1头顶为红色，图2头顶为黑色','images':[1,2],'region':[.2,.1,.6,.3]}]}


def test_vision_freezes_actual_pixels_records_report_and_never_approves_image(tmp_path,monkeypatch):
    app,target,ref,pixels=fixture(tmp_path,monkeypatch);calls=[]
    async def request(command,**kw):
        calls.append((command,kw));return {'type':'result','data':{'text':json.dumps(result(),ensure_ascii=False),'usage':{'input':20,'output':10,'totalTokens':30,'cost':None}}}
    monkeypatch.setattr(app.state.pi_runtime,'request',request)
    service=app.state.vision_reviews
    review=service.prepare('p',{'id':target['id'],'version':1},references=[{'id':ref['id'],'version':1}],operation_key='one')
    assert not calls and review['status']=='prepared'
    done=asyncio.run(service.execute('p',review['id']))
    assert done['status']=='completed' and done['report']==result()
    assert done['usage']['totalTokens']==30 and done['source']=='ai'
    assert [base64.b64decode(i['data']) for i in calls[0][1]['images']]==[pixels,pixels]
    assert calls[0][0]=='complete' and 'tools' not in calls[0][1]
    assert '主角在雨中' in calls[0][1]['prompt'] and '主角' in calls[0][1]['prompt']
    asyncio.run(service.execute('p',review['id']));assert len(calls)==1
    with app.state.store.db() as db:
        assert app.state.store.get(db,'p',target['id'])['version']==1
        assert app.state.store.get(db,'p',target['id'])['review']=='pending'
    assert 'vision-test-key' not in (tmp_path/'workbench.sqlite').read_bytes().decode(errors='ignore')


def test_vision_rejects_unapproved_refs_and_stale_inputs_without_request(tmp_path,monkeypatch):
    app,target,ref,_=fixture(tmp_path,monkeypatch);service=app.state.vision_reviews
    with app.state.store.db() as db:db.execute('DELETE FROM reviews')
    with pytest.raises(HTTPException):service.prepare('p',{'id':target['id'],'version':1},references=[{'id':ref['id'],'version':1}],operation_key='bad')
    review=service.prepare('p',{'id':target['id'],'version':1},operation_key='stale')
    with app.state.store.db() as db:app.state.store.save(db,'p',target['id'],1,{**target['content'],'prompt':'新版'})
    with pytest.raises(HTTPException):asyncio.run(service.execute('p',review['id']))
    assert service.get('p',review['id'])['status']=='prepared'


def test_vision_invalid_report_preserves_return_and_unknown_never_retries(tmp_path,monkeypatch):
    app,target,_,_=fixture(tmp_path,monkeypatch);service=app.state.vision_reviews;calls=[]
    async def request(command,**kw):calls.append(kw);return {'type':'result','data':{'text':'{"summary":"缺少问题字段"}','usage':None}}
    monkeypatch.setattr(app.state.pi_runtime,'request',request)
    review=service.prepare('p',{'id':target['id'],'version':1},operation_key='bad-json')
    done=asyncio.run(service.execute('p',review['id']))
    assert done['status']=='invalid' and done['raw']=='{"summary":"缺少问题字段"}' and done['report'] is None
    asyncio.run(service.execute('p',review['id']));assert len(calls)==1
    async def timeout(command,**kw):calls.append(kw);raise TimeoutError()
    monkeypatch.setattr(app.state.pi_runtime,'request',timeout)
    review=service.prepare('p',{'id':target['id'],'version':1},operation_key='timeout')
    assert asyncio.run(service.execute('p',review['id']))['status']=='unknown'
    asyncio.run(service.execute('p',review['id']));assert len(calls)==2


def test_vision_received_result_recovers_after_recreation_without_new_call(tmp_path,monkeypatch):
    app,target,ref,_=fixture(tmp_path,monkeypatch);service=app.state.vision_reviews
    review=service.prepare('p',{'id':target['id'],'version':1},references=[{'id':ref['id'],'version':1}],operation_key='saved')
    with app.state.store.db() as db:
        db.execute("UPDATE vision_reviews SET status='received',raw=? WHERE id=?",(json.dumps(result()),review['id']))
    from backend.vision_reviews import VisionReviews
    restored=VisionReviews(app,app.state.store,service.credentials,service.config_get)
    done=asyncio.run(restored.execute('p',review['id']))
    assert done['status']=='completed' and done['report']==result()
    with app.state.store.db() as db:db.execute("UPDATE vision_reviews SET status='running' WHERE id=?",(review['id'],))
    restored=VisionReviews(app,app.state.store,service.credentials,service.config_get)
    assert restored.get('p',review['id'])['status']=='unknown'


def test_vision_cancelled_waiter_never_submits_and_late_return_keeps_cancellation(tmp_path,monkeypatch):
    app,target,ref,_=fixture(tmp_path,monkeypatch);service=app.state.vision_reviews;calls=[]
    async def request(command,**kw):
        calls.append((command,kw))
        if command=='complete':
            with app.state.store.db() as db:db.execute("UPDATE vision_reviews SET status='cancelled' WHERE id=?",(kw['run_id'],))
            return {'type':'result','data':{'text':json.dumps(result()),'usage':None}}
        return {'type':'result','data':{}}
    monkeypatch.setattr(app.state.pi_runtime,'request',request)
    async def check():
        first=service.prepare('p',{'id':target['id'],'version':1},operation_key='wait')
        await service.slot.acquire()
        task=asyncio.create_task(service.execute('p',first['id']))
        await service.cancel('p',first['id']);service.slot.release()
        assert (await task)['status']=='cancelled' and not calls
        second=service.prepare('p',{'id':target['id'],'version':1},references=[{'id':ref['id'],'version':1}],operation_key='late')
        done=await service.execute('p',second['id'])
        assert done['status']=='cancelled' and done['raw'] and done['report']==result()
    asyncio.run(check())


@pytest.mark.parametrize('patch',[
    {'images':[3]}, {'region':[.9,.9,.5,.5]}, {'severity':'pass'}, {'evidence':''}, {'region':[True,0,.2,.2]}, {'images':[]},
])
def test_vision_rejects_unverifiable_issue_references(tmp_path,monkeypatch,patch):
    from backend.vision_reviews import validate_report
    report=result();report['issues'][0].update(patch)
    with pytest.raises(ValueError):validate_report(json.dumps(report),2)


def test_vision_mock_source_and_project_isolation(tmp_path,monkeypatch):
    app,target,_,_=fixture(tmp_path,monkeypatch);service=app.state.vision_reviews
    with app.state.store.db() as db:db.execute("UPDATE versions SET source='mock' WHERE record_id=?",(target['id'],))
    job=service.prepare('p',{'id':target['id'],'version':1},operation_key='mock')
    assert job['source']=='mock'
    with app.state.store.db() as db:db.execute('INSERT INTO projects VALUES(?,?,?,?,?)',('other','其他项目',0,'t','t'))
    with pytest.raises(HTTPException):service.get('other',job['id'])
    with pytest.raises(HTTPException):service.prepare('other',{'id':target['id'],'version':1},operation_key='foreign')


def test_host_vision_through_real_pi_sdk_reaches_loopback_with_pixels(tmp_path,monkeypatch):
    import threading
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    app,target,ref,pixels=fixture(tmp_path,monkeypatch);requests=[]
    class Provider(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append(body)
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
            for delta,finish in [({'role':'assistant','content':json.dumps(result(),ensure_ascii=False)},None),({},'stop')]:
                value={'id':'vision','object':'chat.completion.chunk','created':1,'model':'fixture','choices':[{'index':0,'delta':delta,'finish_reason':finish}]}
                self.wfile.write(('data: '+json.dumps(value)+'\n\n').encode())
            self.wfile.write(b'data: [DONE]\n\n')
    server=ThreadingHTTPServer(('127.0.0.1',0),Provider);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with app.state.store.db() as db:
            db.execute('UPDATE settings SET content=?',(json.dumps({'vision':{'url':f'http://127.0.0.1:{server.server_port}/v1','model':'fixture'}}),))
        async def check():
            await app.state.pi_runtime.start()
            try:
                assert app.state.pi_runtime.status=='ready'
                job=app.state.vision_reviews.prepare('p',{'id':target['id'],'version':1},references=[{'id':ref['id'],'version':1}],operation_key='real-sdk')
                done=await app.state.vision_reviews.execute('p',job['id'])
                assert done['status']=='completed',done
                assert done['usage'] is None
            finally:await app.state.pi_runtime.close()
        asyncio.run(check())
        content=next(m['content'] for m in requests[0]['messages'] if m['role']=='user')
        assert [base64.b64decode(p['image_url']['url'].split(',')[1]) for p in content if p['type']=='image_url']==[pixels,pixels]
        assert not requests[0].get('tools') and len(requests)==1
        assert not list((tmp_path/'agent').rglob('*.jsonl'))
    finally:server.shutdown();server.server_close();thread.join()


def test_vision_configuration_changed_after_key_read_blocks_before_dispatch(tmp_path,monkeypatch):
    app,target,_,_=fixture(tmp_path,monkeypatch);service=app.state.vision_reviews;calls=[]
    review=service.prepare('p',{'id':target['id'],'version':1},operation_key='config-race')
    original=service.credentials
    def credentials():
        old=original()
        with app.state.store.db() as db:db.execute('UPDATE settings SET content=?',(json.dumps({'vision':{'url':'http://other.invalid/v1','model':'changed'}}),))
        return old
    monkeypatch.setattr(service,'credentials',credentials)
    async def request(*args,**kw):calls.append(kw);return {'type':'error'}
    monkeypatch.setattr(app.state.pi_runtime,'request',request)
    with pytest.raises(HTTPException):asyncio.run(service.execute('p',review['id']))
    assert not calls and service.get('p',review['id'])['status']=='prepared'


def test_vision_http_preview_start_and_isolated_history(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    app,target,ref,_=fixture(tmp_path,monkeypatch);calls=[];original=app.state.pi_runtime.request
    async def request(command,**kw):
        if command!='complete':return await original(command,**kw)
        calls.append(kw);return {'type':'result','data':{'text':json.dumps(result()),'usage':None}}
    monkeypatch.setattr(app.state.pi_runtime,'request',request)
    with TestClient(app) as c:
        body={'target':{'id':target['id'],'version':1},'references':[{'id':ref['id'],'version':1}],'submission_id':'preview'}
        response=c.post('/api/projects/p/vision-reviews',json=body)
        assert response.status_code==200,response.text
        review=response.json();assert review['status']=='prepared' and not calls
        assert c.post('/api/projects/p/vision-reviews',json=body).json()['id']==review['id']
        url='/api/projects/p/vision-reviews/'+review['id']
        assert c.post(url+'/start',json={}).status_code==200
        assert c.get(url).json()['status']=='completed' and len(calls)==1
        c.post(url+'/start',json={});assert len(calls)==1
        rows=c.get('/api/projects/p/vision-reviews',params={'target_id':target['id']}).json()
        assert len(rows)==1 and rows[0]['target_version']==1 and 'raw' not in rows[0]
        assert c.get('/api/projects/other/vision-reviews/'+review['id']).status_code==404


def test_vision_unknown_requires_explicit_resolution_before_another_call(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    app,target,_,_=fixture(tmp_path,monkeypatch);calls=[];original=app.state.pi_runtime.request
    async def request(command,**kw):
        if command!='complete':return await original(command,**kw)
        calls.append(kw);raise TimeoutError()
    monkeypatch.setattr(app.state.pi_runtime,'request',request)
    with TestClient(app) as c:
        b='/api/projects/p/vision-reviews';body={'target':{'id':target['id'],'version':1},'submission_id':'unknown'}
        first=c.post(b,json=body).json();url=b+'/'+first['id']
        c.post(url+'/start',json={});assert c.get(url).json()['status']=='unknown'
        assert c.post(url+'/recover',json={}).status_code==409
        second=c.post(b,json={**body,'submission_id':'second'}).json()
        assert c.post(b+'/'+second['id']+'/start',json={}).status_code==409 and len(calls)==1
        assert c.post(url+'/resolve',json={'confirmed':False,'note':'尚未核对'}).status_code==422
        assert c.post(url+'/resolve',json={'confirmed':True,'note':'已在本机替身确认无可恢复返回，明确结束等待'}).json()['status']=='resolved'
        c.post(b+'/'+second['id']+'/start',json={});assert len(calls)==2


def test_vision_queued_restart_requires_explicit_reauthorization(tmp_path,monkeypatch):
    from backend.vision_reviews import VisionReviews
    app,target,_,_=fixture(tmp_path,monkeypatch);service=app.state.vision_reviews
    first=service.prepare('p',{'id':target['id'],'version':1},operation_key='queued')
    with app.state.store.db() as db:db.execute("UPDATE vision_reviews SET status='queued' WHERE id=?",(first['id'],))
    restored=VisionReviews(app,app.state.store,service.credentials,service.config_get)
    assert restored.get('p',first['id'])['status']=='interrupted'
    assert asyncio.run(restored.execute('p',first['id']))['status']=='interrupted'


def test_vision_deep_invalid_json_is_saved_as_invalid_report(tmp_path,monkeypatch):
    app,target,_,_=fixture(tmp_path,monkeypatch);service=app.state.vision_reviews
    async def request(command,**kw):return {'type':'result','data':{'text':'['*2000+']'*2000,'usage':None}}
    monkeypatch.setattr(app.state.pi_runtime,'request',request)
    first=service.prepare('p',{'id':target['id'],'version':1},operation_key='deep')
    done=asyncio.run(service.execute('p',first['id']))
    assert done['status']=='invalid' and done['raw'] and done['report'] is None


def test_vision_late_return_preserves_manual_resolution_and_its_note(tmp_path,monkeypatch):
    app,target,ref,_=fixture(tmp_path,monkeypatch);service=app.state.vision_reviews
    async def request(command,**kw):
        with app.state.store.db() as db:db.execute("UPDATE vision_reviews SET status='resolved',error='人工记录：已结束等待' WHERE id=?",(kw['run_id'],))
        return {'type':'result','data':{'text':json.dumps(result()),'usage':None}}
    monkeypatch.setattr(app.state.pi_runtime,'request',request)
    first=service.prepare('p',{'id':target['id'],'version':1},references=[{'id':ref['id'],'version':1}],operation_key='late-resolved')
    done=asyncio.run(service.execute('p',first['id']))
    assert done['status']=='resolved' and done['error']=='人工记录：已结束等待' and done['raw']


def test_vision_http_saved_report_recovery_returns_final_result_without_background_delay(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    app,target,ref,_=fixture(tmp_path,monkeypatch)
    review=app.state.vision_reviews.prepare('p',{'id':target['id'],'version':1},references=[{'id':ref['id'],'version':1}],operation_key='http-received')
    with app.state.store.db() as db:db.execute("UPDATE vision_reviews SET status='received',raw=? WHERE id=?",(json.dumps(result()),review['id']))
    with TestClient(app) as c:
        response=c.post('/api/projects/p/vision-reviews/'+review['id']+'/recover',json={})
        assert response.status_code==200,response.text
        assert response.json()['status']=='completed' and response.json()['report']==result()
