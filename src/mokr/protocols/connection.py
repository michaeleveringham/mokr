from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, Protocol


class Connection(Protocol):
    """The event-capable command transport shared by CDP and BiDi."""

    @property
    def url(self) -> str:
        """The transport WebSocket URL."""
        ...

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        """The event loop used by the transport."""
        ...

    def on(self, event: str, listener: Callable[..., Any]) -> Any:
        """Register a listener for a protocol event."""
        ...

    def remove_listener(self, event: str, listener: Callable[..., Any]) -> Any:
        """Remove a previously registered protocol-event listener."""
        ...

    async def send(
        self, method: str, params: dict[str, Any] | None = None
    ) -> Any:
        """Send a protocol command and return its result."""
        ...

    async def dispose(self) -> None:
        """Close the protocol transport and release resources."""
        ...
