import json,hashlib
import pytest
from fastapi import HTTPException
from backend.tests.test_skills import client,install,pack
from backend.agent_tools import freeze_context,ProjectTools
from backend.skills import frozen_skills,freeze_stage_resources,stage_instructions


def library(**overrides):return pack(**{'id':'shared','name':'公共约束库','stages':['review'],'files':{'SKILL.md':'这个审核主流程不应在script阶段自动加载。','rules/common.md':'固定人物身份。见[细则](detail.md)。','rules/detail.md':'保持衣装状态连续。'},**overrides})
def workflow(**overrides):return pack(**{'id':'author','stages':['script'],'dependencies':[{'id':'shared','version':'1.0'}],'files':{'SKILL.md':'本阶段正文。见[公共约束](skill://shared@1.0/rules/common.md)。'},**overrides})

def project(c):return c.post('/api/projects',json={'name':'引用测试'}).json()['id']
def select(c,p,hashes,revision=0):return c.put(f'/api/projects/{p}/skills',json={'expected_revision':revision,'hashes':hashes})


def test_cross_package_selection_is_explicit_and_wrong_versions_do_not_satisfy_dependencies(client):
    root=install(client,workflow());assert root.status_code==200,root.text
    p=project(client)
    response=select(client,p,[root.json()['hash']]);assert response.status_code==422,response.text
    assert client.get(f'/api/projects/{p}/skills').json()=={'revision':0,'hashes':[]}
    wrong=install(client,library(version='2')).json()
    assert select(client,p,[root.json()['hash'],wrong['hash']]).status_code==422
    correct=install(client,library()).json()
    assert select(client,p,[root.json()['hash'],correct['hash']]).status_code==200


def test_frozen_dependencies_are_readable_without_loading_another_stages_main_rules(client):
    root=install(client,workflow()).json();dep=install(client,library()).json();p=project(client)
    assert select(client,p,[root['hash'],dep['hash']]).status_code==200
    with client.app.state.store.db() as db:
        frozen=freeze_context(client.app.state.store,db,p,stage='script');rules=stage_instructions(db,frozen['skills'])
    assert root['hash'] in rules and dep['hash'] in rules
    assert '这个审核主流程不应' not in rules
    assert next(s for s in frozen['skills'] if s['hash']==dep['hash'])['resource_only']
    assert select(client,p,[],1).status_code==200
    tool=ProjectTools(client.app.state.store,p,frozen)
    result=tool.call('project_query',{'action':'skill','id':root['hash'],'query':'skill://shared@1.0/rules/common.md'})
    assert result['hash']==dep['hash'] and '固定人物身份' in result['text']
    assert '保持衣装' in tool.call('project_query',{'action':'skill','id':dep['hash'],'query':'rules/detail.md'})['text']
    other=project(client)
    with client.app.state.store.db() as db:foreign=freeze_context(client.app.state.store,db,other,stage='script')
    with pytest.raises(HTTPException):ProjectTools(client.app.state.store,other,foreign).call('project_query',{'action':'skill','id':root['hash'],'query':'skill://shared@1.0/rules/common.md'})


def test_stage_rule_closure_crosses_packages_and_preserves_relative_resource_paths(client):
    dep=install(client,library()).json();root=install(client,workflow(stages=['setup'])).json();p=project(client)
    select(client,p,[root['hash'],dep['hash']])
    with client.app.state.store.db() as db:closed=freeze_stage_resources(client.app.state.store,db,p,'setup')
    texts=[r['text'] for info in closed for r in info['resources']]
    assert any('固定人物身份' in text for text in texts)
    assert any('保持衣装' in text for text in texts)
    assert not any('这个审核主流程不应' in text for text in texts)


@pytest.mark.parametrize('target',['skill://shared@latest/rules/common.md','skill://shared@1.0/%2e%2e/private.md','skill://shared@1.0/rules/common.md?run=1','skill://undeclared@1.0/SKILL.md'])
def test_unpinned_undeclared_and_escaping_references_do_not_install(client,target):
    response=install(client,workflow(files={'SKILL.md':f'运行约束见[x]({target})。'}))
    assert response.status_code==422,response.text


def test_missing_target_file_blocks_selection_and_does_not_change_old_project_rules(client):
    root=install(client,workflow(files={'SKILL.md':'参见[x](skill://shared@1.0/missing.md)。'})).json();dep=install(client,library()).json();p=project(client)
    response=select(client,p,[root['hash'],dep['hash']]);assert response.status_code==422,response.text
    assert client.get(f'/api/projects/{p}/skills').json()['revision']==0


def test_legacy_packages_keep_their_original_canonical_hash(client):
    body=pack();expected=hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    installed=install(client,body);assert installed.status_code==200,installed.text
    assert installed.json()['hash']==expected
    assert not installed.json().get('dependencies')

def test_transitive_reference_cycles_are_bounded_and_do_not_enable_main_flows(client):
    root=install(client,workflow()).json()
    middle=install(client,library(dependencies=[{'id':'third','version':'1.0'}],files={'SKILL.md':'不自动加载middle主流程','rules/common.md':'身份约束。[后续](skill://third@1.0/rules/c.md)'})).json()
    last=install(client,pack(id='third',stages=['style'],dependencies=[{'id':'author','version':'1.0'}],files={'SKILL.md':'不自动加载third主流程','rules/c.md':'[回入口](skill://author@1.0/SKILL.md)'})).json()
    p=project(client);assert select(client,p,[root['hash'],middle['hash'],last['hash']]).status_code==200
    with client.app.state.store.db() as db:closed=freeze_stage_resources(client.app.state.store,db,p,'script')
    assert sum(len(item['resources']) for item in closed)==3
    assert not any('不自动加载' in r['text'] for item in closed for r in item['resources'])


def test_setup_assistant_apply_cannot_bypass_dependency_selection(tmp_path,monkeypatch):
    from backend.tests.test_setup_assistant import fixture,wait
    from fastapi.testclient import TestClient
    app,_,_=fixture(tmp_path,monkeypatch)
    with TestClient(app) as c:
        root=install(c,workflow()).json();dep=install(c,library()).json();p=project(c)
        app.state.setup_reply={'reply':'先核对项目依赖。','actions':[{'kind':'select_skills','handles':['installed:'+root['hash']]}]}
        sid=c.post('/api/setup-assistant/sessions',json={'project_id':p}).json()['id']
        first=c.post(f'/api/setup-assistant/sessions/{sid}/messages',json={'message':'启用主流程','expected_version':0}).json()
        candidate=wait(c,sid,first['id']);action=candidate['actions'][0]
        assert c.post(f"/api/setup-assistant/runs/{first['id']}/actions/{action['id']}/apply",json={}).status_code==422
        assert c.get(f'/api/projects/{p}/skills').json()['revision']==0
        app.state.setup_reply={'reply':'同时核对两个固定版本。','actions':[{'kind':'select_skills','handles':['installed:'+root['hash'],'installed:'+dep['hash']]}]}
        sent=c.post(f'/api/setup-assistant/sessions/{sid}/messages',json={'message':'包括依赖再启用','expected_version':1}).json()
        candidate=wait(c,sid,sent['id']);action=candidate['actions'][0]
        assert c.post(f"/api/setup-assistant/runs/{sent['id']}/actions/{action['id']}/apply",json={}).status_code==200


def test_actual_sdk_can_query_a_fixed_cross_package_resource(tmp_path,monkeypatch):
    import threading,time
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    from fastapi.testclient import TestClient
    from backend.app import create_app
    import backend.app as module
    requests=[]
    class Provider(BaseHTTPRequestHandler):
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append(body)
            has_tool=any(m['role']=='tool' for m in body['messages'])
            delta={'role':'assistant','content':'已按固定引用读取身份约束，尚未修改作品。'} if has_tool else {'role':'assistant','tool_calls':[{'index':0,'id':'cross-read','type':'function','function':{'name':'project_query','arguments':json.dumps({'action':'skill','id':root['hash'],'query':'skill://shared@1.0/rules/common.md'})}}]}
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
            for part in [{'choices':[{'index':0,'delta':delta,'finish_reason':None}]},{'choices':[{'index':0,'delta':{},'finish_reason':'stop' if has_tool else 'tool_calls'}]}]:
                self.wfile.write(('data: '+json.dumps({'id':'fixture','object':'chat.completion.chunk','created':1,'model':'fixture',**part})+'\n\n').encode())
            self.wfile.write(b'data: [DONE]\n\n')
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Provider);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    monkeypatch.setattr(module.vault,'get_password',lambda *args:'synthetic-cross-key')
    try:
        with TestClient(create_app(tmp_path)) as c:
            root=install(c,workflow()).json();dep=install(c,library()).json();p=project(c);select(c,p,[root['hash'],dep['hash']])
            with c.app.state.store.db() as db:db.execute('INSERT INTO settings VALUES(1,?)',(json.dumps({'text':{'url':f'http://127.0.0.1:{server.server_port}/v1','model':'fixture'}}),))
            base=f'/api/projects/{p}';sid=c.post(base+'/agent/sessions',json={'stage':'script'}).json()['id']
            sent=c.post(base+f'/agent/sessions/{sid}/messages',json={'message':'读取本次跨包约束','expected_version':0});assert sent.status_code==200,sent.text
            rid=sent.json()['id'];deadline=time.monotonic()+15
            while time.monotonic()<deadline:
                value=c.get(base+f'/agent/runs/{rid}').json()
                if value['status'] not in ('queued','running'):break
                time.sleep(.02)
            assert value['status']=='completed',value
            assert len(requests)==2
            assert '这个审核主流程不应' not in json.dumps(requests[0],ensure_ascii=False)
            assert '固定人物身份' in json.dumps(requests[1],ensure_ascii=False)
            assert next(i for i in value['skills'] if i['hash']==dep['hash'])['resource_only']
    finally:server.shutdown();server.server_close();thread.join()

def test_repeated_references_do_not_amplify_frozen_metadata(client):
    repeated='[约束](skill://shared@1.0/rules/common.md)\n'*200
    response=install(client,workflow(files={'SKILL.md':repeated}));assert response.status_code==200,response.text
    assert len(response.json()['cross_references'])==1


def test_cross_package_edge_count_is_bounded_before_installation(client):
    text='\n'.join(f'[资料](skill://shared@1.0/rules/{i}.md)' for i in range(1501))
    response=install(client,workflow(files={'SKILL.md':'固定入口','references/many.md':text}))
    assert response.status_code==422,response.text
