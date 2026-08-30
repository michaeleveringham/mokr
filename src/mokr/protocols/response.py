from __future__ import annotations

from typing import Any, Protocol


class Response(Protocol):
    """Portable response metadata and body access."""

    @property
    def url(self) -> str:
        """The response URL."""
        ...

    @property
    def status(self) -> int:
        """The HTTP status code."""
        ...

    @property
    def ok(self) -> bool:
        """Whether the response has a non-error HTTP status."""
        ...

    @property
    def reason(self) -> str:
        """The HTTP reason text."""
        ...

    @property
    def headers(self) -> dict[str, str]:
        """Response headers, keyed case-insensitively in lowercase."""
        ...

    async def buffer(self) -> bytes:
        """Return the response body as bytes."""
        ...

    async def content(self) -> str:
        """Return the response body decoded as text."""
        ...

    async def json(self) -> Any:
        """Decode the response body as JSON."""
        ...

    async def to_dict(self) -> dict[str, Any]:
        """Return the response status, headers, and decoded body."""
        ...
