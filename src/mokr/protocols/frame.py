from __future__ import annotations

from typing import Any, Protocol

from mokr.protocols.element import Element


class Frame(Protocol):
    """Portable frame operations shared by browser backends."""

    @property
    def url(self) -> str:
        """The frame's current URL."""
        ...

    async def evaluate(self, page_function: str, *args: Any) -> Any:
        """Evaluate JavaScript in this frame with JSON-like arguments."""
        ...

    async def query_selector(self, selector: str) -> Element | None:
        """Return the first element matching a CSS selector, if any."""
        ...

    async def query_selector_all(self, selector: str) -> list[Element]:
        """Return all elements matching a CSS selector."""
        ...
