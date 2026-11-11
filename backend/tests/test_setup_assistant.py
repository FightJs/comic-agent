import json
import time
import pytest
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.tests.test_skills import pack


def fixture(tmp_path,monkeypatch,real_runtime=False):
    import backend.app as module
    class Vault:
        values={'text':'private-text-fixture','image':'private-image-fixture'}
        def get_password(self,service,key):return self.values.get(key.split(':')[-1])
        def set_password(self,service,key,value):self.values[key.split(':')[-1]]=value
        def delete_password(self,service,key):self.values.pop(key.split(':')[-1],None)
    vault=Vault();monkeypatch.setattr(module,'vault',vault);app=create_app(tmp_path);calls=[]
    with app.state.store.db() as db:db.execute('INSERT INTO settings VALUES(1,?)',(json.dumps({'text':{'purpose':'text','url':'http://127.0.0.1:1/v1','model':'fixture'}}),))
    original=app.state.pi_runtime.request
    async def request(command,**kwargs):
        if command!='setup':return await original(command,**kwargs)
        calls.append(kwargs)
        return {'type':'result','data':{'text':json.dumps(app.state.setup_reply,ensure_ascii=False),'usage':getattr(app.state,'setup_usage',None)}}
    if not real_runtime:monkeypatch.setattr(app.state.pi_runtime,'request',request)
    app.state.setup_reply={'reply':'建议核对后应用所附配置包。','actions':[{'kind':'apply_config','attachment':'config0'}]}
    return app,vault,calls


def wait(c,sid,rid):
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        value=c.get(f'/api/setup-assistant/sessions/{sid}').json()
        run=next(r for r in value['runs'] if r['id']==rid)
        if run['status'] not in ('queued','running'):return run
        time.sleep(.01)
    raise AssertionError('设置助手未结束')


def test_setup_assistant_proposes_configuration_without_exposing_or_applying_secrets(tmp_path,monkeypatch):
    app,vault,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        package={'format':'comic-config/v1','name':'生图设置','profiles':[{'purpose':'image','url':'http://image.invalid/v1','model':'image-fixture','api':'openai-images','secret':'new-image-package-key'}]}
        token=c.post('/api/config-packages/preview',content=json.dumps(package).encode()).json()['token']
        sid=c.post('/api/setup-assistant/sessions',json={}).json()['id']
        sent=c.post(f'/api/setup-assistant/sessions/{sid}/messages',json={'message':'帮我配置生图','expected_version':0,'config_tokens':[token]})
        assert sent.status_code==200,sent.text
        run=wait(c,sid,sent.json()['id'])
        assert run['status']=='completed' and run['actions'][0]['status']=='pending'
        assert vault.values['image']=='private-image-fixture'
        prompt=calls[0]['prompt']
        assert 'image-fixture' in prompt and 'new-image-package-key' not in prompt and 'private-image-fixture' not in prompt and token not in prompt
        action=run['actions'][0]
        applied=c.post(f"/api/setup-assistant/runs/{run['id']}/actions/{action['id']}/apply",json={})
        assert applied.status_code==200,applied.text
        assert vault.values['image']=='new-image-package-key'
        assert c.post(f"/api/setup-assistant/runs/{run['id']}/actions/{action['id']}/apply",json={}).status_code==200
        assert all(secret.encode() not in (tmp_path/'workbench.sqlite').read_bytes() for secret in ('new-image-package-key','private-text-fixture','private-image-fixture'))


def test_setup_skill_is_only_installed_and_enabled_after_separate_approval(tmp_path,monkeypatch):
    app,_,_=fixture(tmp_path,monkeypatch)
    app.state.setup_reply={'reply':'先安装，再启用此项目的审核流程。','actions':[{'kind':'install_skill','attachment':'skill0'},{'kind':'select_skills','handles':['skill0']}]}
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'小说'}).json()['id']
        preview=c.post('/api/setup-assistant/skill-packages/preview',content=json.dumps(pack(stages=['review'])).encode())
        assert preview.status_code==200,preview.text
        token=preview.json()['token'];assert c.get('/api/skills').json()==[]
        sid=c.post('/api/setup-assistant/sessions',json={'project_id':pid}).json()['id']
        sent=c.post(f'/api/setup-assistant/sessions/{sid}/messages',json={'message':'安装并启用这套一致性流程','expected_version':0,'skill_tokens':[token]})
        run=wait(c,sid,sent.json()['id']);assert run['status']=='completed'
        assert c.get('/api/skills').json()==[] and c.get(f'/api/projects/{pid}/skills').json()['hashes']==[]
        url=f"/api/setup-assistant/runs/{run['id']}/actions/"
        assert c.post(url+run['actions'][1]['id']+'/apply',json={}).status_code==409
        assert c.post(url+run['actions'][0]['id']+'/apply',json={}).status_code==200
        assert len(c.get('/api/skills').json())==1 and not c.get(f'/api/projects/{pid}/skills').json()['hashes']
        assert c.post(url+run['actions'][1]['id']+'/apply',json={}).status_code==200
        assert c.get(f'/api/projects/{pid}/skills').json()['hashes']==[preview.json()['hash']]


def test_setup_rejects_secret_chat_and_unauthorized_model_action(tmp_path,monkeypatch):
    app,_,calls=fixture(tmp_path,monkeypatch)
    app.state.setup_reply={'reply':'准备方案。','actions':[{'kind':'apply_config','attachment':'not-attached'}]}
    with TestClient(app) as c:
        sid=c.post('/api/setup-assistant/sessions',json={}).json()['id'];url=f'/api/setup-assistant/sessions/{sid}/messages'
        assert c.post(url,json={'message':'key=private-image-fixture','expected_version':0}).status_code==422
        assert not calls
        sent=c.post(url,json={'message':'检查系统配置缺项','expected_version':0})
        run=wait(c,sid,sent.json()['id']);assert run['status']=='invalid' and run['actions']==[]


def test_setup_redacts_other_provider_keys_even_in_response_field_names(tmp_path,monkeypatch):
    app,_,_=fixture(tmp_path,monkeypatch)
    app.state.setup_reply={'reply':'private-image-fixture 不应进入历史','actions':[]}
    app.state.setup_usage={'private-image-fixture':'private-text-fixture'}
    with TestClient(app) as c:
        sid=c.post('/api/setup-assistant/sessions',json={}).json()['id']
        sent=c.post(f'/api/setup-assistant/sessions/{sid}/messages',json={'message':'检查配置','expected_version':0})
        run=wait(c,sid,sent.json()['id'])
        assert run['status']=='completed' and 'private-image-fixture' not in json.dumps(run)
        assert b'private-image-fixture' not in (tmp_path/'workbench.sqlite').read_bytes()


def test_setup_bootstrap_and_stale_configuration_never_apply_implicitly(tmp_path,monkeypatch):
    app,vault,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        sid=c.post('/api/setup-assistant/sessions',json={}).json()['id'];url=f'/api/setup-assistant/sessions/{sid}/messages'
        with app.state.store.db() as db:db.execute('DELETE FROM settings')
        assert c.post(url,json={'message':'帮我配置','expected_version':0}).status_code==409 and not calls
        with app.state.store.db() as db:db.execute('INSERT INTO settings VALUES(1,?)',(json.dumps({'text':{'url':'http://127.0.0.1:1/v1','model':'fixture'}}),))
        token=c.post('/api/config-packages/preview',content=json.dumps({'format':'comic-config/v1','name':'图片包','profiles':[{'purpose':'image','url':'http://image.invalid/v1','model':'image','secret':'pending-image-key'}]}).encode()).json()['token']
        sent=c.post(url,json={'message':'应用此图片包','expected_version':0,'config_tokens':[token]});run=wait(c,sid,sent.json()['id'])
        c.put('/api/settings',json={'purpose':'text','url':'http://127.0.0.1:1/v1','model':'changed'})
        response=c.post(f"/api/setup-assistant/runs/{run['id']}/actions/{run['actions'][0]['id']}/apply",json={})
        assert response.status_code==409 and vault.values['image']=='private-image-fixture'


def test_setup_project_selection_conflict_preserves_current_user_choices(tmp_path,monkeypatch):
    app,_,_=fixture(tmp_path,monkeypatch)
    app.state.setup_reply={'reply':'可关闭当前项目流程，请核对。','actions':[{'kind':'select_skills','handles':[]}]}
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'项目'}).json()['id']
        sid=c.post('/api/setup-assistant/sessions',json={'project_id':pid}).json()['id']
        sent=c.post(f'/api/setup-assistant/sessions/{sid}/messages',json={'message':'关闭本项目所有流程','expected_version':0});run=wait(c,sid,sent.json()['id'])
        c.put(f'/api/projects/{pid}/skills',json={'expected_revision':0,'hashes':[]})
        assert c.post(f"/api/setup-assistant/runs/{run['id']}/actions/{run['actions'][0]['id']}/apply",json={}).status_code==409
        assert c.get(f'/api/projects/{pid}/skills').json()['revision']==1


def test_setup_shutdown_marks_capacity_waiters_interrupted(tmp_path,monkeypatch):
    import asyncio
    app,_,_=fixture(tmp_path,monkeypatch);original=app.state.pi_runtime.request
    async def request(command,**kwargs):
        if command=='setup':await asyncio.Event().wait()
        return await original(command,**kwargs)
    monkeypatch.setattr(app.state.pi_runtime,'request',request)
    with TestClient(app) as c:
        for _ in range(3):
            sid=c.post('/api/setup-assistant/sessions',json={}).json()['id']
            assert c.post(f'/api/setup-assistant/sessions/{sid}/messages',json={'message':'核对缺项','expected_version':0}).status_code==200
    with app.state.store.db() as db:assert {r['status'] for r in db.execute('SELECT status FROM setup_runs')}=={'interrupted'}


def test_setup_real_pi_sdk_uses_only_text_credential_and_keeps_other_keys_out_of_disk(tmp_path,monkeypatch):
    import threading
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    app,_,_=fixture(tmp_path,monkeypatch,real_runtime=True);requests=[]
    class Provider(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            requests.append((self.headers.get('Authorization'),json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
            answer=json.dumps({'reply':'private-image-fixture 仅为恶意回显测试，不能保存','actions':[]})
            for delta,finish in [({'role':'assistant','content':answer},None),({},'stop')]:
                event={'id':'setup','object':'chat.completion.chunk','created':1,'model':'fixture','choices':[{'index':0,'delta':delta,'finish_reason':finish}]}
                self.wfile.write(('data: '+json.dumps(event)+'\n\n').encode())
            self.wfile.write(b'data: [DONE]\n\n')
    server=ThreadingHTTPServer(('127.0.0.1',0),Provider);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with app.state.store.db() as db:db.execute('UPDATE settings SET content=?',(json.dumps({'text':{'url':f'http://127.0.0.1:{server.server_port}/v1','model':'fixture'}}),))
        with TestClient(app) as c:
            sid=c.post('/api/setup-assistant/sessions',json={}).json()['id']
            sent=c.post(f'/api/setup-assistant/sessions/{sid}/messages',json={'message':'核对配置缺项','expected_version':0})
            done=wait(c,sid,sent.json()['id']);assert done['status']=='completed',done
            assert '[REDACTED]' in done['reply'] and done['usage'] is None
        assert len(requests)==1 and requests[0][0]=='Bearer private-text-fixture'
        assert 'private-image-fixture' not in json.dumps(requests[0][1]) and [t['function']['name'] for t in requests[0][1]['tools']]==['setup_catalog']
        assert not list((tmp_path/'agent').rglob('*.jsonl'))
        assert b'private-image-fixture' not in (tmp_path/'workbench.sqlite').read_bytes()
    finally:server.shutdown();server.server_close();thread.join()


def test_setup_cancel_preserves_late_return_without_publishing_actions(tmp_path,monkeypatch):
    import asyncio
    import threading
    app,_,_=fixture(tmp_path,monkeypatch);release=threading.Event();entered=threading.Event();original=app.state.pi_runtime.request
    async def request(command,**kwargs):
        if command!='setup':return await original(command,**kwargs)
        entered.set()
        while not release.is_set():await asyncio.sleep(.01)
        return {'type':'result','data':{'text':json.dumps({'reply':'迟到回复','actions':[]}), 'usage':None}}
    monkeypatch.setattr(app.state.pi_runtime,'request',request)
    with TestClient(app) as c:
        sid=c.post('/api/setup-assistant/sessions',json={}).json()['id']
        sent=c.post(f'/api/setup-assistant/sessions/{sid}/messages',json={'message':'核对配置','expected_version':0});rid=sent.json()['id']
        assert entered.wait(2)
        assert c.post(f'/api/setup-assistant/runs/{rid}/cancel',json={}).json()['status']=='cancelled'
        release.set();deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            run=c.get(f'/api/setup-assistant/sessions/{sid}').json()['runs'][0]
            if run['raw'] is not None:break
            time.sleep(.01)
        assert run['status']=='cancelled' and run['raw'] and run['actions']==[] and run['reply']==''


def test_setup_keychain_wait_does_not_block_basic_project_reads(tmp_path,monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    app,vault,_=fixture(tmp_path,monkeypatch);entered=threading.Event();release=threading.Event();original=vault.get_password
    def waiting(service,key):
        if key.endswith(':text'):entered.set();release.wait(3)
        return original(service,key)
    monkeypatch.setattr(vault,'get_password',waiting)
    with TestClient(app) as c,ThreadPoolExecutor(max_workers=2) as pool:
        sid=c.post('/api/setup-assistant/sessions',json={}).json()['id']
        sending=pool.submit(c.post,f'/api/setup-assistant/sessions/{sid}/messages',json={'message':'核对系统','expected_version':0})
        assert entered.wait(2)
        reading=pool.submit(c.get,'/api/projects')
        try:assert reading.result(timeout=.5).status_code==200
        finally:release.set();sending.result(timeout=5)


def test_setup_rejected_action_cannot_later_be_applied(tmp_path,monkeypatch):
    app,_,_=fixture(tmp_path,monkeypatch);app.state.setup_reply={'reply':'可清空项目流程，待核对。','actions':[{'kind':'select_skills','handles':[]}]}
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'拒绝方案'}).json()['id'];sid=c.post('/api/setup-assistant/sessions',json={'project_id':pid}).json()['id']
        sent=c.post(f'/api/setup-assistant/sessions/{sid}/messages',json={'message':'关闭项目流程','expected_version':0});run=wait(c,sid,sent.json()['id'])
        url=f"/api/setup-assistant/runs/{run['id']}/actions/{run['actions'][0]['id']}"
        response=c.post(url+'/reject',json={});assert response.status_code==200,response.text
        assert response.json()['actions'][0]['status']=='rejected'
        assert c.post(url+'/apply',json={}).status_code==409
        assert c.get(f'/api/projects/{pid}/skills').json()['revision']==0


def test_setup_freezes_only_bound_projects_enabled_setup_rules(tmp_path,monkeypatch):
    app,_,calls=fixture(tmp_path,monkeypatch)
    app.state.setup_reply={'reply':'依据当前项目配置流程核对。','actions':[]}
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'配置规则项目'}).json()['id']
        other=c.post('/api/projects',json={'name':'其他项目'}).json()['id']
        setup=pack(stages=['setup']);setup['files'][setup['entrypoint']]='先解释一致性用途，不自动启用。private-image-fixture'
        digest=c.post('/api/skills/import',content=json.dumps(setup).encode()).json()['hash']
        assert c.put(f'/api/projects/{pid}/skills',json={'expected_revision':0,'hashes':[digest]}).status_code==200
        for project in (pid,other,None):
            sid=c.post('/api/setup-assistant/sessions',json={'project_id':project} if project else {}).json()['id']
            sent=c.post(f'/api/setup-assistant/sessions/{sid}/messages',json={'message':'检查配置流程','expected_version':0})
            run=wait(c,sid,sent.json()['id']);assert run['status']=='completed'
            rules=run['public_input']['setup_rules']
            if project==pid:
                assert rules['skills'][0]['hash']==digest
                assert '先解释一致性用途' in rules['instructions']
                assert 'private-image-fixture' not in json.dumps(rules)
                assert rules==json.loads(calls[-1]['prompt'])['snapshot']['setup_rules']
                assert c.put(f'/api/projects/{pid}/skills',json={'expected_revision':1,'hashes':[]}).status_code==200
                assert c.get(f'/api/setup-assistant/sessions/{sid}').json()['runs'][0]['public_input']['setup_rules']==rules
            else:assert rules=={'skills':[],'instructions':''}


def test_setup_loads_linked_resources_once_and_excludes_unreferenced_or_other_stage(tmp_path,monkeypatch):
    app,_,calls=fixture(tmp_path,monkeypatch);app.state.setup_reply={'reply':'依据固定流程资料核对。','actions':[]}
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'引用流程'}).json()['id']
        bundle=pack(stages=['setup'],files={'SKILL.md':'先读[资料](references/a.md)。','references/a.md':'唯一配置说明 private-image-fixture [循环](../SKILL.md) [外部](https://example.invalid/no-fetch)','unused.md':'不应读未引用资料'})
        digest=c.post('/api/skills/import',content=json.dumps(bundle).encode()).json()['hash']
        other=c.post('/api/skills/import',content=json.dumps(pack(id='review-only',stages=['review'],files={'SKILL.md':'不应读审核阶段'})).encode()).json()['hash']
        c.put(f'/api/projects/{pid}/skills',json={'expected_revision':0,'hashes':[digest,other]})
        sid=c.post('/api/setup-assistant/sessions',json={'project_id':pid}).json()['id']
        sent=c.post(f'/api/setup-assistant/sessions/{sid}/messages',json={'message':'按本项目配置流程说明','expected_version':0});run=wait(c,sid,sent.json()['id'])
        assert run['status']=='completed'
        rules=run['public_input']['setup_rules'];text=rules['instructions']
        assert text.count('唯一配置说明')==1
        assert 'private-image-fixture' not in text and '[REDACTED]' in text
        assert '不应读未引用资料' not in text and '不应读审核阶段' not in text
        assert rules['skills'][0]['resource_paths']==['SKILL.md','references/a.md']
        assert json.loads(calls[-1]['prompt'])['snapshot']['setup_rules']==rules


@pytest.mark.parametrize('damage',['missing','oversize'])
def test_setup_refuses_incomplete_or_oversized_linked_rules_without_sending(tmp_path,monkeypatch,damage):
    app,_,calls=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'规则完整性'}).json()['id']
        digest=c.post('/api/skills/import',content=json.dumps(pack(stages=['setup'],files={'SKILL.md':'读[资料](rules.txt)','rules.txt':'完整规则'})).encode()).json()['hash']
        c.put(f'/api/projects/{pid}/skills',json={'expected_revision':0,'hashes':[digest]})
        with app.state.store.db() as db:
            if damage=='missing':db.execute('DELETE FROM skill_files WHERE hash=? AND path=?',(digest,'rules.txt'))
            else:db.execute('UPDATE skill_files SET content=? WHERE hash=? AND path=?',('长'*80000,digest,'rules.txt'))
        sid=c.post('/api/setup-assistant/sessions',json={'project_id':pid}).json()['id']
        response=c.post(f'/api/setup-assistant/sessions/{sid}/messages',json={'message':'依据配置流程核对','expected_version':0})
        assert response.status_code==422,response.text
        assert not calls
        session=c.get(f'/api/setup-assistant/sessions/{sid}').json()
        assert session['version']==0 and session['runs']==[]


def test_setup_catalog_tool_can_find_frozen_items_beyond_first_page(tmp_path,monkeypatch):
    app,_,_=fixture(tmp_path,monkeypatch)
    from backend.skills import install
    items=[install(app.state.store,pack(id=f'flow-{i}',name=f'流程{i}')) for i in range(55)]
    wanted=items[0];seen=[];original=app.state.pi_runtime.request
    async def request(command,**kwargs):
        if command!='setup':return await original(command,**kwargs)
        install(app.state.store,pack(id='new-after-freeze',name='流程0新安装'))
        query=await kwargs['on_tool']({'name':'setup_catalog','arguments':{'query':'流程0','start':0,'limit':5}})
        seen.append(query)
        return {'type':'result','data':{'text':json.dumps({'reply':'找到所需流程，待核对启用。','actions':[{'kind':'select_skills','handles':['installed:'+wanted['hash']]}]}),'usage':None}}
    monkeypatch.setattr(app.state.pi_runtime,'request',request)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'大流程库'}).json()['id'];sid=c.post('/api/setup-assistant/sessions',json={'project_id':pid}).json()['id']
        sent=c.post(f'/api/setup-assistant/sessions/{sid}/messages',json={'message':'找流程0并提出启用方案','expected_version':0});run=wait(c,sid,sent.json()['id'])
        assert run['status']=='completed',run
        assert seen[0]['items'][0]['hash']==wanted['hash'] and seen[0]['total']==1
        assert run['public_input']['catalog_reads'][0]['query']=='流程0'
        assert run['actions'][0]['display']['skills'][0]['hash']==wanted['hash']
        assert c.get(f'/api/projects/{pid}/skills').json()['hashes']==[]


@pytest.mark.parametrize('repeat',[False,True])
@pytest.mark.parametrize('source',['installed','bundled'])
def test_setup_real_sdk_queries_catalog_without_persisting_node_history(tmp_path,monkeypatch,repeat,source):
    import threading
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    from backend.skills import install
    app,_,_=fixture(tmp_path,monkeypatch,real_runtime=True);requests=[]
    if source=='installed':wanted=install(app.state.store,pack(id='searched',name='查询测试流程'))
    else:
        from backend.bundled_skills import bundled_packages
        digest,bundle=next(iter(bundled_packages().items()));wanted={'hash':digest,'id':bundle['id']}
    proposal={'kind':'select_skills','handles':['installed:'+wanted['hash']]} if source=='installed' else {'kind':'install_skill','attachment':'bundled:'+wanted['hash']}
    class Provider(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append(body)
            first=repeat or len(requests)==1
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
            delta={'role':'assistant','tool_calls':[{'index':0,'id':'catalog-call','type':'function','function':{'name':'setup_catalog','arguments':json.dumps({'source':source,'query':wanted['id'],'limit':5})}}]} if first else {'role':'assistant','content':json.dumps({'reply':'private-image-fixture 查询到流程，待明确启用。','actions':[proposal]})}
            for part,finish in [(delta,None),({},'tool_calls' if first else 'stop')]:
                event={'id':'catalog','object':'chat.completion.chunk','created':1,'model':'fixture','choices':[{'index':0,'delta':part,'finish_reason':finish}]}
                self.wfile.write(('data: '+json.dumps(event)+'\n\n').encode())
            self.wfile.write(b'data: [DONE]\n\n')
    server=ThreadingHTTPServer(('127.0.0.1',0),Provider);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with app.state.store.db() as db:db.execute('UPDATE settings SET content=?',(json.dumps({'text':{'url':f'http://127.0.0.1:{server.server_port}/v1','model':'fixture'}}),))
        with TestClient(app) as c:
            pid=c.post('/api/projects',json={'name':'真实工具链'}).json()['id'];sid=c.post('/api/setup-assistant/sessions',json={'project_id':pid}).json()['id']
            sent=c.post(f'/api/setup-assistant/sessions/{sid}/messages',json={'message':'查询测试流程并提出启用方案','expected_version':0});run=wait(c,sid,sent.json()['id'])
            assert run['status']==('interrupted' if repeat else 'completed'),run
            assert len(run['public_input']['catalog_reads'])==(8 if repeat else 1)
            assert run['public_input']['catalog_reads'][0]['items'][0]['hash']==wanted['hash']
            assert c.get(f'/api/projects/{pid}/skills').json()['hashes']==[]
            assert 'private-image-fixture' not in json.dumps(run)
        assert len(requests)==(8 if repeat else 2)
        assert [t['function']['name'] for t in requests[0]['tools']]==['setup_catalog']
        assert any(m['role']=='tool' and wanted['hash'] in m['content'] for m in requests[1]['messages'])
        assert not [p for p in (tmp_path/'agent').rglob('*') if p.is_file()]
        assert b'private-image-fixture' not in (tmp_path/'workbench.sqlite').read_bytes()
    finally:server.shutdown();server.server_close();thread.join()


@pytest.mark.parametrize('tool,args',[('project_query',{}),('setup_catalog',{'path':'/etc/passwd'}),('setup_catalog',{'source':'filesystem'}),('setup_catalog',{'start':True}),('setup_catalog',{'limit':51}),('setup_catalog',{'query':'private-image-fixture'})])
def test_setup_catalog_denies_other_tools_unknown_fields_and_secret_queries(tmp_path,monkeypatch,tool,args):
    app,_,_=fixture(tmp_path,monkeypatch);original=app.state.pi_runtime.request
    async def request(command,**kwargs):
        if command!='setup':return await original(command,**kwargs)
        with pytest.raises(ValueError):await kwargs['on_tool']({'name':tool,'arguments':args})
        return {'type':'result','data':{'text':json.dumps({'reply':'仅可查询流程目录。','actions':[]}), 'usage':None}}
    monkeypatch.setattr(app.state.pi_runtime,'request',request)
    with TestClient(app) as c:
        sid=c.post('/api/setup-assistant/sessions',json={}).json()['id']
        sent=c.post(f'/api/setup-assistant/sessions/{sid}/messages',json={'message':'检查流程目录','expected_version':0});run=wait(c,sid,sent.json()['id'])
        assert run['status']=='completed' and run['public_input']['catalog_reads']==[]


def test_setup_installs_bundled_five_only_after_explicit_individual_adoption(tmp_path,monkeypatch):
    app,_,_=fixture(tmp_path,monkeypatch);original=app.state.pi_runtime.request;catalog=[]
    async def request(command,**kwargs):
        if command!='setup':return await original(command,**kwargs)
        result=await kwargs['on_tool']({'name':'setup_catalog','arguments':{'source':'bundled','limit':10}})
        catalog.extend(result['items']);handles=[item['handle'] for item in catalog]
        actions=[{'kind':'install_skill','attachment':handle} for handle in handles]+[{'kind':'select_skills','handles':handles}]
        return {'type':'result','data':{'text':json.dumps({'reply':'内置首版规则可安装，尚未执行。','actions':actions}), 'usage':None}}
    monkeypatch.setattr(app.state.pi_runtime,'request',request)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'内置规则'}).json()['id'];sid=c.post('/api/setup-assistant/sessions',json={'project_id':pid}).json()['id']
        sent=c.post(f'/api/setup-assistant/sessions/{sid}/messages',json={'message':'安装内置五件套并启用','expected_version':0});run=wait(c,sid,sent.json()['id'])
        assert run['status']=='completed',run
        assert len(catalog)==5 and all(item['handle'].startswith('bundled:') for item in catalog)
        assert len(run['actions'])==6 and c.get('/api/skills').json()==[]
        assert all(a['display']['origin']=='bundled_rules_first_pass' for a in run['actions'][:5])
        url=f"/api/setup-assistant/runs/{run['id']}/actions/"
        assert c.post(url+run['actions'][-1]['id']+'/apply',json={}).status_code==409
        for action in run['actions'][:5]:
            assert c.post(url+action['id']+'/apply',json={}).status_code==200
            assert c.post(url+action['id']+'/apply',json={}).status_code==200
        assert len(c.get('/api/skills').json())==5
        assert c.get(f'/api/projects/{pid}/skills').json()['hashes']==[]
        assert c.post(url+run['actions'][-1]['id']+'/apply',json={}).status_code==200
        assert c.get(f'/api/projects/{pid}/skills').json()['hashes']==[item['hash'] for item in catalog]


def test_bundled_candidate_survives_restart_and_never_reads_updated_repository_on_apply(tmp_path,monkeypatch):
    import backend.setup_assistant as setup
    app,_,_=fixture(tmp_path,monkeypatch);original=app.state.pi_runtime.request
    async def request(command,**kwargs):
        if command!='setup':return await original(command,**kwargs)
        item=(await kwargs['on_tool']({'name':'setup_catalog','arguments':{'source':'bundled','limit':1}}))['items'][0]
        return {'type':'result','data':{'text':json.dumps({'reply':'只安装已核对的内置首版。','actions':[{'kind':'install_skill','attachment':item['handle']}]}),'usage':None}}
    monkeypatch.setattr(app.state.pi_runtime,'request',request)
    with TestClient(app) as c:
        sid=c.post('/api/setup-assistant/sessions',json={}).json()['id']
        sent=c.post(f'/api/setup-assistant/sessions/{sid}/messages',json={'message':'安装内置规则','expected_version':0});run=wait(c,sid,sent.json()['id'])
        assert run['status']=='completed'
    def unavailable():raise AssertionError('apply must not reload repository')
    monkeypatch.setattr(setup,'bundled_packages',unavailable)
    with TestClient(create_app(tmp_path)) as c:
        response=c.post(f"/api/setup-assistant/runs/{run['id']}/actions/{run['actions'][0]['id']}/apply",json={})
        assert response.status_code==200,response.text
        assert c.get('/api/skills').json()[0]['hash']==run['actions'][0]['display']['hash']


def test_guessing_an_unqueried_bundled_handle_is_not_authorized(tmp_path,monkeypatch):
    from backend.bundled_skills import bundled_packages
    app,_,_=fixture(tmp_path,monkeypatch);digest=next(iter(bundled_packages()))
    app.state.setup_reply={'reply':'虚构未读引用','actions':[{'kind':'install_skill','attachment':'bundled:'+digest}]}
    with TestClient(app) as c:
        sid=c.post('/api/setup-assistant/sessions',json={}).json()['id']
        sent=c.post(f'/api/setup-assistant/sessions/{sid}/messages',json={'message':'看看有什么内置规则','expected_version':0});run=wait(c,sid,sent.json()['id'])
        assert run['status']=='invalid' and run['actions']==[] and c.get('/api/skills').json()==[]
