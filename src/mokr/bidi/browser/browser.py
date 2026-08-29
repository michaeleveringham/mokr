from __future__ import annotations

import asyncio
from typing import Any, Callable

from pyee import EventEmitter

from mokr.bidi.browser.context import BidiBrowserContext
from mokr.bidi.browser.page import BidiPage
from mokr.bidi.connection import BidiSession
from mokr.bidi.input import BidiDialog
from mokr.bidi.network import (
    BidiRequest,
    BidiResponse,
    run_interception_callbacks,
)


class BidiBrowser(EventEmitter):
    """Container for WebDriver BiDi pages and isolated user contexts."""

    def __init__(
        self,
        browser_type: str,
        session: BidiSession,
        process: Any = None,
        close_callback: Callable | None = None,
        default_viewport: dict[str, Any] | None = None,
        default_user_agent: str | None = None,
    ) -> None:
        """Create a browser facade over an active BiDi session.

        Args:
            browser_type: Active browser backend kind.
            session: WebDriver BiDi command facade.
            process: Local browser process, if mokr launched it.
            close_callback: Optional callback invoked during shutdown.
            default_viewport: Viewport applied to newly discovered pages.
            default_user_agent: User-agent override applied to new pages.
        """
        super().__init__()
        self._browser_type = browser_type
        self._session = session
        self._process = process
        self._close_callback = close_callback
        self._default_viewport = default_viewport
        self._default_user_agent = default_user_agent
        self._pages: dict[str, BidiPage] = {}
        self._page_contexts: dict[str, str | None] = {}
        self._network_subscribed = False
        self._default_context = BidiBrowserContext(self, None)
        self._contexts: dict[str, BidiBrowserContext] = {}

    @property
    def kind(self) -> str:
        """Return the browser backend kind."""
        return self._browser_type

    @property
    def process(self) -> Any:
        """Return the local browser process, if this browser was launched."""
        return self._process

    @property
    def browser_contexts(self) -> list[BidiBrowserContext]:
        """Return the default and isolated browser contexts."""
        return [self._default_context, *self._contexts.values()]

    async def ready(self) -> BidiBrowser:
        """Subscribe to lifecycle events and discover initial pages.

        Returns:
            This browser after its initial page state is ready.
        """
        await self._session.subscribe(
            [
                "browsingContext.contextCreated",
                "browsingContext.contextDestroyed",
                "browsingContext.navigationStarted",
                "browsingContext.userPromptOpened",
            ]
        )
        self._session.connection.on(
            "browsingContext.contextCreated", self._context_created
        )
        self._session.connection.on(
            "browsingContext.contextDestroyed", self._context_destroyed
        )
        self._session.connection.on(
            "browsingContext.userPromptOpened", self._user_prompt_opened
        )
        tree = await self._session.get_tree()
        for context in tree:
            await self._configure_page(self._register_context(context))
        if not self._pages:
            await self._create_page_in_context(None)
        return self

    async def first_page(self) -> BidiPage | None:
        """Return the default context's first page, if present."""
        return await self._default_context.first_page()

    async def new_page(self) -> BidiPage:
        """Create and return a page in the default context."""
        return await self._default_context.new_page()

    async def pages(self) -> list[BidiPage]:
        """Return all pages across browser contexts."""
        return list(self._pages.values())

    @property
    def ws_endpoint(self) -> str:
        """Return the WebDriver BiDi WebSocket endpoint."""
        return self._session.connection.url

    async def create_incognito_browser_context(self) -> BidiBrowserContext:
        """Create and return an isolated browser user context."""
        context_id = await self._session.create_user_context()
        context = BidiBrowserContext(self, context_id)
        self._contexts[context_id] = context
        return context

    async def _create_page_in_context(
        self, user_context: str | None
    ) -> BidiPage:
        context_id = await self._session.create_page(user_context)
        page = self._register_context(
            {
                "context": context_id,
                "url": "about:blank",
                "userContext": user_context,
            }
        )
        await self._configure_page(page)
        return page

    async def _configure_page(self, page: BidiPage) -> None:
        if self._default_viewport and page.viewport is None:
            await page.set_viewport(self._default_viewport)
        if self._default_user_agent and page.user_agent is None:
            await page.set_user_agent(self._default_user_agent)

    def _register_context(self, context: dict[str, Any]) -> BidiPage:
        context_id = context["context"]
        page = self._pages.get(context_id)
        if page is None:
            page = BidiPage(self, context_id, context.get("url", "about:blank"))
            self._pages[context_id] = page
        user_context = context.get("userContext")
        # CDP exposes an opaque browserContextId for some default-profile
        # targets. It is not a BiDi user context, so retain the existing
        # Browser convention of treating unknown ids as the default context.
        self._page_contexts[context_id] = (
            user_context if user_context in self._contexts else None
        )
        return page

    def _context_destroyed(self, event: dict[str, Any]) -> None:
        context_id = event["context"]
        page = self._pages.pop(context_id, None)
        self._page_contexts.pop(context_id, None)
        if page:
            page._closed = True

    def _context_created(self, event: dict[str, Any]) -> None:
        page = self._register_context(event)
        task = asyncio.get_running_loop().create_task(
            self._configure_page(page)
        )
        task.add_done_callback(self._log_background_task)

    async def _enable_network_for_page(
        self,
        page: BidiPage,
        intercept: bool,
        collect_response_data: bool,
    ) -> None:
        if not self._network_subscribed:
            await self._session.subscribe(
                [
                    "network.beforeRequestSent",
                    "network.responseStarted",
                    "network.responseCompleted",
                    "network.fetchError",
                ]
            )
            self._session.connection.on(
                "network.beforeRequestSent", self._before_request_sent
            )
            self._session.connection.on(
                "network.responseCompleted", self._response_completed
            )
            self._network_subscribed = True
        if intercept and page._request_intercept is None:
            page._request_intercept = await self._session.add_intercept(
                ["beforeRequestSent"], [page._context_id]
            )
        if collect_response_data and page._response_collector is None:
            page._response_collector = (
                await self._session.add_network_data_collector(
                    ["response"],
                    50 * 1024 * 1024,
                    [page._context_id],
                )
            )

    def _before_request_sent(self, event: dict[str, Any]) -> None:
        # ``session.subscribe`` observes every request, whereas only events
        # associated with an intercept are paused and may be continued.
        if not event.get("intercepts"):
            return
        page = self._pages.get(event.get("context"))
        if page is None:
            return
        task = asyncio.get_running_loop().create_task(
            run_interception_callbacks(
                BidiRequest(self._session, page, event), page._route_stack
            )
        )
        task.add_done_callback(self._log_background_task)

    def _response_completed(self, event: dict[str, Any]) -> None:
        page = self._pages.get(event.get("context"))
        if page:
            page.emit(
                "response",
                BidiResponse(self._session, event, page._response_collector),
            )

    def _user_prompt_opened(self, event: dict[str, Any]) -> None:
        page = self._pages.get(event["context"])
        if page:
            page.emit("dialog", BidiDialog(self._session, event))

    @staticmethod
    def _log_background_task(task: asyncio.Task) -> None:
        try:
            task.result()
        except (ConnectionError, RuntimeError):
            # Firefox may emit a late request event while the session closes, ignore it.
            pass

    async def close(self) -> None:
        """Close the browser through its configured close callback."""
        if self._close_callback:
            result = self._close_callback()
            if result is not None and asyncio.iscoroutine(result):
                await result

    async def disconnect(self) -> None:
        """Disconnect from the browser without requesting shutdown."""
        await self._session.connection.dispose()
