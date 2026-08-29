from __future__ import annotations

from typing import TYPE_CHECKING

from mokr.bidi.browser import BidiBrowserContext

if TYPE_CHECKING:
    from mokr.bidi.firefox.browser import FirefoxBrowser
    from mokr.bidi.firefox.page import FirefoxPage


class FirefoxBrowserContext(BidiBrowserContext):
    """A Firefox browser user context controlled through native BiDi."""

    def __init__(self, browser: FirefoxBrowser, context_id: str | None) -> None:
        """Create a Firefox browser context.

        Args:
            browser: Parent Firefox browser.
            context_id: BiDi user-context identifier, or ``None`` for the
                default context.
        """
        super().__init__(browser, context_id)

    async def new_page(self) -> FirefoxPage:
        """Create and return a Firefox BiDi page in this context."""
        return await self._browser._create_page_in_context(self._id)
