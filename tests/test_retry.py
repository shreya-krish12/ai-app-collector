"""429 handling: Retry-After honoured, backoff fallback, retry budget enforced."""

import httpx
import pytest

from app_collector.api.client import APIClient, UpstreamError, parse_retry_after


def scripted(*responses: httpx.Response) -> httpx.AsyncClient:
    queue = list(responses)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return queue.pop(0)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://x")
    client.seen = seen  # type: ignore[attr-defined]
    return client


async def test_page_2_429_is_retried_after_retry_after(mock_http, fake_sleep, simulator):
    api = APIClient(mock_http, sleep=fake_sleep)
    pages = [p async for p in api.iter_pages("acme")]

    statuses = [status for _, cursor, status in simulator.request_log if cursor]
    assert statuses == [429, 200]
    assert fake_sleep.calls == [1.0]  # exactly the server's Retry-After
    assert pages[1].attempts == 2


async def test_backoff_used_when_retry_after_missing(fake_sleep):
    http = scripted(httpx.Response(429), httpx.Response(429), httpx.Response(200, json={"ok": True}))
    api = APIClient(http, backoff_base=0.5, jitter=False, sleep=fake_sleep)

    response, attempts = await api.get_with_retry("/apps", {})

    assert response.status_code == 200 and attempts == 3
    assert fake_sleep.calls == [0.5, 1.0]  # 0.5 * 2^(n-1)


async def test_retry_budget_exhausted_raises(fake_sleep):
    http = scripted(*[httpx.Response(429, headers={"Retry-After": "0"}) for _ in range(4)])
    api = APIClient(http, max_retries=3, sleep=fake_sleep)

    with pytest.raises(UpstreamError, match="429 persisted after 4 attempts"):
        await api.get_with_retry("/apps", {})
    assert len(http.seen) == 4


async def test_non_retryable_status_fails_fast(fake_sleep):
    http = scripted(httpx.Response(401, json={"error": "bad token"}))
    with pytest.raises(UpstreamError, match="HTTP 401"):
        await APIClient(http, sleep=fake_sleep).get_with_retry("/apps", {})
    assert fake_sleep.calls == []


async def test_server_errors_are_retried(fake_sleep):
    http = scripted(httpx.Response(503), httpx.Response(200, json={}))
    _, attempts = await APIClient(http, jitter=False, sleep=fake_sleep).get_with_retry("/apps", {})
    assert attempts == 2


async def test_network_errors_are_retried(fake_sleep):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, json={})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://x")
    _, attempts = await APIClient(http, sleep=fake_sleep).get_with_retry("/apps", {})
    assert attempts == 2


async def test_retry_after_is_capped(fake_sleep):
    http = scripted(httpx.Response(429, headers={"Retry-After": "3600"}), httpx.Response(200, json={}))
    await APIClient(http, backoff_max=30, sleep=fake_sleep).get_with_retry("/apps", {})
    assert fake_sleep.calls == [30]


@pytest.mark.parametrize(
    "header, expected",
    [("2", 2.0), ("0", 0.0), (None, None), ("", None), ("soon", None),
     ("Wed, 21 Oct 2015 07:28:00 GMT", 0.0)],  # a date in the past -> no wait
)
def test_parse_retry_after(header, expected):
    assert parse_retry_after(header) == expected
