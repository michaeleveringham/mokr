from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from mokr.core.http.request import HttpRequest


class HttpResponse:
    """Protocol-neutral response produced by :class:`HttpDomain`."""

    def __init__(self, response: httpx.Response, request: HttpRequest) -> None:
        self._httpx_response = response
        self._request = request
        self._content: bytes | None = None

    def __repr__(self) -> str:
        return f"<HttpResponse ({self.status}: {self.reason}) at {id(self)}>"

    @property
    def url(self) -> str:
        """Return the response URL."""
        return str(self._httpx_response.url)

    @property
    def ok(self) -> bool:
        """Whether the response has a non-error status."""
        return self.status == 0 or not 400 <= self.status < 599

    @property
    def status(self) -> int:
        """Return the HTTP status code."""
        return self._httpx_response.status_code

    @property
    def extra_status_info(self) -> None:
        """HTTPX responses do not carry CDP extra status information."""
        return None

    @property
    def reason(self) -> str:
        """Return the HTTP reason phrase."""
        return self._httpx_response.reason_phrase

    @property
    def headers(self) -> dict[str, str]:
        """Return response headers with lowercase keys."""
        return {
            name.lower(): value
            for name, value in self._httpx_response.headers.items()
        }

    @property
    def security_details(self) -> None:
        """HTTPX responses do not expose browser security details."""
        return None

    @property
    def request(self) -> HttpRequest:
        """Return the request paired with this response."""
        return self._request

    @property
    def from_cache(self) -> bool:
        """Return ``False`` because browser cache metadata is unavailable."""
        return False

    @property
    def from_service_worker(self) -> bool:
        """Return ``False`` because this request bypassed the browser."""
        return False

    @property
    def httpx_response(self) -> httpx.Response:
        """Return the underlying HTTPX response."""
        return self._httpx_response

    async def buffer(self, force: bool = False) -> bytes:
        """Return the response body as bytes."""
        if self._content is None or force:
            self._content = await asyncio.to_thread(self._httpx_response.read)
        return self._content

    async def content(self) -> str | bytes:
        """Return the response body as text, or bytes when undecodable."""
        content = await self.buffer()
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError:
            return content

    async def json(self) -> Any:
        """Decode the response body as JSON."""
        return json.loads(await self.content())

    async def to_dict(self) -> dict[str, Any]:
        """Return status, headers, and body in a dictionary."""
        return {
            "status": self.status,
            "headers": self.headers,
            "body": await self.content(),
        }
