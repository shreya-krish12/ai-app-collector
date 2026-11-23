"""Shared fixtures. Every test gets a fresh in-memory database."""

from __future__ import annotations

import httpx
import pytest

from app_collector.api.mock_api import MOCK_BASE_URL, build_mock_transport
from app_collector.api.upstream import UpstreamSimulator
from app_collector.api.upstream_server import create_upstream_app
from app_collector.collector.ingester import Collector
from app_collector.config import Mode, Settings
from app_collector.storage.db import Database


class FakeSleep:
    """Records requested delays instead of sleeping, so retry tests are instant."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


@pytest.fixture
def db(tmp_path) -> Database:
    # A real file (not :memory:) so concurrent tenant writes use separate
    # connections, exactly like production. tmp_path is per-test.
    database = Database(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    database.create_all()
    yield database
    database.engine.dispose()


@pytest.fixture
def fake_sleep() -> FakeSleep:
    return FakeSleep()


@pytest.fixture
def simulator() -> UpstreamSimulator:
    return UpstreamSimulator()


@pytest.fixture
def mock_http(simulator):
    """httpx client wired to the in-process mock transport."""
    return httpx.AsyncClient(transport=build_mock_transport(simulator), base_url=MOCK_BASE_URL)


@pytest.fixture
def make_collector(db, fake_sleep, simulator):
    """Collector whose mode switch is real but whose network is in-process.

    mock -> httpx.MockTransport
    real -> the actual FastAPI upstream app, called over HTTP via ASGITransport
    Both share `simulator`, so request counts can be asserted.
    """

    def factory() -> Collector:
        upstream_app = create_upstream_app(simulator)

        def http_factory(mode: Mode) -> httpx.AsyncClient:
            if mode is Mode.MOCK:
                return httpx.AsyncClient(transport=build_mock_transport(simulator), base_url=MOCK_BASE_URL)
            return httpx.AsyncClient(transport=httpx.ASGITransport(app=upstream_app), base_url="http://upstream.test")

        return Collector(db, Settings(), http_factory=http_factory, sleep=fake_sleep)

    return factory
