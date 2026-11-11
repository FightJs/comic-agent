import asyncio
import base64
import io
import json
import httpx
import pytest
from PIL import Image
from fastapi import HTTPException
from backend.store import Store


def png(size=(8,8),alpha=False):
    output=io.BytesIO();Image.new('RGBA' if alpha else 'RGB',size,(255,0,0,0) if alpha else (255,0,0)).save(output,format='PNG');return output.getvalue()


def fixture(tmp_path,handler):
    from backend.image_provider import ImageProvider
    store=Store(tmp_path)
    with store.db() as db:db.execute("INSERT INTO projects VALUES('p','图像',0,'t','t')")
    config={'url':'http://fixture/v1','model':'gpt-image-1.5','api':'openai-images'}
    provider=ImageProvider(store,lambda:config.copy(),lambda:'fixture-secret',transport=httpx.MockTransport(handler))
    return store,provider,config


def reply(request):return httpx.Response(200,json={'data':[{'b64_json':base64.b64encode(png()).decode()}],'usage':{'input_tokens':10,'output_tokens':20,'total_tokens':30}})


def test_generation_is_durable_and_idempotent_without_storing_credentials(tmp_path):
    calls=[]
    def handle(request):calls.append(request);return reply(request)
    store,provider,_=fixture(tmp_path,handle)
    first=provider.prepare('p','one','雨夜街头')
    assert first['status']=='prepared' and not calls
    completed=asyncio.run(provider.execute('p',first['id']))
    assert completed['status']=='completed' and len(calls)==1
    payload=json.loads(calls[0].content)
    assert calls[0].url.path=='/v1/images/generations'
    assert payload['model']=='gpt-image-1.5' and payload['n']==1 and payload['output_format']=='png'
    assert calls[0].headers['authorization']=='Bearer fixture-secret'
    assert completed['result']['width']==8 and completed['result']['usage']['total_tokens']==30
    assert provider.prepare('p','one','雨夜街头')['id']==first['id']
    assert asyncio.run(provider.execute('p',first['id']))==completed
    assert len(calls)==1
    with pytest.raises(HTTPException):provider.prepare('p','one','更换提示词')
    with store.db() as db:
        assert 'fixture-secret' not in '\n'.join(db.iterdump())
    assert 'fixture-secret' not in '\n'.join(p.read_text() for p in (store.root/'image-receipts').glob('*.json'))


def test_multiple_references_and_mask_use_multipart_edit_in_frozen_order(tmp_path):
    calls=[]
    def handle(request):calls.append(request);return reply(request)
    store,provider,_=fixture(tmp_path,handle)
    with store.db() as db:
        refs=[]
        for n in range(2):
            url=store.file(db,'p',str(n)+'.png',png(),'image/png')
            r=store.add(db,'p','asset',str(n),{'url':url});refs.append({'id':r['id'],'version':1})
        url=store.file(db,'p','mask.png',png(alpha=True),'image/png')
        mask=store.add(db,'p','image','蒙版',{'url':url})
    call=provider.prepare('p','edit','修改背景',refs=refs,mask={'id':mask['id'],'version':1})
    result=asyncio.run(provider.execute('p',call['id']))
    assert result['status']=='completed'
    assert calls[0].url.path=='/v1/images/edits'
    body=calls[0].content
    assert body.count(b'name="image[]"')==2 and b'name="mask"' in body
    assert call['manifest']['references'][0]['id']==refs[0]['id']


def test_uncertain_network_result_never_reposts_even_after_restart(tmp_path):
    calls=[]
    def timeout(request):calls.append(request);raise httpx.ReadTimeout('fixture-secret',request=request)
    store,provider,config=fixture(tmp_path,timeout)
    call=provider.prepare('p','unknown','提示词')
    assert asyncio.run(provider.execute('p',call['id']))['status']=='unknown'
    from backend.image_provider import ImageProvider
    reopened=ImageProvider(store,lambda:config.copy(),lambda:'fixture-secret',transport=httpx.MockTransport(timeout))
    assert asyncio.run(reopened.execute('p',call['id']))['status']=='unknown'
    assert len(calls)==1
    with store.db() as db:assert 'fixture-secret' not in '\n'.join(db.iterdump())


def test_saved_response_recovers_after_registration_failure_without_new_bill(tmp_path,monkeypatch):
    calls=[]
    def handle(request):calls.append(request);return reply(request)
    store,provider,_=fixture(tmp_path,handle)
    call=provider.prepare('p','recover','提示词')
    monkeypatch.setattr(provider,'_finalize',lambda *args:(_ for _ in ()).throw(OSError('disk fixture')))
    assert asyncio.run(provider.execute('p',call['id']))['status']=='received'
    from backend.image_provider import ImageProvider
    reopened=ImageProvider(store,provider.profile_get,provider.secret_get,transport=httpx.MockTransport(handle))
    result=asyncio.run(reopened.execute('p',call['id']))
    assert result['status']=='completed' and len(calls)==1
    assert len(list((store.root/'files').iterdir()))==1


def test_references_changed_after_preparation_are_not_submitted(tmp_path):
    calls=[]
    def handle(request):calls.append(request);return reply(request)
    store,provider,_=fixture(tmp_path,handle)
    with store.db() as db:
        url=store.file(db,'p','a.png',png(),'image/png');r=store.add(db,'p','asset','人像',{'url':url})
    call=provider.prepare('p','stale','提示词',refs=[{'id':r['id'],'version':1}])
    with store.db() as db:store.save(db,'p',r['id'],1,{**r['content'],'note':'改过'})
    with pytest.raises(HTTPException):asyncio.run(provider.execute('p',call['id']))
    assert not calls


def test_concurrent_execution_submits_exactly_once(tmp_path):
    calls=[]
    async def handle(request):calls.append(request);await asyncio.sleep(.03);return reply(request)
    _,provider,_=fixture(tmp_path,handle)
    call=provider.prepare('p','concurrent','提示词')
    async def run():return await asyncio.gather(*(provider.execute('p',call['id']) for _ in range(3)))
    results=asyncio.run(run())
    assert len(calls)==1 and all(r['status']=='completed' for r in results)
    assert len({r['result']['url'] for r in results})==1


@pytest.mark.parametrize('status,state',[(400,'rejected'),(401,'rejected'),(429,'rejected'),(408,'unknown'),(500,'unknown'),(302,'unknown')])
def test_http_errors_do_not_echo_credentials_or_implicitly_retry(tmp_path,status,state):
    calls=[]
    def handle(request):calls.append(request);return httpx.Response(status,headers={'location':'http://elsewhere/','x-request-id':'request-fixture'},json={'error':{'message':'fixture-secret'}})
    store,provider,_=fixture(tmp_path,handle)
    call=provider.prepare('p','error','提示词')
    result=asyncio.run(provider.execute('p',call['id']))
    assert result['status']==state
    assert result['result']['http_status']==status and result['result']['request_id']=='request-fixture'
    assert asyncio.run(provider.execute('p',call['id']))['status']==state and len(calls)==1
    with store.db() as db:assert 'fixture-secret' not in '\n'.join(db.iterdump())


def test_invalid_masks_and_unsupported_options_never_register_or_submit(tmp_path):
    calls=[]
    def handle(request):calls.append(request);return reply(request)
    store,provider,_=fixture(tmp_path,handle)
    with store.db() as db:
        url=store.file(db,'p','opaque.png',png(),'image/png');r=store.add(db,'p','asset','不透明图片',{'url':url})
    ref={'id':r['id'],'version':1}
    for args in [{'refs':[ref],'mask':ref},{'mask':ref},{'options':{'size':'1x1'}},{'options':{'hard_mask':'文字坐标'}}]:
        with pytest.raises(HTTPException):provider.prepare('p','invalid','提示词',**args)
    with store.db() as db:assert db.execute('SELECT count(*) FROM image_calls').fetchone()[0]==0
    assert not calls


def test_configuration_change_before_dispatch_is_not_silently_accepted(tmp_path):
    calls=[]
    def handle(request):calls.append(request);return reply(request)
    _,provider,config=fixture(tmp_path,handle)
    call=provider.prepare('p','config','提示词')
    config['model']='another-explicit-model'
    with pytest.raises(HTTPException):asyncio.run(provider.execute('p',call['id']))
    assert not calls


def test_mock_dependency_source_is_retained_in_image_receipt(tmp_path):
    store,provider,_=fixture(tmp_path,reply)
    with store.db() as db:
        url=store.file(db,'p','mock.png',png(),'image/png');r=store.add(db,'p','asset','模拟人物',{'url':url},'mock')
    call=provider.prepare('p','mock','提示词',refs=[{'id':r['id'],'version':1}])
    result=asyncio.run(provider.execute('p',call['id']))
    assert result['manifest']['source']=='mock' and result['result']['source']=='mock'


def test_semantically_identical_reference_maps_reuse_the_same_operation(tmp_path):
    store,provider,_=fixture(tmp_path,reply)
    with store.db() as db:
        url=store.file(db,'p','a.png',png(),'image/png');r=store.add(db,'p','asset','a',{'url':url})
    first=provider.prepare('p','canonical','提示词',refs=[{'id':r['id'],'version':1}])
    repeated=provider.prepare('p','canonical','提示词',refs=[{'version':1,'id':r['id']}])
    assert repeated['id']==first['id']


def test_application_registers_image_service_without_reading_real_credentials(tmp_path,monkeypatch):
    import backend.app as module
    reads=[]
    monkeypatch.setattr(module.vault,'get_password',lambda *args:reads.append(args))
    app=module.create_app(tmp_path)
    assert hasattr(app.state,'image_provider')
    assert reads==[]
    with app.state.store.db() as db:assert db.execute('SELECT count(*) FROM image_calls').fetchone()[0]==0


def test_registered_service_reaches_local_http_provider_and_publishes_owned_file(tmp_path,monkeypatch):
    import threading
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    from fastapi.testclient import TestClient
    import backend.app as module
    requests=[]
    class Provider(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            body=json.dumps({'data':[{'b64_json':base64.b64encode(png()).decode()}],'echo':'fixture-secret','fixture-secret':'key-echo'}).encode()
            self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.send_header('x-request-id','local-image-request');self.end_headers();self.wfile.write(body)
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Provider);threading.Thread(target=server.serve_forever,daemon=True).start()
    monkeypatch.setattr(module.vault,'get_password',lambda *args:'fixture-secret')
    try:
        app=module.create_app(tmp_path)
        with app.state.store.db() as db:
            db.execute("INSERT INTO projects VALUES('p','图像',0,'t','t')")
            db.execute('INSERT INTO settings VALUES(1,?)',(json.dumps({'image':{'url':f'http://127.0.0.1:{server.server_port}/v1','model':'gpt-image-1.5','api':'openai-images'}}),))
        with TestClient(app) as client:
            provider=app.state.image_provider
            call=provider.prepare('p','http','画一封密信')
            output=asyncio.run(provider.execute('p',call['id']))
            assert output['status']=='completed' and len(requests)==1
            assert client.get(output['result']['url']).content==png()
            assert output['result']['request_id']=='local-image-request'
            assert output['result']['usage'] is None and output['result']['checked'] is False
            assert 'fixture-secret' not in (provider.directory/(call['id']+'.json')).read_text()
            with app.state.store.db() as db:assert db.execute('SELECT count(*) FROM records').fetchone()[0]==0
    finally:server.shutdown();server.server_close()


def test_invalid_success_body_remains_unknown_with_traceable_request_id(tmp_path):
    calls=[]
    def handle(request):calls.append(request);return httpx.Response(200,headers={'x-request-id':'invalid-body-request'},content=b'fixture-secret not json')
    store,provider,_=fixture(tmp_path,handle)
    call=provider.prepare('p','invalid-response','提示词')
    result=asyncio.run(provider.execute('p',call['id']))
    assert result['status']=='unknown' and result['result']['request_id']=='invalid-body-request'
    assert asyncio.run(provider.execute('p',call['id']))['status']=='unknown' and len(calls)==1
    with store.db() as db:assert 'fixture-secret' not in '\n'.join(db.iterdump())


def test_foreign_project_cannot_read_or_execute_a_prepared_call(tmp_path):
    calls=[]
    def handle(request):calls.append(request);return reply(request)
    store,provider,_=fixture(tmp_path,handle)
    with store.db() as db:db.execute("INSERT INTO projects VALUES('other','乙',0,'t','t')")
    call=provider.prepare('p','isolation','提示词')
    with pytest.raises(HTTPException) as error:asyncio.run(provider.execute('other',call['id']))
    assert error.value.status_code==404 and not calls


def test_provider_change_during_credential_read_never_sends_new_key_to_old_endpoint(tmp_path):
    calls=[]
    def handle(request):calls.append(request);return reply(request)
    _,provider,config=fixture(tmp_path,handle)
    call=provider.prepare('p','credential-race','提示词')
    def changed_key():config['url']='http://other-provider/v1';return 'replacement-secret'
    provider.secret_get=changed_key
    with pytest.raises(HTTPException):asyncio.run(provider.execute('p',call['id']))
    assert not calls and provider.get('p',call['id'])['status']=='prepared'
