import json
import io
import zipfile
import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException
from backend.app import create_app

@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path)) as c:yield c

def pack(**overrides):
    return {'format':'comic-skill/v1','id':'faithful','name':'忠实一致性流程','version':'1.0','stages':['outline','script'],'tags':['一致性','玄幻'],'entrypoint':'SKILL.md','files':{'SKILL.md':'# 一致性\n先核对人物动机。详见[约束](references/rules.md)。','references/rules.md':'不得为追求戏剧性伪造原著事实。'},**overrides}

def install(c,body):return c.post('/api/skills/import',content=json.dumps(body).encode(),headers={'Content-Type':'application/json'})

def test_install_is_immutable_and_project_selection_is_versioned(client):
    c=client
    first=install(c,pack());assert first.status_code==200,first.text
    value=first.json();assert len(value['hash'])==64
    assert install(c,pack()).json()['hash']==value['hash']
    assert install(c,pack(files={'SKILL.md':'另一份规则'})).status_code==409
    pid=c.post('/api/projects',json={'name':'甲'}).json()['id'];base=f'/api/projects/{pid}/skills'
    assert c.put(base,json={'expected_revision':0,'hashes':[value['hash']]}).status_code==200
    assert c.get(base).json()['revision']==1
    assert c.put(base,json={'expected_revision':0,'hashes':[]}).status_code==409
    assert c.get('/api/skills').json()[0]['name']=='忠实一致性流程'


def test_zip_and_paths_are_validated_without_extracting(client):
    value=pack();files=value.pop('files');buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w') as z:
        z.writestr('manifest.json',json.dumps(value))
        for path,text in files.items():z.writestr(path,text)
    assert client.post('/api/skills/import',content=buf.getvalue()).status_code==200
    assert install(client,pack(id='escape',files={'SKILL.md':'x','../outside':'secret'})).status_code==422
    assert install(client,pack(id='missing',files={'else.md':'无入口'})).status_code==422


def test_selected_skill_is_frozen_and_resources_are_available_to_tools(client):
    from backend.agent_tools import freeze_context,ProjectTools
    c=client;value=install(c,pack()).json();pid=c.post('/api/projects',json={'name':'项目'}).json()['id']
    c.put(f'/api/projects/{pid}/skills',json={'expected_revision':0,'hashes':[value['hash']]})
    with c.app.state.store.db() as db:frozen=freeze_context(c.app.state.store,db,pid,stage='outline')
    c.put(f'/api/projects/{pid}/skills',json={'expected_revision':1,'hashes':[]})
    tools=ProjectTools(c.app.state.store,pid,frozen)
    result=tools.call('project_query',{'action':'skill','id':value['hash'],'query':'references/rules.md'})
    assert result['text']=='不得为追求戏剧性伪造原著事实。'
    assert len(frozen['skills'])==1
    with pytest.raises(HTTPException) as denied:tools.call('project_query',{'action':'skill','id':'foreign','query':'SKILL.md'})
    assert denied.value.status_code==403


def test_missing_relative_reference_is_rejected(client):
    response=install(client,pack(id='broken',files={'SKILL.md':'遵循[必需约束](references/missing.md)。'}))
    assert response.status_code==422


def test_only_one_version_of_a_workflow_can_be_selected(client):
    a=install(client,pack()).json();b=install(client,pack(version='2')).json()
    pid=client.post('/api/projects',json={'name':'项目'}).json()['id']
    response=client.put(f'/api/projects/{pid}/skills',json={'expected_revision':0,'hashes':[a['hash'],b['hash']]})
    assert response.status_code==422


def test_code_examples_do_not_become_missing_operational_links(client):
    text='# 规则\n```md\n[格式示例](not-a-real-file.md)\n```\n实际规则：不得编造原著事实。'
    assert install(client,pack(id='examples',files={'SKILL.md':text})).status_code==200


def test_sibling_skill_reference_resolves_inside_the_same_bundle(client):
    value=pack(id='family',entrypoint='planning/SKILL.md',files={'planning/SKILL.md':'查看[镜头规则](../shots/SKILL.md)。','shots/SKILL.md':'一格只表达一个主要画面。'})
    assert install(client,value).status_code==200


def test_script_resources_are_inert_and_unselected_bundles_are_inaccessible(client,tmp_path):
    from backend.agent_tools import freeze_context,ProjectTools
    marker=tmp_path/'must-not-exist'
    value=pack(id='inert',files={'SKILL.md':'脚本仅作参考，不自动执行。','scripts/setup.py':f'from pathlib import Path\nPath({str(marker)!r}).write_text("unsafe")'})
    installed=install(client,value);assert installed.status_code==200
    assert not marker.exists()
    pid=client.post('/api/projects',json={'name':'未启用'}).json()['id']
    with client.app.state.store.db() as db:frozen=freeze_context(client.app.state.store,db,pid,stage='outline')
    from fastapi import HTTPException
    with pytest.raises(HTTPException):ProjectTools(client.app.state.store,pid,frozen).call('project_query',{'action':'skill','id':installed.json()['hash']})


def test_zip_symlink_and_large_uncompressed_bundle_are_rejected(client):
    body=pack();body.pop('files');buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w') as z:
        z.writestr('manifest.json',json.dumps(body));link=zipfile.ZipInfo('SKILL.md');link.external_attr=(0o120777<<16);z.writestr(link,'/etc/passwd')
    assert client.post('/api/skills/import',content=buf.getvalue()).status_code==422
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w',compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr('manifest.json',json.dumps(body));z.writestr('SKILL.md','x'*(8*1024*1024+1))
    assert client.post('/api/skills/import',content=buf.getvalue()).status_code==422
