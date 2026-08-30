from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from mokr.protocols.page import Page

if TYPE_CHECKING:
    from mokr.protocols.browser import Browser


class BrowserContext(Protocol):
    """
    Browser context within the browser process.

    Contexts are independent of one another, not sharing storage.
    Contexts beyond the default context that `mokr.browser.Browser` starts
    with will be incognito.
    """

    def __init__(self, browser: Browser, context_id: str | None) -> None:
        """
        Args:
            browser (Browser): Parent `mokr.browser.Browser` object from which
                the context was spawned.
            context_id (str | None): The context identifier (may be None).
        """

    @property
    def incognito(self) -> bool:
        """Whether this is an isolated non-default context."""
        ...

    async def pages(self) -> list[Page]:
        """Return pages in this context."""
        ...

    async def first_page(self) -> Page | None:
        """Return this context's first page, if present."""
        ...

    async def new_page(self) -> Page:
        """Create and return a page in this context."""
        ...

    async def close(self) -> None:
        """Close this browser context."""
        ...
