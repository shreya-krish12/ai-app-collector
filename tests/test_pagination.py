"""Cursor pagination: all pages fetched, in order, and the loop terminates."""

import httpx
import pytest

from app_collector.api.client import APIClient, UpstreamError
from app_collector.api.upstream import PAGE_2_CURSOR, page_items


async def collect(api: APIClient, client_id: str):
    return [page async for page in api.iter_pages(client_id)]


async def test_fetches_both_pages_in_order(mock_http, fake_sleep):
    api = APIClient(mock_http, sleep=fake_sleep)
    pages = await collect(api, "acme")

    assert [p.number for p in pages] == [1, 2]
    assert [i["app_id"] for i in pages[0].items] == [i["app_id"] for i in page_items("acme", 1)]
    assert [i["app_id"] for i in pages[1].items] == [i["app_id"] for i in page_items("acme", 2)]


async def test_second_request_sends_next_cursor(mock_http, fake_sleep, simulator):
    await collect(APIClient(mock_http, sleep=fake_sleep), "acme")
    cursors = [cursor for client, cursor, _ in simulator.request_log]
    assert cursors[0] is None
    assert set(cursors[1:]) == {PAGE_2_CURSOR}


async def test_stops_when_next_cursor_is_null(mock_http, fake_sleep, simulator):
    await collect(APIClient(mock_http, sleep=fake_sleep), "vontier")
    # page 1, page 2 (429), page 2 (200) -- and nothing after that
    assert len(simulator.request_log) == 3


async def test_cursor_loop_is_detected(fake_sleep):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": [], "next_cursor": "same"})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://x")
    with pytest.raises(UpstreamError, match="cursor loop"):
        await collect(APIClient(http, sleep=fake_sleep), "acme")


async def test_malformed_page_raises(fake_sleep):
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"data": []})), base_url="http://x"
    )
    with pytest.raises(UpstreamError, match="no 'items' list"):
        await collect(APIClient(http, sleep=fake_sleep), "acme")
