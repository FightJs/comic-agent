from pathlib import Path
import pytest


def test_synthetic_restore_verifies_originals_versions_and_pi_boundaries():
    from scripts.verify_backup_restore import run_verification
    result=run_verification()
    assert result['sqlite_integrity']=='ok'
    assert result['versions_preserved']==2
    assert result['original_hashes_match'] is True
    assert result['pi_session_branch_preserved'] is True
    assert result['duplicate_run_rejected'] is True
    assert result['unknown_model_continuation_rejected'] is True
    assert result['provider_calls']==0


def test_copy_verification_detects_missing_and_changed_files(tmp_path):
    from scripts.verify_backup_restore import inventory, verify_copy
    source=tmp_path/'source';source.mkdir();(source/'original').write_bytes(b'synthetic original')
    expected=inventory(source)
    restored=tmp_path/'restored';restored.mkdir();(restored/'original').write_bytes(b'changed')
    with pytest.raises(ValueError,match='backup_hash_mismatch'):verify_copy(expected,restored)
    (restored/'original').unlink()
    with pytest.raises(ValueError,match='backup_hash_mismatch'):verify_copy(expected,restored)


def test_inventory_refuses_symlinks_instead_of_following_outside_backup(tmp_path):
    from scripts.verify_backup_restore import inventory
    root=tmp_path/'data';root.mkdir();outside=tmp_path/'outside';outside.write_text('synthetic')
    (root/'linked').symlink_to(outside)
    with pytest.raises(ValueError,match='backup_symlink'):inventory(root)
