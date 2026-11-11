"""No network: immutable image retry authorization and attempt evidence."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException

from backend.store import Store
from backend.image_attempts import ImageAttempts, freeze_policy, network_limit

H = 'a' * 64
G = 'b' * 64
SAFE = {'outcome': 'not_sent', 'response_started': False, 'transport_phase': 'connect', 'error_class': 'ConnectError'}


@pytest.fixture
def ledger(tmp_path):
    store = Store(tmp_path)
    with store.db() as db:
        db.execute("INSERT INTO projects VALUES('p','synthetic',0,'t','t')")
        db.execute("INSERT INTO projects VALUES('other','synthetic',0,'t','t')")
    return ImageAttempts(store)


def bind(ledger, retries=4):
    with ledger.store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        return ledger.bind(db, 'p', 'call', H, G, {'version': 1, 'max_not_sent_retries': retries})


def claim(ledger, sequence=1, pid='p', input_hash=H, authorization_hash=G):
    with ledger.store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        return ledger.claim(db, pid, 'call', input_hash, authorization_hash, sequence)


def finish(ledger, attempt, evidence=SAFE):
    with ledger.store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        return ledger.finish(db, 'p', attempt['id'], evidence)


def test_policy_default_and_network_ceiling():
    assert freeze_policy() == {'version': 1, 'max_not_sent_retries': 0}
    assert network_limit(3, {'version': 1, 'max_not_sent_retries': 4}) == 15
    assert network_limit(2) == 2


@pytest.mark.parametrize('policy', [True, [], {'version': True}, {'version': 2}, {'max_not_sent_retries': True}, {'max_not_sent_retries': 1.0}, {'max_not_sent_retries': -1}, {'max_not_sent_retries': 5}, {'extra': 'secret'}])
def test_policy_strict(policy):
    with pytest.raises(HTTPException): freeze_policy(policy)


@pytest.mark.parametrize('count', [True, 1.0, -1, '2'])
def test_network_count_strict(count):
    with pytest.raises(HTTPException): network_limit(count)


def test_five_attempt_limit_survives_reopen_and_terminal_evidence_is_immutable(ledger):
    bind(ledger)
    ids = []
    for sequence in range(1, 6):
        attempt = claim(ledger, sequence)
        assert attempt['claimed'] is True
        ids.append(attempt['id'])
        first = finish(ledger, attempt)
        assert finish(ledger, attempt) == first
        ledger = ImageAttempts(ledger.store)
    assert len(set(ids)) == 5
    with pytest.raises(HTTPException): claim(ledger, 6)
    with ledger.store.db() as db:
        history = ledger.list(db, 'p', 'call')
        assert len(history['attempts']) == 5 and history['remaining_attempts'] == 0
        assert all(a['evidence'] == SAFE for a in history['attempts'])
        with pytest.raises(sqlite3.IntegrityError):
            db.execute('UPDATE image_attempts SET sequence=9 WHERE id=?', (ids[0],))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute('DELETE FROM image_attempt_results WHERE attempt_id=?', (ids[0],))
    with pytest.raises(HTTPException): finish(ledger, {'id': ids[0]}, {**SAFE, 'outcome': 'unknown'})


def test_default_zero_and_old_missing_evidence_never_allow_second_attempt(ledger):
    bind(ledger, 0)
    first = claim(ledger)
    with pytest.raises(HTTPException): claim(ledger, 2)
    finish(ledger, first)
    with pytest.raises(HTTPException): claim(ledger, 2)


@pytest.mark.parametrize('evidence', [
    {'outcome': outcome, 'response_started': started, 'transport_phase': phase}
    for outcome, started, phase in [('unknown', False, 'unknown'), ('rejected', True, 'response_headers'), ('received', True, 'response_body'), ('completed', True, 'response_body')]
])
def test_non_retryable_terminal_outcomes(ledger, evidence):
    bind(ledger)
    finish(ledger, claim(ledger), evidence)
    with pytest.raises(HTTPException): claim(ledger, 2)


@pytest.mark.parametrize('evidence', [
    {'outcome': 'not_sent'},
    {**SAFE, 'response_started': True},
    {**SAFE, 'transport_phase': 'unknown'},
    {**SAFE, 'transport_phase': 'response_headers'},
    {**SAFE, 'error_class': 'WriteTimeout'},
    {**SAFE, 'message': 'synthetic-secret'},
    {**SAFE, 'url': 'http://secret.invalid'},
    {**SAFE, 'http_status': 200},
    {**SAFE, 'receipt_sha256': H},
])
def test_unreliable_or_sensitive_evidence_is_not_accepted(ledger, evidence):
    bind(ledger)
    attempt = claim(ledger)
    with pytest.raises(HTTPException): finish(ledger, attempt, evidence)
    with pytest.raises(HTTPException): claim(ledger, 2)


def test_binding_project_input_grant_and_sequence_checks(ledger):
    bind(ledger)
    bind(ledger)
    with pytest.raises(HTTPException): bind(ledger, 3)
    with pytest.raises(HTTPException): claim(ledger, pid='other')
    with pytest.raises(HTTPException): claim(ledger, input_hash='c' * 64)
    with pytest.raises(HTTPException): claim(ledger, authorization_hash='d' * 64)
    with pytest.raises(HTTPException): claim(ledger, 2)
    with pytest.raises(HTTPException): claim(ledger, True)
    first = claim(ledger)
    duplicate = claim(ledger)
    assert duplicate['id'] == first['id'] and duplicate['claimed'] is False
    with ledger.store.db() as db:
        db.execute('BEGIN IMMEDIATE')
        with pytest.raises(HTTPException): ledger.finish(db, 'other', first['id'], SAFE)


def test_concurrent_claim_does_not_grant_duplicate_network_dispatch(ledger):
    bind(ledger)
    with ThreadPoolExecutor(max_workers=4) as pool:
        attempts = list(pool.map(lambda _: claim(ledger), range(4)))
    assert len({a['id'] for a in attempts}) == 1
    assert sum(a['claimed'] for a in attempts) == 1


def test_host_transaction_is_required(ledger):
    with ledger.store.db() as db:
        with pytest.raises(HTTPException): ledger.bind(db, 'p', 'call', H, G)
    bind(ledger)
    with ledger.store.db() as db:
        with pytest.raises(HTTPException): ledger.claim(db, 'p', 'call', H, G, 1)


def test_unfinished_or_legacy_terminal_missing_transport_evidence_blocks_retry(ledger):
    bind(ledger)
    first = claim(ledger)
    with pytest.raises(HTTPException): claim(ledger, 2)
    with ledger.store.db() as db:
        db.execute('INSERT INTO image_attempt_results VALUES(?,?,?)', (first['id'], '{"outcome":"not_sent"}', 'synthetic'))
    with pytest.raises(HTTPException): claim(ledger, 2)


def test_evidence_cannot_be_replaced_using_sqlite_replace(ledger):
    bind(ledger)
    first = claim(ledger)
    finish(ledger, first)
    with ledger.store.db() as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute('INSERT OR REPLACE INTO image_attempt_results VALUES(?,?,?)', (first['id'], '{}', 'synthetic'))


@pytest.mark.parametrize('evidence', [
    {'outcome': 'not_sent', 'response_started': False, 'transport_phase': 'pool_acquire', 'error_class': 'PoolTimeout'},
    {**SAFE, 'error_class': 'ConnectTimeout'},
])
def test_other_confirmed_unsent_phases_allow_next_attempt(ledger, evidence):
    bind(ledger)
    finish(ledger, claim(ledger), evidence)
    assert claim(ledger, 2)['claimed'] is True


def test_host_guard_rollback_does_not_consume_attempt_or_budget(ledger):
    bind(ledger)
    with pytest.raises(RuntimeError):
        with ledger.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            ledger.claim(db, 'p', 'call', H, G, 1)
            raise RuntimeError('synthetic host guard rollback')
    first = claim(ledger)
    assert first['sequence'] == 1 and first['claimed'] is True
    with ledger.store.db() as db:
        assert ledger.list(db, 'p', 'call')['remaining_attempts'] == 4


def test_unknown_grant_cannot_be_used_to_create_a_retry(ledger):
    with pytest.raises(HTTPException): claim(ledger, 2)
    with ledger.store.db() as db:
        assert db.execute('SELECT count(*) FROM image_attempts').fetchone()[0] == 0
