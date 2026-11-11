"""Synthetic provider: each authorization-backed execute performs at most one POST."""
import asyncio

import httpx
import pytest
from fastapi import HTTPException

from backend.tests.test_image_provider import fixture, reply
from backend.tests.test_image_provider_retry import BrokenBody

G = 'b' * 64
POLICY = {'version': 1, 'max_not_sent_retries': 4}


def prepared(provider, policy=POLICY):
    return provider.prepare('p', 'retry', 'synthetic', retry_policy=policy)


def run(provider, cid, **kwargs):
    return asyncio.run(provider.execute('p', cid, **kwargs))


def test_policy_none_preserves_old_hash_and_explicit_policy_requires_grant(tmp_path):
    requests = []
    _, provider, _ = fixture(tmp_path, lambda req: (requests.append(req), reply(req))[1])
    old = provider.prepare('p', 'old', 'synthetic')
    assert 'retry_policy' not in old['manifest'] and old['attempts'] is None
    assert provider.prepare('p', 'old', 'synthetic', retry_policy=None)['input_hash'] == old['input_hash']
    new = prepared(provider)
    assert new['manifest']['retry_policy'] == POLICY
    with pytest.raises(HTTPException): run(provider, new['id'])
    assert not requests and provider.get('p', new['id'])['attempts'] is None


def test_one_post_per_execute_five_total_unique_attempts_and_reopen(tmp_path):
    requests = []
    def handler(req):
        requests.append(req)
        raise httpx.ConnectError('synthetic-secret', request=req)
    store, provider, config = fixture(tmp_path, handler)
    call = prepared(provider)
    for number in range(1, 6):
        result = run(provider, call['id'], authorization_hash=G, allow_retry=number > 1)
        assert result['status'] == 'not_sent' and len(requests) == number
        assert len(result['attempts']['attempts']) == number
        assert result['attempts']['attempts'][-1]['evidence']['outcome'] == 'not_sent'
    with pytest.raises(HTTPException): run(provider, call['id'], authorization_hash=G, allow_retry=True)
    assert len(requests) == 5
    assert len({req.headers['x-client-request-id'] for req in requests}) == 5
    assert 'synthetic-secret' not in str(result['attempts'])
    from backend.image_provider import ImageProvider
    reopened = ImageProvider(store, lambda: config.copy(), lambda: 'fixture-secret', transport=httpx.MockTransport(handler))
    with pytest.raises(HTTPException): run(reopened, call['id'], authorization_hash=G, allow_retry=True)
    assert len(requests) == 5


def test_retry_requires_same_grant_allow_flag_and_guard(tmp_path):
    requests = []
    def handler(req):
        requests.append(req)
        raise httpx.PoolTimeout('synthetic', request=req)
    _, provider, config = fixture(tmp_path, handler)
    call = prepared(provider)
    run(provider, call['id'], authorization_hash=G)
    assert run(provider, call['id'], authorization_hash=G)['status'] == 'not_sent'
    with pytest.raises(HTTPException): run(provider, call['id'], authorization_hash='c' * 64, allow_retry=True)
    def cancelled(db):raise HTTPException(409, 'synthetic cancellation')
    with pytest.raises(HTTPException): run(provider, call['id'], authorization_hash=G, allow_retry=True, before_submit=cancelled)
    config['model'] = 'changed'
    with pytest.raises(HTTPException): run(provider, call['id'], authorization_hash=G, allow_retry=True)
    assert len(requests) == 1 and len(provider.get('p', call['id'])['attempts']['attempts']) == 1


@pytest.mark.parametrize('status', [400, 403, 408, 500, 302])
def test_response_status_never_retries(tmp_path, status):
    requests = []
    def handler(req):requests.append(req);return httpx.Response(status)
    _, provider, _ = fixture(tmp_path, handler)
    call = prepared(provider)
    first = run(provider, call['id'], authorization_hash=G)
    assert first['attempts']['attempts'][0]['evidence']['response_started'] is True
    assert run(provider, call['id'], authorization_hash=G, allow_retry=True)['status'] == first['status']
    assert len(requests) == 1


def test_response_body_connect_error_unknown_and_cancelled_attempt_terminal(tmp_path):
    requests = []
    def handler(req):requests.append(req);return httpx.Response(200, stream=BrokenBody(httpx.ConnectError))
    _, provider, _ = fixture(tmp_path, handler)
    call = prepared(provider)
    result = run(provider, call['id'], authorization_hash=G)
    assert result['status'] == 'unknown'
    assert result['attempts']['attempts'][0]['evidence']['response_started'] is True
    run(provider, call['id'], authorization_hash=G, allow_retry=True)
    assert len(requests) == 1


def test_cancelled_attempt_and_legacy_failure_cannot_retry(tmp_path):
    requests = []
    def handler(req):requests.append(req);raise asyncio.CancelledError()
    _, provider, _ = fixture(tmp_path, handler)
    call = prepared(provider)
    with pytest.raises(asyncio.CancelledError): run(provider, call['id'], authorization_hash=G)
    result = provider.get('p', call['id'])
    assert result['status'] == 'unknown'
    assert result['attempts']['attempts'][0]['evidence']['outcome'] == 'unknown'
    legacy = provider.prepare('p', 'legacy', 'synthetic')
    provider._status('p', legacy['id'], 'not_sent')
    with pytest.raises(HTTPException): run(provider, legacy['id'], authorization_hash=G, allow_retry=True)
    assert len(requests) == 1


def test_saved_response_failure_recovers_without_attempt_or_post(tmp_path, monkeypatch):
    requests = []
    def handler(req):requests.append(req);return reply(req)
    _, provider, _ = fixture(tmp_path, handler)
    call = prepared(provider)
    finalize = provider._finalize
    monkeypatch.setattr(provider, '_finalize', lambda *args: (_ for _ in ()).throw(OSError('synthetic disk')))
    result = run(provider, call['id'], authorization_hash=G)
    assert result['status'] == 'received'
    assert result['attempts']['attempts'][0]['evidence']['outcome'] == 'received'
    monkeypatch.setattr(provider, '_finalize', finalize)
    assert run(provider, call['id'], authorization_hash=G, allow_retry=True)['status'] == 'completed'
    assert len(requests) == 1


def test_explicit_zero_success_and_retry_then_success_keep_same_logical_call(tmp_path):
    requests = []
    def handler(req):
        requests.append(req)
        if len(requests) == 1:raise httpx.ConnectTimeout('synthetic', request=req)
        return reply(req)
    _, provider, _ = fixture(tmp_path, handler)
    call = prepared(provider)
    run(provider, call['id'], authorization_hash=G)
    done = run(provider, call['id'], authorization_hash=G, allow_retry=True)
    assert done['id'] == call['id'] and done['status'] == 'completed'
    assert done['result']['url'].endswith(call['id'] + '_0')
    assert [a['evidence']['outcome'] for a in done['attempts']['attempts']] == ['not_sent', 'received']
    run(provider, call['id'], authorization_hash=G, allow_retry=True)
    assert len(requests) == 2
    zero = provider.prepare('p', 'zero', 'synthetic', retry_policy={})
    assert run(provider, zero['id'], authorization_hash=G)['attempts']['max_attempts'] == 1


def test_concurrent_execute_claims_one_attempt_with_multiple_slots(tmp_path):
    requests = []
    async def handler(req):
        requests.append(req)
        await asyncio.sleep(0.01)
        return reply(req)
    _, provider, _ = fixture(tmp_path, handler)
    from backend.capacity import CapacityPool
    provider.slot = CapacityPool(3)
    call = prepared(provider)
    async def both():
        return await asyncio.gather(*(provider.execute('p', call['id'], authorization_hash=G) for _ in range(3)))
    asyncio.run(both())
    assert len(requests) == 1
    assert len(provider.get('p', call['id'])['attempts']['attempts']) == 1


def test_reference_change_does_not_consume_retry(tmp_path):
    from backend.tests.test_image_provider import png
    requests = []
    def handler(req):requests.append(req);raise httpx.ConnectError('synthetic', request=req)
    store, provider, _ = fixture(tmp_path, handler)
    with store.db() as db:
        url = store.file(db, 'p', 'synthetic.png', png(), 'image/png')
        ref = store.add(db, 'p', 'asset', 'synthetic', {'url': url})
    call = provider.prepare('p', 'ref', 'synthetic', refs=[{'id': ref['id'], 'version': 1}], retry_policy=POLICY)
    run(provider, call['id'], authorization_hash=G)
    with store.db() as db:db.execute('UPDATE records SET adopted=0 WHERE id=?', (ref['id'],))
    with pytest.raises(HTTPException): run(provider, call['id'], authorization_hash=G, allow_retry=True)
    assert len(requests) == 1 and len(provider.get('p', call['id'])['attempts']['attempts']) == 1


def test_connect_exception_subclass_records_only_known_error_enum(tmp_path):
    class SyntheticConnectError(httpx.ConnectError):pass
    def handler(req):raise SyntheticConnectError('synthetic-secret', request=req)
    _, provider, _ = fixture(tmp_path, handler)
    call = prepared(provider)
    result = run(provider, call['id'], authorization_hash=G)
    assert result['status'] == 'not_sent'
    assert result['attempts']['attempts'][0]['evidence']['error_class'] == 'ConnectError'
