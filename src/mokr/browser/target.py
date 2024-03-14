from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Callable, Literal

from mokr.browser.page import Page
from mokr.connection import DevtoolsConnection

if TYPE_CHECKING:
    from mokr.browser import Browser
    from mokr.browser.context import BrowserContext


KINDS = Literal["page", "background_page", "service_worker", "browser", "other"]


class Target():
    def __init__(
        self,
        browser: Browser,
        target_info: dict,
        browser_context: BrowserContext,
        session_factory: Callable,
        ignore_https_errors: bool,
        default_viewport: dict | None,
        screenshot_task_queue: list,
        loop: asyncio.AbstractEventLoop,
        proxy_credentials: dict | None = None,
        user_agent_data: dict[str, str] | None = None,
    ) -> None:
        """
        Representative of a remote target.
        Targets are a somewhat obscure concept, they can be a browser, frame,
        page, worker, or more. For the purposes of this package, only
        browser, pages, and workers are tracked explicitly.
        Full list of target types can be found at `devtools_agent_host_impl.cc`
        at https://source.chromium.org/chromium/chromium/src/.

        Args:
            browser (Browser): Parent `mokr.browser.Browser`.
            target_info (dict): The "targetInfo" in the event emitted that
                triggered this object's initialisation.
            browser_context (BrowserContext): The `mokr.browser.BrowserContext`
                that this spawned from.
            session_factory (Callable): Callable that creates a new
                `mokr.connection.DevtoolsConnection` for this target.
            ignore_https_errors (bool): Whether network security errors should
                be ignored or not. Inherited from parent `mokr.browser.Browser`.
            default_viewport (dict | None): Default viewport configuration.
                Inherited from parent `mokr.browser.Browser`.
            screenshot_task_queue (list): The screenshot task queue, empty by
                default. Inherited from parent `mokr.browser.Browser`.
            loop (asyncio.AbstractEventLoop): The `asyncio` loop that is tracked
                under the `mokr.browser.Browser`'s `mokr.connection.Connection`.
            proxy_credentials: (dict | None, optional): Dictionary with proxy
                credentials keyed as "username" and "password". Credentials
                should be for the proxy the browser process is bound to.
                Inherited from parent `mokr.browser.Browser`.
            user_agent_data (dict[str, str] | None, optional): A dictionary
                containing the user agent and an indicator to whether it was the
                original or an override.
        """
        self._browser = browser
        self._target_info = target_info
        self._browser_context = browser_context
        self._targetId = target_info.get('targetId', '')
        self._session_factory = session_factory
        self._ignore_https_errors = ignore_https_errors
        self._default_viewport = default_viewport
        self._user_agent_data = user_agent_data
        self._screenshot_task_queue = screenshot_task_queue
        self._loop = loop
        self._proxy_credentials = proxy_credentials
        self._page: Page | None = None
        self._initialized_promise = self._loop.create_future()
        self._is_closed_promise = self._loop.create_future()
        self._is_initialized = (
            self._target_info['type'] != 'page'
            or self._target_info['url'] != ''
        )
        if self._is_initialized:
            self._initialized_callback(True)

    @property
    def url(self) -> str:
        """Get url of this target."""
        return self._target_info['url']

    @property
    def kind(self) -> KINDS:
        """
        Get type of this target.
        Type may be on of "page", "background_page", "service_worker",
        "browser", or "other".
        """
        _type = self._target_info['type']
        if _type in ['page', 'background_page', 'service_worker', 'browser']:
            return _type
        return 'other'

    @property
    def browser(self) -> Browser:
        """
        The `mokr.browser.Browser` that owns the `mokr.browser.BrowserContext`
        that this target was initialised from.
        """
        return self._browser_context.browser

    @property
    def browser_context(self) -> BrowserContext:
        """`mokr.browser.BrowserContext` this target was initialised from."""
        return self._browser_context

    @property
    def opener(self) -> Target | None:
        """The parent `Target` that spawned this, if any."""
        opener_id = self._target_info.get('openerId')
        if opener_id is None:
            return None
        return self.browser._targets.get(opener_id)

    def _target_info_changed(self, target_info: dict) -> None:
        self._target_info = target_info
        if not self._is_initialized and (
            self._target_info['type'] != 'page'
            or self._target_info['url'] != ''
        ):
            self._is_initialized = True
            self._initialized_callback(True)
            return

    def _initialized_callback(self, result: bool) -> None:
        if self._initialized_promise.done():
            self._initialized_promise = self._loop.create_future()
        self._initialized_promise.set_result(result)

    def _closed_callback(self) -> None:
        self._is_closed_promise.set_result(None)

    async def create_devtools_connection(self) -> DevtoolsConnection:
        """
        Initialise the `mokr.connection.DevtoolsConnection` that will be bound
        to this `Target`.

        Returns:
            DevtoolsConnection: The new `mokr.connection.DevtoolsConnection`.
        """
        return await self._session_factory()

    async def page(self) -> Page | None:
        """
        Get the `mokr.browser.Page` object attached to this `Target`.
        Only applicable if `Target.kind` is "page" or "background_page".

        Returns:
            Page | None: Associated `mokr.browser.Page`, if any.
        """
        if (
            self._target_info['type'] in ['page', 'background_page']
            and self._page is None
        ):
            client = await self._session_factory()
            new_page = await Page.create(
                self._browser,
                client,
                self,
                self._ignore_https_errors,
                self._default_viewport,
                self._screenshot_task_queue,
                self._proxy_credentials,
                self._user_agent_data,
            )
            self._page = new_page
            return new_page
        return self._page
