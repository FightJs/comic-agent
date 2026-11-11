"""Pi.5 package/history checks; these do not measure model quality."""
import hashlib
import json
from pathlib import Path
from scripts.build_comic_skills import build
from backend.skill_references import links, local_reference
from backend.skills import install, freeze_stage_resources

ROOT = Path(__file__).resolve().parents[2] / 'resources/comic-skills'


def test_pi5_retains_explicit_conflict_and_task_origin_boundaries():
    packages = build(ROOT)
    for body in packages.values():
        assert body['version'] == '1.0.0-pi.5'
        text = body['files']['references/workbench.md']
        for fragment in ('不能把剧情必需道具或作用对象降为可选', '不能改放沙发或凭空造桌'):
            assert fragment in text
        assert body == json.loads((ROOT / 'packages' / (body['id'] + '.json')).read_text())
    entry = packages['comic-preproduction']['files']['SKILL.md']
    for fragment in ('fresh', 'reuse_selected', '恢复原批次', '未知调用不能借fresh抹账'):
        assert fragment in entry


def test_pi4_archive_is_byte_bound_and_stage_closures_stay_within_budget():
    archive = ROOT / 'archive/1.0.0-pi.4'
    manifest = json.loads((archive / 'archive-manifest.json').read_text())
    for row in manifest['files']:
        raw = (archive / row['path']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == row['sha256']
        assert json.loads(raw)['version'] == '1.0.0-pi.4'
    assert len(manifest['files']) == 5
    packages = build(ROOT)
    for stage in ('setup','memory','skeleton','outline','style','asset','script','package','image','review'):
        size = 0
        for body in packages.values():
            if stage not in body['stages']:
                continue
            pending = [body['entrypoint']]
            visited = set()
            while pending:
                path = pending.pop()
                if path in visited:
                    continue
                visited.add(path)
                text = body['files'][path]
                size += len(text)
                if path.endswith('.md'):
                    pending.extend(target for link in links(text)
                                   if (target := local_reference(path, link)))
        assert size <= 80000, (stage, size)


def test_pi5_install_does_not_replace_selection_or_old_frozen_resources(tmp_path):
    from fastapi.testclient import TestClient
    from backend.app import create_app
    app = create_app(tmp_path)
    with TestClient(app) as client:
        pid = client.post('/api/projects', json={'name': '规则版本隔离'}).json()['id']
        old = json.loads((ROOT / 'archive/1.0.0-pi.4/comic-preproduction.json').read_text())
        before = install(app.state.store, old)
        base = f'/api/projects/{pid}/skills'
        assert client.put(base, json={'expected_revision': 0, 'hashes': [before['hash']]}).status_code == 200
        with app.state.store.db() as db:
            frozen = freeze_stage_resources(app.state.store, db, pid, 'package')
        after = install(app.state.store, build(ROOT)['comic-preproduction'])
        assert after['hash'] != before['hash']
        assert client.get(base).json()['hashes'] == [before['hash']]
        with app.state.store.db() as db:
            assert freeze_stage_resources(app.state.store, db, pid, 'package') == frozen
        assert '未知调用不能借fresh抹账' not in frozen[0]['resources'][0]['text']
