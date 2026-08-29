from __future__ import annotations

import asyncio
from types import SimpleNamespace

from mokr.cdp.network.fetch import CdpFetchDomain


class ReadyEventWaiter:
    def __init__(self, *args, **kwargs) -> None:
        self._loop = args[-1]

    def wait(self):
        future = self._loop.create_future()
        future.set_result(None)
        return future


async def test_fetch_schedules_request_coroutine_before_waiting(
    monkeypatch,
) -> None:
    loop = asyncio.get_running_loop()
    page = SimpleNamespace(
        _network_manager=SimpleNamespace(
            _protocol_request_interception_enabled=True
        ),
        _default_navigation_timeout=100,
        _client=SimpleNamespace(_loop=loop),
        _interception_callback_chain=[],
        on=lambda *args: None,
    )
    fetch_domain = object.__new__(CdpFetchDomain)
    fetch_domain._page = page
    fetch_domain._requests_in_flight = set()
    page._interception_callback_chain = [fetch_domain._register_requests]
    expected_response = object()

    async def fake_fetch(request_uuid: str, url: str, params: dict) -> None:
        fetch_domain._requests_in_flight.add(request_uuid)

    async def fake_wait(futures, **kwargs):
        assert all(asyncio.isfuture(future) for future in futures)
        assert any(isinstance(future, asyncio.Task) for future in futures)
        await asyncio.gather(*futures)
        return set(futures), set()

    monkeypatch.setattr(
        "mokr.cdp.network.fetch.CdpEventWaiter", ReadyEventWaiter
    )
    monkeypatch.setattr("mokr.cdp.network.fetch.asyncio.wait", fake_wait)
    fetch_domain._fetch = fake_fetch
    fetch_domain._select_response = lambda request_uuid: expected_response

    assert (
        await fetch_domain.fetch("https://example.test/") is expected_response
    )
