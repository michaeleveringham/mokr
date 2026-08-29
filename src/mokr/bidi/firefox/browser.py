from __future__ import annotations

import asyncio
from typing import Any

from mokr.bidi.browser import BidiBrowser
from mokr.bidi.firefox.context import FirefoxBrowserContext
from mokr.bidi.firefox.page import FirefoxPage


class FirefoxBrowser(BidiBrowser):
    """Firefox-specific browser facade built on Firefox's native BiDi server."""

    def __init__(
        self,
        *args: Any,
        ignore_https_errors: bool = False,
        proxy_credentials: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._ignore_https_errors = ignore_https_errors
        # ``HttpDomain`` copies this mapping when it constructs its HTTPX
        # client, so preserve the CDP backend's empty-mapping convention.
        self._proxy_credentials = proxy_credentials or {}
        self._default_context = FirefoxBrowserContext(self, None)
        self._contexts: dict[str, FirefoxBrowserContext] = {}
        self._installed_extensions: list[str] = []
        self._credentials: tuple[str, str] | None = None
        self._auth_intercept: str | None = None

    async def create_incognito_browser_context(self) -> FirefoxBrowserContext:
        """Create an isolated Firefox user context."""
        context_id = await self._session.create_user_context()
        context = FirefoxBrowserContext(self, context_id)
        self._contexts[context_id] = context
        return context

    async def ready(self) -> FirefoxBrowser:
        """Discover initial pages and subscribe to Firefox frame lifecycle events."""
        await super().ready()
        await self._session.subscribe(
            ["browsingContext.load", "browsingContext.historyUpdated"]
        )
        return self

    async def install_extension(self, path: str) -> str:
        """Install a temporary Firefox WebExtension and return its identifier."""
        extension_id = await self._session.install_extension(path)
        self._installed_extensions.append(extension_id)
        return extension_id

    async def set_credentials(self, username: str, password: str = "") -> None:
        """Configure credentials used to answer Firefox authentication prompts."""
        self._credentials = (username, password)
        if self._auth_intercept is not None:
            return
        await self._session.subscribe(["network.authRequired"])
        self._auth_intercept = await self._session.add_intercept(
            ["authRequired"]
        )
        self._session.connection.on(
            "network.authRequired", self._on_auth_required
        )

    def _on_auth_required(self, event: dict[str, Any]) -> None:
        credentials = self._credentials
        task = asyncio.get_running_loop().create_task(
            self._session.continue_with_auth(
                event["request"],
                *(credentials or (None, None)),
            )
        )
        task.add_done_callback(self._log_background_task)

    def _register_context(self, context: dict[str, Any]) -> FirefoxPage:
        context_id = context["context"]
        page = self._pages.get(context_id)
        if page is None:
            page = FirefoxPage(
                self, context_id, context.get("url", "about:blank")
            )
            self._pages[context_id] = page
        user_context = context.get("userContext")
        self._page_contexts[context_id] = (
            user_context if user_context in self._contexts else None
        )
        return page

    def _context_created(self, event: dict[str, Any]) -> None:
        parent_id = event.get("parent")
        if parent_id:
            for page in self._pages.values():
                if parent_id in page._frames_by_context:
                    page._register_frame(event)
                    return
        super()._context_created(event)

    def _context_destroyed(self, event: dict[str, Any]) -> None:
        context_id = event["context"]
        for page in self._pages.values():
            if (
                context_id in page._frames_by_context
                and context_id != page._context_id
            ):
                page._remove_frame(context_id)
                return
        super()._context_destroyed(event)

    async def close(self) -> None:
        """Uninstall temporary extensions and close the Firefox browser."""
        for extension_id in reversed(self._installed_extensions):
            try:
                await self._session.uninstall_extension(extension_id)
            except Exception:
                pass
        self._installed_extensions.clear()
        if self._auth_intercept is not None:
            await self._session.remove_intercept(self._auth_intercept)
            self._auth_intercept = None
        await super().close()
