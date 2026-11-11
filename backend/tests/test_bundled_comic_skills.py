"""Portable rule packages; no access to the developer's personal skill install."""
import hashlib
import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.skills import SkillPackage,freeze_stage_resources

ROOT=Path(__file__).resolve().parents[2]


def test_five_bundles_are_reproducible_valid_and_frozen_without_personal_paths(tmp_path):
    from scripts.build_comic_skills import build
    built=build(ROOT/'resources/comic-skills')
    assert set(built)=={'comic-preproduction','comic-visual-assets','comic-shot-design','comic-panel-generation','comic-image-review'}
    app=create_app(tmp_path)
    with TestClient(app) as c:
        pid=c.post('/api/projects',json={'name':'可移植规则'}).json()['id'];hashes=[]
        for name,body in built.items():
            assert body==json.loads((ROOT/'resources/comic-skills/packages'/f'{name}.json').read_text())
            SkillPackage.model_validate(body)
            assert '/Users/' not in json.dumps(body) and '.codex/' not in json.dumps(body)
            assert all(Path(path).suffix in ('.md','.json') for path in body['files'])
            imported=c.post('/api/skills/import',content=json.dumps(body).encode());assert imported.status_code==200,imported.text
            hashes.append(imported.json()['hash'])
            assert c.post('/api/skills/import',content=json.dumps(body).encode()).json()['hash']==hashes[-1]
        assert c.get(f'/api/projects/{pid}/skills').json()['hashes']==[]
        assert c.put(f'/api/projects/{pid}/skills',json={'expected_revision':0,'hashes':hashes}).status_code==200
        with app.state.store.db() as db:
            for stage in ('setup','style','asset','package','image','review'):
                rules=freeze_stage_resources(app.state.store,db,pid,stage)
                assert rules,stage
                assert sum(len(r['text']) for info in rules for r in info['resources'])<=80000
                assert any('候选' in r['text'] for info in rules for r in info['resources'])
                assert all('generation_host.py' not in r['text'] and 'imagegen' not in r['text'] for info in rules for r in info['resources'])
        assert not list(tmp_path.rglob('*.png'))


def test_source_rule_integrity_is_checked_before_build(tmp_path):
    import shutil
    from scripts.build_comic_skills import build
    source=tmp_path/'source';shutil.copytree(ROOT/'resources/comic-skills',source)
    rule=next((source/'rules').glob('*.md'));rule.write_text(rule.read_text()+'\nchanged')
    import pytest
    with pytest.raises(ValueError,match='source_hash'):build(source)


@pytest.mark.parametrize('resource,needle',[('rules/MEM-008.md','无可辨认人物或场景倒影'),('references/shot-framing.md','胸上裁切不能声称看见腰部'),('references/appearance-and-single-frame.md','总数2而只见自身左耳时，可见1'),('references/control-guidance.md','不能推断已执行ControlNet'),('references/final-input-semantics.md','不能在末尾追加更强相反命令')])
def test_migrated_rule_reaches_real_pi_tool_request(tmp_path,monkeypatch,resource,needle):
    import threading,time
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    import backend.app as module
    calls=[];skill={}
    class Provider(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));calls.append(body)
            tool=not any(m['role']=='tool' for m in body['messages'])
            delta={'role':'assistant','tool_calls':[{'index':0,'id':'mirror-rule','type':'function','function':{'name':'project_query','arguments':json.dumps({'action':'skill','id':skill['hash'],'query':resource})}}]} if tool else {'role':'assistant','content':'已读取指定固定资料；此本机替身只验证引用链，未生成图片。'}
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
            for value,finish in [(delta,None),({},'tool_calls' if tool else 'stop')]:
                chunk={'id':'fixture','object':'chat.completion.chunk','created':1,'model':'fixture','choices':[{'index':0,'delta':value,'finish_reason':finish}]}
                self.wfile.write(('data: '+json.dumps(chunk)+'\n\n').encode())
            self.wfile.write(b'data: [DONE]\n\n')
    server=ThreadingHTTPServer(('127.0.0.1',0),Provider);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    monkeypatch.setattr(module.vault,'get_password',lambda *args:'synthetic-migration-key')
    try:
        with TestClient(create_app(tmp_path)) as c:
            pid=c.post('/api/projects',json={'name':'镜面规则接线'}).json()['id'];base=f'/api/projects/{pid}'
            body=json.loads((ROOT/'resources/comic-skills/packages/comic-shot-design.json').read_text())
            skill.update(c.post('/api/skills/import',content=json.dumps(body).encode()).json())
            c.put(base+'/skills',json={'expected_revision':0,'hashes':[skill['hash']]})
            with c.app.state.store.db() as db:db.execute('INSERT INTO settings VALUES(1,?)',(json.dumps({'text':{'url':f'http://127.0.0.1:{server.server_port}/v1','model':'fixture'}}),))
            sid=c.post(base+'/agent/sessions',json={'stage':'package'}).json()['id']
            sent=c.post(base+f'/agent/sessions/{sid}/messages',json={'message':'核对镜面提示词规则','expected_version':0});assert sent.status_code==200,sent.text
            deadline=time.monotonic()+10
            while time.monotonic()<deadline:
                done=c.get(base+'/agent/runs/'+sent.json()['id']).json()
                if done['status'] not in ('queued','running'):break
                time.sleep(.02)
            assert done['status']=='completed',done
            assert len(calls)==2 and '条漫镜头与物理空间' in json.dumps(calls[0],ensure_ascii=False)
            assert any(m['role']=='tool' and needle in m['content'] for m in calls[1]['messages'])
            assert c.get(base+'/tasks').json()==[] and c.get(base+'/records').json()==[]
            assert done['skills'][0]['hash']==skill['hash']
    finally:server.shutdown();server.server_close();thread.join()


def test_build_includes_audited_reference_and_rejects_changed_text(tmp_path):
    """Dropping reference files or skipping their digest check breaks this contract."""
    import shutil,pytest
    from scripts.build_comic_skills import build
    root=tmp_path/'source';shutil.copytree(ROOT/'resources/comic-skills',root)
    path=root/'references'/'audited.md';path.parent.mkdir(exist_ok=True)
    path.write_text('裁切须容纳批准的必要接触；不能抬手迁就景别。')
    index=json.loads((root/'source-index.json').read_text())
    resource={'path':'references/audited.md','source':'legacy/references/audited.md','source_sha256':'a'*64,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'adaptation':'replace_legacy_host'}
    index['references']=index.get('references',[])+[resource]
    for item in index['packages']:item['references']=item.get('references',[])+['references/audited.md']
    (root/'source-index.json').write_text(json.dumps(index))
    for entry in (root/'entries').glob('*.md'):entry.write_text(entry.read_text()+'\n[裁切依据](references/audited.md)')
    built=build(root)
    assert all(body['files']['references/audited.md']==path.read_text() for body in built.values())
    assert all(resource in json.loads(body['files']['provenance.json'])['reference_sources'] for body in built.values())
    path.write_text('changed without updating the audit')
    with pytest.raises(ValueError,match='source_hash'):build(root)


def test_reference_upgrade_keeps_old_run_resources_and_exposes_new_materials(tmp_path):
    from backend.agent_tools import freeze_context,ProjectTools
    root=ROOT/'resources/comic-skills'
    old=json.loads((root/'versions/1.0.0-pi.1/comic-shot-design.json').read_text())
    new=json.loads((root/'packages/comic-shot-design.json').read_text())
    with TestClient(create_app(tmp_path)) as c:
        pid=c.post('/api/projects',json={'name':'资料升级固定历史'}).json()['id'];base=f'/api/projects/{pid}'
        previous=c.post('/api/skills/import',content=json.dumps(old).encode()).json()
        assert c.put(base+'/skills',json={'expected_revision':0,'hashes':[previous['hash']]}).status_code==200
        with c.app.state.store.db() as db:frozen=freeze_context(c.app.state.store,db,pid,stage='package')
        latest=c.post('/api/skills/import',content=json.dumps(new).encode());assert latest.status_code==200,latest.text
        assert latest.json()['hash']!=previous['hash']
        assert c.put(base+'/skills',json={'expected_revision':1,'hashes':[latest.json()['hash']]}).status_code==200
        with c.app.state.store.db() as db:
            current=freeze_context(c.app.state.store,db,pid,stage='package')
            closed=freeze_stage_resources(c.app.state.store,db,pid,'package')
        assert any(r['path']=='references/shot-framing.md' for info in closed for r in info['resources'])
        tools=ProjectTools(c.app.state.store,pid,current)
        result=tools.call('project_query',{'action':'skill','id':latest.json()['hash'],'query':'references/shot-framing.md'})
        assert result['text']==new['files']['references/shot-framing.md']
        history=ProjectTools(c.app.state.store,pid,frozen).call('project_query',{'action':'skill','id':previous['hash'],'query':'rules/MEM-008.md'})
        assert history['text']==old['files']['rules/MEM-008.md']
        assert c.get(base+'/records').json()==[] and c.get(base+'/tasks').json()==[]


def test_build_refuses_untracked_reference_even_when_file_exists(tmp_path):
    import shutil,pytest
    from scripts.build_comic_skills import build
    root=tmp_path/'source';shutil.copytree(ROOT/'resources/comic-skills',root)
    (root/'references/untracked.md').write_text('unreviewed text')
    index=json.loads((root/'source-index.json').read_text());index['packages'][0]['references'].append('references/untracked.md')
    (root/'source-index.json').write_text(json.dumps(index))
    with pytest.raises(ValueError,match='reference_not_audited'):build(root)


def test_execution_reference_upgrade_is_explicit_and_preserves_pi3_frozen_resources(tmp_path):
    from backend.agent_tools import freeze_context,ProjectTools
    root=ROOT/'resources/comic-skills'
    archived=root/'versions/1.0.0-pi.3/comic-shot-design.json'
    assert archived.is_file(),'pi.3 must remain importable with its original hash'
    old=json.loads(archived.read_text());new=json.loads((root/'packages/comic-shot-design.json').read_text())
    assert old['version']=='1.0.0-pi.3' and new['version']==json.loads((root/'source-index.json').read_text())['version']
    assert old['version']!=new['version']
    with TestClient(create_app(tmp_path)) as c:
        pid=c.post('/api/projects',json={'name':'执行参考固定升级'}).json()['id'];base=f'/api/projects/{pid}'
        previous=c.post('/api/skills/import',content=json.dumps(old).encode()).json()
        assert c.put(base+'/skills',json={'expected_revision':0,'hashes':[previous['hash']]}).status_code==200
        with c.app.state.store.db() as db:frozen=freeze_context(c.app.state.store,db,pid,stage='package')
        latest=c.post('/api/skills/import',content=json.dumps(new).encode()).json()
        assert c.get(base+'/skills').json()['hashes']==[previous['hash']]
        assert c.put(base+'/skills',json={'expected_revision':1,'hashes':[latest['hash']]}).status_code==200
        with c.app.state.store.db() as db:current=freeze_context(c.app.state.store,db,pid,stage='package')
        for path in ['references/appearance-and-single-frame.md','references/final-input-semantics.md','references/control-guidance.md']:
            response=ProjectTools(c.app.state.store,pid,current).call('project_query',{'action':'skill','id':latest['hash'],'query':path})
            assert response['text']==new['files'][path]
            from fastapi import HTTPException
            with pytest.raises(HTTPException):ProjectTools(c.app.state.store,pid,frozen).call('project_query',{'action':'skill','id':previous['hash'],'query':path})
        old_rule=ProjectTools(c.app.state.store,pid,frozen).call('project_query',{'action':'skill','id':previous['hash'],'query':'rules/MEM-008.md'})
        assert old_rule['text']==old['files']['rules/MEM-008.md']
        assert c.get(base+'/records').json()==c.get(base+'/tasks').json()==[]
