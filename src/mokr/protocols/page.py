from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol


class Page(Protocol):
    """Portable page operations returned by :func:`mokr.launch`."""

    @property
    def url(self) -> str:
        """The page's current URL."""
        ...

    @property
    def is_closed(self) -> bool:
        """Whether the page has been closed."""
        ...

    def on(self, event: str, listener: Callable[..., Any]) -> Any:
        """Register an event listener or request-interception callback."""
        ...

    async def goto(
        self, url: str, timeout: int | None = None, wait_until: str = "load"
    ) -> Any:
        """Navigate to a URL and wait for the requested readiness state."""
        ...

    async def content(self) -> str:
        """Return the current document's serialized HTML."""
        ...

    async def set_content(self, html: str) -> None:
        """Replace the current document's HTML."""
        ...

    async def evaluate(self, page_function: str, *args: Any) -> Any:
        """Evaluate JavaScript in this page with JSON-like arguments."""
        ...

    async def screenshot(self, **kwargs: Any) -> bytes | str:
        """Capture a screenshot of the page."""
        ...

    async def close(self, run_before_unload: bool = False) -> None:
        """Close the page."""
        ...
