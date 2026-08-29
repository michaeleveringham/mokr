from __future__ import annotations

import asyncio
import os
from collections.abc import Iterable
from typing import Any

from pyee import EventEmitter
import pytest


def pytest_collection_modifyitems(config, items) -> None:
    if os.environ.get("MOKR_RUN_INTEGRATION") == "1":
        return
    skip_integration = pytest.mark.skip(
        reason="set MOKR_RUN_INTEGRATION=1 to run browser integration tests"
    )
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)


class FakeDevtoolsClient:
    """Small recording stand-in for the DevTools client used by unit tests."""

    def __init__(self, responses: Iterable[Any] = ()) -> None:
        self._loop = asyncio.get_running_loop()
        self.calls: list[tuple[str, dict[str, Any] | None]] = []
        self._responses = iter(responses)

    async def send(
        self, method: str, params: dict[str, Any] | None = None
    ) -> Any:
        self.calls.append((method, params))
        response = next(self._responses, {})
        if isinstance(response, Exception):
            raise response
        return response


class FakeRequest:
    def __init__(self, url: str = "https://example.test/") -> None:
        self.url = url
        self._request_id = "request-1"
        self._from_memory_cache = False


class FakeConnection(EventEmitter):
    """Event-capable connection double for browser orchestration tests."""

    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        super().__init__()
        self._loop = asyncio.get_running_loop()
        self.url = "ws://browser.test/devtools"
        self.calls: list[tuple[str, dict[str, Any] | None]] = []
        self._responses = responses or {}
        self.closed_callback = None
        self.disposed = False

    def _set_closed_callback(self, callback) -> None:
        self.closed_callback = callback

    async def send(
        self, method: str, params: dict[str, Any] | None = None
    ) -> Any:
        self.calls.append((method, params))
        response = self._responses.get(method, {})
        if isinstance(response, Exception):
            raise response
        return response

    async def dispose(self) -> None:
        self.disposed = True
