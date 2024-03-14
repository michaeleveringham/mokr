from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pyee import EventEmitter

from mokr.browser.page import Page
from mokr.browser.target import Target
from mokr.exceptions import BrowserError

if TYPE_CHECKING:
    from mokr.browser import Browser


LOGGER = logging.getLogger(__name__)


class BrowserContext(EventEmitter):
    def __init__(self, browser: Browser, context_id: str | None) -> None:
        """
        Browser context within the browser process. Contexts are independent
        of one another, not sharing storage. Contexts beyond the default
        context that `mokr.browser.Browser` starts with will be incognito.

        Args:
            browser (Browser): Parent `mokr.browser.Browser` object from which
                the context was spawned.
            context_id (str | None): The context identifier (may be None).
        """
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
    def browser(self) -> Browser:
        """The `mokr.browser.Browser` object this context is attached to."""
        return self._browser

    def targets(self) -> list[Target]:
        """
        A list of all `mokr.browser.Target`s in this context.

        Returns:
            list[Target]: All initialised targets within this context.
        """
        return [
            target for target in self._browser.targets()
            if target.browser_context == self
        ]

    async def pages(self) -> list[Page]:
        """
        A list of all `mokr.browser.Page`s in this context.

        Returns:
            list[Page]: All pages within this context.
        """
        page_targets = [
            target for target in self.targets() if target.kind == "page"
        ]
        return [target._page for target in page_targets if await target.page()]

    async def first_page(self) -> Page:
        """
        Return the first page in `BrowserContext.pages`.
        If no pages active, returns None.

        Returns:
            Page | None: First active page in this context, if any.
        """
        pages = await self.pages()
        if pages:
            return pages[0]

    async def new_page(self) -> Page:
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
            raise BrowserError('Non-incognito profile cannot be closed.')
        await self._browser._dispose_context(self._id)
