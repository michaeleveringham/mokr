from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pyee import EventEmitter

from mokr.cdp.browser.page import CdpPage
from mokr.cdp.browser.target import CdpTarget
from mokr.exceptions import BrowserError

if TYPE_CHECKING:
    from mokr.cdp.browser import CdpBrowser


LOGGER = logging.getLogger(__name__)


class CdpBrowserContext(EventEmitter):
    """A storage-isolated Chrome DevTools Protocol browser context."""

    def __init__(self, browser: CdpBrowser, context_id: str | None) -> None:
        super().__init__()
        self._browser = browser
        self._id = context_id

    @property
    def incognito(self) -> bool:
        """
        True if the browser context is incognito, otherwise False. Only default
        context spawned when the `mokr.browser.Browser` object is spawned is
        not incognito.
        """
        return bool(self._id)

    @property
    def browser(self) -> CdpBrowser:
        """The `mokr.browser.Browser` object this context is attached to."""
        return self._browser

    def targets(self) -> list[CdpTarget]:
        """
        A list of all `mokr.cdp.browser.CdpTarget`s in this context.

        Returns:
            list[CdpTarget]: All initialised targets within this context.
        """
        return [
            target
            for target in self._browser.targets()
            if target.browser_context == self
        ]

    async def pages(self) -> list[CdpPage]:
        """
        A list of all `mokr.browser.Page`s in this context.

        Returns:
            list[Page]: All pages within this context.
        """
        page_targets = [
            target for target in self.targets() if target.kind == "page"
        ]
        return [target._page for target in page_targets if await target.page()]

    async def first_page(self) -> CdpPage:
        """
        Return the first page in `BrowserContext.pages`.
        If no pages active, returns None.

        Returns:
            Page | None: First active page in this context, if any.
        """
        pages = await self.pages()
        if pages:
            return pages[0]

    async def new_page(self) -> CdpPage:
        """
        Spawn a new page.

        Returns:
            Page: A new `mokr.browser.Page` at "about:blank".
        """
        return await self._browser._create_page_in_context(self._id)

    async def close(self) -> None:
        """
        Close the context. Can only be done on incognito contexts.

        Raises:
            BrowserError: Raised if called from the default context.
        """
        if self._id is None:
            raise BrowserError("Non-incognito profile cannot be closed.")
        await self._browser._dispose_context(self._id)
