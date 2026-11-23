"""Multi-tenant isolation: each client uses its own sanctioned_apps list and its own rows."""

import httpx

from app_collector.collector.ingester import Collector
from app_collector.config import CLIENTS, Mode, Settings


def by_app(records):
    return {r["app_id"]: r for r in records}


async def test_same_app_classified_differently_per_client(make_collector, db):
    await make_collector().run(Mode.MOCK)
    acme = by_app(db.list_records("acme"))
    vontier = by_app(db.list_records("vontier"))

    assert acme["chatgpt"]["classification"] == "sanctioned"      # on acme's list only
    assert vontier["chatgpt"]["classification"] == "unsanctioned"
    assert acme["claude"]["classification"] == "unsanctioned"     # on vontier's list only
    assert vontier["claude"]["classification"] == "sanctioned"
    assert acme["copilot"]["classification"] == vontier["copilot"]["classification"] == "sanctioned"


async def test_each_client_only_gets_its_own_rows(make_collector, db):
    await make_collector().run(Mode.MOCK)
    assert {r["client_id"] for r in db.list_records("acme")} == {"acme"}
    assert by_app(db.list_records("acme"))["chatgpt"]["users"] == 120
    assert by_app(db.list_records("vontier"))["chatgpt"]["users"] == 40


async def test_running_one_client_leaves_the_other_untouched(make_collector, db):
    collector = make_collector()
    await collector.run(Mode.MOCK, ["vontier"])
    before = db.list_records("vontier")
    run = await collector.run(Mode.MOCK, ["acme"])

    assert list(run.clients) == ["acme"]
    assert db.list_records("vontier") == before


async def test_one_client_failing_does_not_stop_the_other(db, fake_sleep):
    def handler(request):
        if request.url.params["client_id"] == "acme":
            return httpx.Response(500)
        return httpx.Response(200, json={"items": [{"app_id": "a", "app_name": "Claude"}], "next_cursor": None})

    collector = Collector(db, Settings(max_retries=1), sleep=fake_sleep,
                          http_factory=lambda m: httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://x"))
    run = await collector.run(Mode.MOCK)

    assert run.status == "partial"
    assert (run.clients["acme"].status, run.clients["vontier"].status) == ("failed", "completed")
    assert (db.count_records("acme"), db.count_records("vontier")) == (0, 1)


def test_list_matching_ignores_case_and_spaces():
    assert CLIENTS["acme"].classify("  github   COPILOT ") == "sanctioned"
    assert CLIENTS["acme"].classify("Claude") == "unsanctioned"
