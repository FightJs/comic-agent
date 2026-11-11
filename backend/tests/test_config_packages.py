import json
import pytest
from fastapi.testclient import TestClient
from backend.app import create_app
import backend.app as module


class Vault:
    def __init__(self):self.values={};self.fail=None
    def get_password(self,service,key):return self.values.get(key)
    def set_password(self,service,key,value):
        if key==self.fail:raise RuntimeError('fixture secret error')
        self.values[key]=value
    def delete_password(self,service,key):self.values.pop(key,None)


@pytest.fixture
def setup(tmp_path,monkeypatch):
    vault=Vault();monkeypatch.setattr(module,'vault',vault)
    with TestClient(create_app(tmp_path)) as c:yield c,vault,tmp_path


def preview(c,profiles):
    return c.post('/api/config-packages/preview',content=json.dumps({'format':'comic-config/v1','name':'创作配置','profiles':profiles}).encode(),headers={'Content-Type':'application/json'})


def test_preview_redacts_and_apply_saves_keys_only_to_vault(setup):
    c,vault,root=setup
    value=preview(c,[{'purpose':'text','url':'https://example.org/v1','model':'text-model','secret':'private-config-key'},{'purpose':'image','url':'https://api.openai.com/v1','model':'image-model','secret':'private-image-key'}])
    assert value.status_code==200,value.text
    assert 'private-config-key' not in value.text
    assert value.json()['profiles'][0]['has_secret'] is True
    assert vault.values=={}
    token=value.json()['token']
    result=c.post('/api/config-packages/apply',json={'token':token})
    assert result.status_code==200,result.text
    assert result.json()['applied']==['text','image']
    assert vault.values['provider:text']=='private-config-key'
    assert c.get('/api/settings').json()['model']=='text-model'
    assert c.post('/api/config-packages/apply',json={'token':token}).json()==result.json()
    with c.app.state.store.db() as db:
        assert 'private-config-key' not in db.execute('SELECT content FROM settings').fetchone()[0]
    assert b'private-config-key' not in (root/'workbench.sqlite').read_bytes()


def test_bad_package_and_credential_urls_do_not_echo_secrets(setup):
    c,_,_=setup
    bad=preview(c,[{'purpose':'text','url':'https://name:credential-password@example.org/v1','model':'m','secret':'never-echo'}])
    assert bad.status_code==422
    assert all(s not in bad.text for s in ['credential-password','never-echo'])
    malformed=c.post('/api/config-packages/preview',content=b'{"secret":"never-echo"}',headers={'Content-Type':'application/json'})
    assert malformed.status_code==422 and 'never-echo' not in malformed.text


def test_settings_conflict_prevents_vault_writes(setup):
    c,vault,_=setup
    token=preview(c,[{'purpose':'text','url':'https://example.org/v1','model':'m','secret':'new-key'}]).json()['token']
    c.put('/api/settings',json={'purpose':'text','model':'changed','url':'https://example.org/v1'})
    assert c.post('/api/config-packages/apply',json={'token':token}).status_code==409
    assert vault.values=={}


def test_partial_keychain_failure_rolls_back_previous_secrets(setup):
    c,vault,_=setup;vault.values['provider:text']='old-key';vault.fail='provider:image'
    token=preview(c,[{'purpose':'text','url':'https://example.org/v1','model':'m','secret':'new-key'},{'purpose':'image','url':'https://example.org/v1','model':'i','secret':'image-key'}]).json()['token']
    response=c.post('/api/config-packages/apply',json={'token':token})
    assert response.status_code==503
    assert vault.values['provider:text']=='old-key'
    assert c.get('/api/settings').json()['model']==''
    assert 'new-key' not in response.text


def test_raw_upload_is_bounded_and_never_uses_multipart_tempfiles(setup,monkeypatch):
    import starlette.formparsers
    c,_,_=setup
    def forbidden(*args,**kwargs):raise AssertionError('must not spool credentials')
    monkeypatch.setattr(starlette.formparsers,'SpooledTemporaryFile',forbidden)
    assert preview(c,[{'purpose':'text','url':'https://example.org/v1','model':'m'}]).status_code==200
    response=c.post('/api/config-packages/preview',content=b'x'*(1024*1024+1))
    assert response.status_code==413


def test_expired_preview_is_rejected_and_discard_is_idempotent(setup,monkeypatch):
    import backend.config_packages as packages
    from types import SimpleNamespace
    c,vault,_=setup;stamp=[100]
    monkeypatch.setattr(packages,'time',SimpleNamespace(monotonic=lambda:stamp[0]))
    token=preview(c,[{'purpose':'text','url':'https://example.org/v1','model':'m','secret':'expired-key'}]).json()['token']
    stamp[0]=701
    assert c.post('/api/config-packages/apply',json={'token':token}).status_code==410
    assert vault.values=={}
    for _ in range(2):assert c.post('/api/config-packages/discard',json={'token':token}).status_code==200


def test_secret_only_change_invalidates_preview_and_missing_secret_preserves_key(setup):
    c,vault,_=setup;vault.values['provider:text']='existing-key'
    token=preview(c,[{'purpose':'text','url':'https://example.org/v1','model':'m'}]).json()['token']
    assert c.post('/api/config-packages/apply',json={'token':token}).status_code==200
    assert vault.values['provider:text']=='existing-key'
    token=preview(c,[{'purpose':'text','url':'https://example.org/v1','model':'m','secret':'package-key'}]).json()['token']
    assert c.put('/api/settings',json={'purpose':'text','url':'https://example.org/v1','model':'m','secret':'manual-new-key'}).status_code==200
    assert c.post('/api/config-packages/apply',json={'token':token}).status_code==409
    assert vault.values['provider:text']=='manual-new-key'


def test_secret_copied_into_public_fields_is_rejected_before_preview(setup):
    c,_,_=setup
    response=preview(c,[{'purpose':'text','url':'https://example.org/v1','model':'accidental-private-key','secret':'accidental-private-key'}])
    assert response.status_code==422
    assert 'accidental-private-key' not in response.text


def test_non_chat_protocol_is_preserved_for_unified_runtime(setup):
    c,_,_=setup
    assert c.put('/api/settings',json={'purpose':'text','url':'https://example.org/v1','model':'m','api':'anthropic-messages','secret':'fixture-provider-key'}).status_code==200
    with c.app.state.store.db() as db:
        assert c.app.state.graph_engine.config(db)['api']=='anthropic-messages'
    assert c.get('/api/settings').json()['api']=='anthropic-messages'
