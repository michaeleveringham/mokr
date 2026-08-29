from __future__ import annotations

from typing import Protocol


class Request(Protocol):
    """Portable request interception operations."""

    @property
    def url(self) -> str:
        """The intercepted request URL."""
        ...

    @property
    def method(self) -> str:
        """The intercepted HTTP method."""
        ...

    @property
    def headers(self) -> dict[str, str]:
        """Request headers, keyed case-insensitively in lowercase."""
        ...

    async def release(self) -> None:
        """Continue the intercepted request unchanged."""
        ...

    async def abort(self) -> None:
        """Fail the intercepted request."""
        ...

    async def fulfill(
        self,
        body: str | bytes = b"",
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Fulfill the intercepted request with a synthetic response."""
        ...
