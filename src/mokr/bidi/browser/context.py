from __future__ import annotations

from typing import TYPE_CHECKING

from pyee import EventEmitter

if TYPE_CHECKING:
    from mokr.bidi.browser.browser import BidiBrowser
    from mokr.bidi.browser.page import BidiPage


class BidiBrowserContext(EventEmitter):
    """A storage-isolated WebDriver BiDi browser user context."""

    def __init__(self, browser: BidiBrowser, context_id: str | None) -> None:
        """Create a browser context.

        Args:
            browser: Parent BiDi browser.
            context_id: BiDi user-context identifier, or ``None`` for the
                default context.
        """
        super().__init__()
        self._browser = browser
        self._id = context_id

    @property
    def incognito(self) -> bool:
        """Whether this is a non-default isolated user context."""
        return self._id is not None

    @property
    def browser(self) -> BidiBrowser:
        """Return the browser that owns this context."""
        return self._browser

    async def pages(self) -> list[BidiPage]:
        """Return pages belonging to this context."""
        return [
            page
            for page in self._browser._pages.values()
            if self._browser._page_contexts.get(page._context_id) == self._id
        ]

    async def first_page(self) -> BidiPage | None:
        """Return this context's first page, if present."""
        pages = await self.pages()
        return pages[0] if pages else None

    async def new_page(self) -> BidiPage:
        """Create and return a page in this context."""
        return await self._browser._create_page_in_context(self._id)

    async def close(self) -> None:
        """Close this non-default user context and all of its pages.

        Raises:
            ValueError: If called for the default browser context.
        """
        if self._id is None:
            raise ValueError("The default browser context cannot be closed.")
        await self._browser._session.remove_user_context(self._id)
        self._browser._contexts.pop(self._id, None)
