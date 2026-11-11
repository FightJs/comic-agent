import io
import zipfile
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from backend.app import create_app

@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        yield c

def project(c, name='测试小说'):
    r = c.post('/api/projects', json={'name': name})
    assert r.status_code == 200
    return r.json()['id']

def record(c, p, kind='outline', content=None, **extra):
    r = c.post(f'/api/projects/{p}/records', json={'kind': kind, 'title': '测试', 'content': content or {'html': '<p>旧文</p>'}, **extra})
    assert r.status_code == 200, r.text
    return r.json()

def png():
    b = io.BytesIO()
    Image.new('RGB', (100, 200), 'olive').save(b, 'PNG')
    return b.getvalue()

def test_persistence_and_project_isolation(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        p, q = project(c), project(c, '另一本')
        r = record(c, p)
        assert c.get(f'/api/projects/{q}/records/{r["id"]}').status_code == 404
    with TestClient(create_app(tmp_path)) as c:
        assert c.get(f'/api/projects/{p}/records/{r["id"]}').json()['content']['html'] == '<p>旧文</p>'
        assert len(c.get('/api/projects').json()) == 2

def test_revision_conflict_and_review_invalidation(client):
    p = project(client)
    r = record(client, p)
    base = f'/api/projects/{p}/records/{r["id"]}'
    assert client.post(base+'/reviews', json={'version': 1, 'decision': 'approved', 'note': '通过'}).status_code == 200
    assert client.get(base).json()['review'] == 'approved'
    changed = client.put(base, json={'expected_version': 1, 'content': {'html': '<p>新版</p>'}})
    assert changed.status_code == 200
    assert changed.json()['review'] == 'pending'
    assert client.put(base, json={'expected_version': 1, 'content': {}}).status_code == 409
    versions = client.get(base+'/versions').json()
    assert versions[-1]['content']['html'] == '<p>旧文</p>'
    assert client.get(base+'/reviews').json()[0]['version'] == 1

def test_mock_lineage_never_becomes_formal(client):
    p = project(client)
    r = record(client, p, source='mock')
    base = f'/api/projects/{p}/records/{r["id"]}'
    r = client.put(base, json={'expected_version': 1, 'content': {'html': '手动改写'}, 'source': 'manual'}).json()
    assert r['source'] == 'mock'
    assert client.post(base+'/reviews', json={'version': 2, 'decision': 'approved', 'note': '模拟审核'}).json()['source'] == 'mock'
    gates = client.get(f'/api/projects/{p}/gates').json()
    assert not gates['ready'] and not gates['ai_connected']

def test_import_original_encoding_and_chapters(client):
    p = project(client)
    raw = '第一章 初见\n院中有一棵树。\n第二章 重逢\n她回来了。'.encode('gb18030')
    r = client.post(f'/api/projects/{p}/text', files={'file': ('中文小说.txt', raw, 'text/plain')})
    assert r.status_code == 200, r.text
    content = r.json()['content']
    assert content['encoding'] == 'gb18030'
    assert len(content['chapters']) == 2
    assert client.get(content['url']).content == raw
    bad = client.post(f'/api/projects/{p}/text', files={'file': ('bad.txt', b'\xff\x00\xfe', 'text/plain')})
    assert bad.status_code == 422

def test_image_validation_annotations_and_zip(client):
    p, q = project(client), project(client)
    raw = png()
    r = client.post(f'/api/projects/{p}/images', files={'file': ('角色.png', raw, 'image/png')}).json()
    assert r['content']['width'] == 100
    base = f'/api/projects/{p}/records/{r["id"]}'
    data = {'expected_version': 0, 'image_version': 1, 'items': [{'id':'a','type':'rect','x':10,'y':20,'width':30,'height':40,'note':'改为长袖'}]}
    assert client.put(base+'/annotations', json=data).status_code == 200
    assert client.get(base+'/annotations?image_version=1').json()['items'][0]['x'] == 10
    assert client.get(base+'/annotations?image_version=2').status_code == 404
    assert client.put(base+'/annotations', json=data).status_code == 409
    assert client.get(r['content']['url']).content == raw
    z = client.post(f'/api/projects/{p}/download', json={'ids':[r['id']]} )
    with zipfile.ZipFile(io.BytesIO(z.content)) as archive:
        assert archive.read(archive.namelist()[0]) == raw
    assert client.post(f'/api/projects/{q}/download', json={'ids':[r['id']]}).status_code == 404
    assert client.post(f'/api/projects/{p}/images', files={'file': ('坏图.png', b'garbage', 'image/png')}).status_code == 422

def test_task_failure_retry_and_mock_result(client):
    p = project(client)
    r = record(client, p,kind='style',content={'prompt':'画风草稿'})
    t = client.post(f'/api/projects/{p}/tasks', json={'kind':'style', 'target_id':r['id'], 'input_version':1,'fail':True}).json()
    task = client.get(f'/api/projects/{p}/tasks').json()[0]
    assert task['status'] == 'failed'
    assert client.post(f'/api/projects/{p}/tasks/{t["id"]}/retry').status_code == 200
    task = client.get(f'/api/projects/{p}/tasks').json()[0]
    assert task['status'] == 'succeeded'
    result = client.get(f'/api/projects/{p}/records/{task["output_id"]}').json()
    assert result['source'] == 'mock'

def test_settings_do_not_return_secrets(client, monkeypatch):
    import backend.app as module
    class Vault:
        value = None
        def set_password(self, service, user, password): self.value = password
        def get_password(self, service, user): return self.value
    monkeypatch.setattr(module, 'vault', Vault())
    r = client.put('/api/settings', json={'url':'https://example.com/v1','model':'candidate','purpose':'text','secret':'test-secret'})
    assert r.status_code == 200
    assert 'test-secret' not in client.get('/api/settings').text
    assert client.get('/api/settings').json()['has_secret'] is True
    assert client.get('/api/settings').json()['connection'] == 'unverified'
