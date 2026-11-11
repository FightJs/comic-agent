"""Exercise the startup version guard without installing or starting services."""
import os
from pathlib import Path
import subprocess


SCRIPT = Path(__file__).resolve().parents[2] / 'start.command'


def fake_node(path, version):
    path.parent.mkdir(parents=True, exist_ok=True)
    major, minor = map(int, version.split('.')[:2])
    path.write_text('#!/bin/sh\nif [ "$1" = "--version" ]; then echo "v'+version+'"; exit 0; fi\n'+
                    ('exit 0\n' if major > 22 or major == 22 and minor >= 19 else 'echo "需要 Node.js ≥22.19" >&2; exit 1\n'))
    path.chmod(0o755)


def guard(tmp_path, current, installed):
    home = tmp_path / 'home'
    home.mkdir()
    bindir = tmp_path / 'current'
    fake_node(bindir / 'node', current)
    for version in installed:
        fake_node(home / '.nvm/versions/node' / ('v'+version) / 'bin/node', version)
    # Run only the real script prefix before any install/build/server commands.
    prefix = SCRIPT.read_text().split('if [[ ! -d agent-runtime/node_modules ]]')[0]
    probe = tmp_path / 'probe.command'
    probe.write_text(prefix+'\ncommand -v node\n')
    env = {**os.environ, 'HOME': str(home), 'PATH': str(bindir)}
    return subprocess.run(['/bin/zsh', str(probe)], env=env, capture_output=True, text=True), home, bindir


def test_old_node_uses_highest_compatible_installed_nvm(tmp_path):
    result, home, _ = guard(tmp_path, '20.13.0', ['22.18.0', '22.23.1', '24.2.0'])
    assert result.returncode == 0, result.stderr
    assert str(home / '.nvm/versions/node/v24.2.0/bin/node') in result.stdout


def test_compatible_path_node_is_preserved(tmp_path):
    result, _, bindir = guard(tmp_path, '22.19.0', ['24.2.0'])
    assert result.returncode == 0, result.stderr
    assert str(bindir / 'node') in result.stdout


def test_no_compatible_node_fails_before_install(tmp_path):
    result, _, _ = guard(tmp_path, '20.13.0', ['22.18.0', '18.20.0'])
    assert result.returncode != 0
    assert '需要 Node.js ≥22.19' in result.stderr
