"""Audit decisions must not silently turn unimplemented host protocols into migrated tools."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]

def test_host_contract_reviews_keep_source_identity_and_explicit_remaining_work():
    inventory=json.loads((ROOT/'resources/comic-skills/migration-inventory.json').read_text())
    records={r['source']:r for r in inventory['files']}
    audit=json.loads((ROOT/'resources/comic-skills/host-contract-review.json').read_text())
    assert audit['format']=='comic-host-contract-review/v1'
    assert len(audit['sources'])==3 and audit['changes_runtime_packages'] is False
    for source in audit['sources']:
        row=records[source['source']]
        assert source['source_sha256']==row['sha256']
        assert row['status']==source['status']=='reviewed_partial_host_mapping'
        assert row['review']=='host-contract-review.json'
        assert any(c['disposition']=='pending' for c in source['clauses'])
        assert {c['disposition'] for c in source['clauses']}<= {'workbench_equivalent','not_applicable','pending'}
        for clause in source['clauses']:
            assert clause['source_topic'] and clause['decision']
            if clause['disposition']=='workbench_equivalent':assert clause['evidence']
            for evidence in clause['evidence']:
                p=ROOT/evidence['path'];assert p.is_file()
                if evidence.get('test'):assert 'def '+evidence['test']+'(' in p.read_text()
    assert len([r for r in records.values() if r['status']=='pending_review'])==50
