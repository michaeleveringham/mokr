from __future__ import annotations

import base64
import json
from typing import Any

from mokr.bidi.connection import BidiSession
from mokr.bidi.network._utils import headers_to_dict


class BidiResponse:
    """Representation of a response received through WebDriver BiDi.

    Event-backed responses retrieve their body from a network data collector.
    Responses created by :class:`BidiFetchDomain` retain the body returned by
    the page's JavaScript ``fetch`` call instead.
    """

    def __init__(
        self,
        session: BidiSession,
        event: dict[str, Any],
        collector: str | None,
    ) -> None:
        """Create a response from a BiDi ``responseCompleted`` event.

        Args:
            session: Remote BiDi session used to retrieve body data.
            event: ``network.responseCompleted`` event payload.
            collector: Network data collector registered before the request,
                if response bodies were enabled.
        """
        self._session = session
        self._request_id = event["request"]["request"]
        self._payload = event["response"]
        self._navigation_id = event.get("navigation")
        self._collector = collector
        self._body: bytes | None = None

    @classmethod
    def from_fetch(cls, payload: dict[str, Any]) -> BidiResponse:
        """Create a response from a serialized page-context fetch result.

        Args:
            payload: Response metadata and a base64-encoded body returned by
                :class:`BidiFetchDomain`.

        Returns:
            A response whose body is retained in memory.
        """
        response = cls.__new__(cls)
        response._session = None
        response._request_id = None
        response._payload = {
            **payload,
            "headers": [
                {
                    "name": name,
                    "value": {"type": "string", "value": value},
                }
                for name, value in payload.get("headers", [])
            ],
        }
        response._navigation_id = None
        response._collector = None
        response._body = base64.b64decode(payload["body"])
        return response

    @property
    def navigation_id(self) -> str | None:
        """Return the BiDi navigation associated with this response, if any."""
        return self._navigation_id

    @property
    def url(self) -> str:
        """Return the response URL."""
        return self._payload["url"]

    @property
    def status(self) -> int:
        """Return the HTTP status code."""
        return self._payload["status"]

    @property
    def ok(self) -> bool:
        """Whether the response has a non-error HTTP status."""
        return self.status == 0 or not 400 <= self.status < 599

    @property
    def reason(self) -> str:
        """Return the HTTP reason text supplied by the browser."""
        return self._payload.get("statusText", "")

    @property
    def headers(self) -> dict[str, str]:
        """Return response headers keyed case-insensitively in lowercase."""
        return headers_to_dict(self._payload.get("headers", []))

    async def buffer(self) -> bytes:
        """Return the response body as bytes, retrieving it once if needed."""
        if self._body is not None:
            return self._body
        if self._collector is None:
            raise RuntimeError(
                "Response bodies were not enabled before this request. "
                "Register the response listener before navigating."
            )
        data = await self._session.get_network_data(
            self._request_id, self._collector
        )
        if isinstance(data, dict):
            data_type = data.get("type")
            value = data.get("value", "")
            self._body = (
                base64.b64decode(value)
                if data_type == "base64"
                else value.encode()
            )
        elif isinstance(data, str):
            self._body = data.encode()
        else:
            raise RuntimeError(
                "The browser returned an invalid BiDi network data payload."
            )
        return self._body

    async def content(self) -> str:
        """Return the response body decoded as UTF-8 text."""
        return (await self.buffer()).decode()

    async def json(self) -> Any:
        """Decode the response body as JSON."""
        return json.loads(await self.content())

    async def to_dict(self) -> dict[str, Any]:
        """Return the response status, headers, and decoded body."""
        return {
            "status": self.status,
            "headers": self.headers,
            "body": await self.content(),
        }
