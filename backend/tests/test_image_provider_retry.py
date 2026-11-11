"""Synthetic transport evidence: only a pre-response connect failure is not_sent."""
import asyncio

import httpx
import pytest

from backend.tests.test_image_provider import fixture


class BrokenBody(httpx.AsyncByteStream):
    def __init__(self, error):
        self.error = error

    async def __aiter__(self):
        raise self.error('synthetic response interrupted')
        yield b''


@pytest.mark.parametrize('error', [httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout])
def test_response_started_cannot_be_classified_as_not_sent_or_retried(tmp_path, error):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, stream=BrokenBody(error), headers={'x-request-id': 'synthetic-received'})

    _, provider, _ = fixture(tmp_path, handler)
    call = provider.prepare('p', 'response-started', 'synthetic prompt')
    result = asyncio.run(provider.execute('p', call['id']))
    assert result['status'] == 'unknown'
    assert result['result']['http_status'] == 200
    assert result['result']['request_id'] == 'synthetic-received'
    assert asyncio.run(provider.execute('p', call['id']))['status'] == 'unknown'
    assert len(requests) == 1


@pytest.mark.parametrize('error', [httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout])
def test_pre_response_connection_failure_stays_terminal_without_retry_authorization(tmp_path, error):
    requests = []

    def handler(request):
        requests.append(request)
        raise error('synthetic connection failure', request=request)

    _, provider, _ = fixture(tmp_path, handler)
    call = provider.prepare('p', 'not-sent', 'synthetic prompt')
    assert asyncio.run(provider.execute('p', call['id']))['status'] == 'not_sent'
    assert asyncio.run(provider.execute('p', call['id']))['status'] == 'not_sent'
    assert len(requests) == 1


@pytest.mark.parametrize('error', [httpx.WriteTimeout, httpx.ReadError, httpx.RemoteProtocolError])
def test_possibly_sent_transport_error_never_retries(tmp_path, error):
    requests = []

    def handler(request):
        requests.append(request)
        raise error('synthetic uncertain result', request=request)

    _, provider, _ = fixture(tmp_path, handler)
    call = provider.prepare('p', 'uncertain', 'synthetic prompt')
    assert asyncio.run(provider.execute('p', call['id']))['status'] == 'unknown'
    assert asyncio.run(provider.execute('p', call['id']))['status'] == 'unknown'
    assert len(requests) == 1


def test_cancelled_request_is_unknown_and_never_retried(tmp_path):
    requests = []

    def handler(request):
        requests.append(request)
        raise asyncio.CancelledError()

    _, provider, _ = fixture(tmp_path, handler)
    call = provider.prepare('p', 'cancelled', 'synthetic prompt')
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(provider.execute('p', call['id']))
    assert asyncio.run(provider.execute('p', call['id']))['status'] == 'unknown'
    assert len(requests) == 1
