"""
Mock mode transport: answers requests in-process with httpx.MockTransport,
using the shared UpstreamSimulator. No sockets are opened.
"""

from __future__ import annotations

import httpx

from app_collector.api.upstream import UpstreamSimulator

MOCK_BASE_URL = "http://mock-upstream.local"


def build_mock_transport(simulator: UpstreamSimulator) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path != "/apps":
            return httpx.Response(404, json={"error": "not found"})
        result = simulator.handle(
            request.url.params.get("client_id"),
            request.url.params.get("cursor"),
        )
        return httpx.Response(result.status_code, json=result.body, headers=result.headers)

    return httpx.MockTransport(handler)
