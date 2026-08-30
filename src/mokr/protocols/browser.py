from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Protocol

from mokr.protocols.page import Page

if TYPE_CHECKING:
    from mokr.protocols.context import BrowserContext


class Browser(Protocol):
    """
    Created upon connect to a browser.
    It is an abstract container for the individual pages and browser contexts.
    """

    def __init__(
        self,
        browser_type: str,
        *args: Any,
        close_callback: Callable | None = None,
        default_viewport: dict[str, Any] | None = None,
        default_user_agent: str | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Args:
            browser_type (Literal["chrome"]): The CDP browser type.
            close_callback (Callable | None, optional): Callback to run on
                close. Defaults to None.
            proxy_credentials: (dict | None, optional): Dictionary with proxy
                credentials keyed as "username" and "password". Credentials
                should be for the proxy the browser process is bound to.
            default_user_agent (str, optional): Default user agent to use on
                all new pages.
        """
        ...

    @property
    def kind(self) -> str:
        """The active browser backend kind."""
        ...

    @property
    def process(self) -> Any:
        """The local browser process, if this browser was launched locally."""
        ...

    @property
    def browser_contexts(self) -> list[BrowserContext]:
        """The default and isolated browser contexts."""
        ...

    async def first_page(self) -> Page | None:
        """Return the default context's first page, if present."""
        ...

    async def new_page(self) -> Page:
        """Create and return a page in the default browser context."""
        ...

    async def pages(self) -> list[Page]:
        """Return all open pages across contexts."""
        ...

    async def create_incognito_browser_context(self) -> BrowserContext:
        """Create and return an isolated browser context."""
        ...

    async def close(self) -> None:
        """Close the browser."""
        ...

    async def disconnect(self) -> None:
        """Disconnect without requesting browser shutdown."""
        ...
