"""Check audit traceability, not equivalence of legacy program behavior."""
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESOURCES = ROOT / 'resources/comic-skills'


def mapping():
    return json.loads((RESOURCES / 'capability-mapping.json').read_text())


def test_mapping_covers_every_unfinished_source_without_closing_inventory():
    inventory = json.loads((RESOURCES / 'migration-inventory.json').read_text())
    expected = {r['source']: r for r in inventory['files'] if r['status'] in {
        'pending_review', 'reviewed_partial_host_mapping', 'not_registered', 'partially_adapted_script'}}
    data = mapping()
    assert data['changes_runtime_packages'] is False
    assert data['changes_inventory_status'] is False
    rows = [r for group in data['groups'] for r in group['sources']]
    assert len(rows) == len({r['source'] for r in rows})
    assert set(expected) == {r['source'] for r in rows}
    for row in rows:
        assert row['source_sha256'] == expected[row['source']]['sha256']
        assert row['inventory_status'] == expected[row['source']]['status']
        assert row['program_behavior_review'] == 'not_completed'
    assert data['scope']['source_items'] == len(rows) == 175


def test_mapping_evidence_points_to_existing_named_tests_and_nonempty_boundaries():
    data = mapping()
    for group in data['groups']:
        assert group['review_status'] == 'group_reviewed'
        assert group['sources'] and group['preserved_semantics'] and group['legacy_mechanisms_not_ported']
        assert group['known_gaps'] and group['disposition'] in {
            'host_replacement_with_gaps', 'semantic_adaptation_with_optional_tools', 'legacy_host_replacement'}
        for evidence in group['evidence']:
            path = ROOT / evidence['path']
            assert path.is_file(), evidence
            if 'test' in evidence:
                names = {n.name for n in ast.walk(ast.parse(path.read_text()))
                         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
                assert evidence['test'] in names, evidence
    scope = data['plan_boundaries']
    plan = (ROOT / scope['path']).read_text()
    for clause in scope['original_clauses']:
        assert clause in plan
    assert scope['global_token_money_budget']['basis'] == 'later_navigation_and_progress'
    assert scope['global_token_money_budget']['original_stage_six_explicit'] is False
    assert scope['full_duty_clock']['required_by_original_plan'] is False
    assert data['verification_limit']
