from __future__ import annotations

from typing import Protocol


class Element(Protocol):
    """Portable DOM-element operations shared by browser backends."""

    async def click(self) -> None:
        """Click this element."""
        ...

    async def content(self) -> str:
        """Return this element's serialized HTML."""
        ...

    async def bounding_box(self) -> dict[str, float] | None:
        """Return this element's viewport bounding box, if attached."""
        ...
