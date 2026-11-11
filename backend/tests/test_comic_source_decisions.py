"""Trace per-source decisions; this is not proof of legacy-program equivalence."""
import ast
import hashlib
import json
import re
import pytest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
RESOURCES=ROOT/'resources/comic-skills'
SOURCE_ROOT=Path.home()/'.codex/skills'
DECISIONS=RESOURCES/'source-decisions'


def decisions():
    return [json.loads(p.read_text()) for p in sorted(DECISIONS.glob('*.json'))]


def test_every_unfinished_source_has_exactly_one_separate_disposition_record():
    mapping=json.loads((RESOURCES/'capability-mapping.json').read_text())
    expected={r['source']:r for g in mapping['groups'] for r in g['sources']}
    documents=decisions()
    assert len(documents)==4
    rows=[r for doc in documents for r in doc['files']]
    assert len(rows)==len({r['source'] for r in rows})==175
    assert {r['source'] for r in rows}==set(expected)
    assert {(g['id'] if isinstance(g,dict) else g) for doc in documents for g in doc['groups']}=={g['id'] for g in mapping['groups']}
    for doc in documents:
        assert doc['format']=='comic-source-decisions/v1'
    for row in rows:
        assert row['source_sha256']==expected[row['source']]['source_sha256']
        assert row['disposition'] in {'semantic_retained','host_replaced','legacy_mechanism_not_ported','needs_implementation','mixed','pending'}
        assert row['summary'] and row['clauses'] and row['limits']
        # Runtime registration status and program equivalence are separate facts.
        assert row.get('program_equivalence_verified',False) is False


def test_live_source_hashes_and_anchors_when_original_skills_are_available():
    if not SOURCE_ROOT.is_dir():pytest.skip('original external Skills unavailable; artifact coverage and host evidence remain checked separately')
    for doc in decisions():
        for row in doc['files']:
            source=SOURCE_ROOT/row['source']
            assert source.is_file(),row['source']
            raw=source.read_bytes()
            assert hashlib.sha256(raw).hexdigest()==row['source_sha256']
            text=raw.decode('utf-8');lines=text.splitlines()
            for clause in row['clauses']:
                anchor=clause['source_anchor']
                line_range=re.fullmatch(r'L(\d+)(?:-L?(\d+))?',anchor)
                if line_range:
                    start=int(line_range[1]);end=int(line_range[2] or start)
                    assert 1<=start<=end<=len(lines),(row['source'],anchor)
                else:assert anchor and anchor in text,(row['source'],anchor)
                assert clause['behavior'] and clause['decision']


def test_host_evidence_is_resolvable_without_external_skill_installation():
    for doc in decisions():
        for row in doc['files']:
            for clause in row['clauses']:
                assert clause['behavior'] and clause['decision']
                for evidence in clause.get('workbench_evidence',[]):
                    path=ROOT/evidence['path']
                    assert path.is_file(),evidence
                    if 'test' in evidence:
                        names={n.name for n in ast.walk(ast.parse(path.read_text())) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
                        assert evidence['test'] in names,evidence


def test_inventory_links_dispositions_without_relabeling_runtime_registration():
    inventory=json.loads((RESOURCES/'migration-inventory.json').read_text())
    rows={r['source']:r for r in inventory['files']}
    linked=0
    for document_path in sorted(DECISIONS.glob('*.json')):
        document=json.loads(document_path.read_text())
        for decision in document['files']:
            row=rows[decision['source']]
            assert row['sha256']==decision['source_sha256']
            assert row['status'] in {'pending_review','reviewed_partial_host_mapping','not_registered','partially_adapted_script'}
            review=row['disposition_review']
            assert review['record']=='source-decisions/'+document_path.name
            assert review['disposition']==decision['disposition']
            assert review['program_equivalence_verified'] is False
            linked+=1
    assert linked==175
