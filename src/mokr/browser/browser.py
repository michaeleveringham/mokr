from __future__ import annotations

from subprocess import Popen
from typing import Any, Awaitable, Callable, Literal

from pyee import EventEmitter

from mokr.browser.context import BrowserContext
from mokr.browser.page import Page
from mokr.browser.target import Target
from mokr.connection import Connection
from mokr.constants import (
    BROWSER_GET_VERSION,
    DISCONNECTED,
    TARGET_CHANGED,
    TARGET_CREATE_BROWSER_CONTEXT,
    TARGET_CREATE_TARGET,
    TARGET_CREATED,
    TARGET_DESTROYED,
    TARGET_DISPOSE_BROWSER_CONTEXT,
    TARGET_INFO_CHANGED,
    TARGET_SET_DISCOVER_TARGETS,
    TARGET_TARGET_CREATED,
    TARGET_TARGET_DESTROYED,
)
from mokr.exceptions import BrowserError


class Browser(EventEmitter):
    def __init__(
        self,
        browser_type: Literal["chrome", "firefox"],
        connection: Connection,
        context_ids: list[str],
        ignore_https_errors: bool,
        default_viewport: dict | None,
        process: Popen | None = None,
        close_callback: Callable | None = None,
        proxy_credentials: dict | None = None,
        default_user_agent: str | None = None,
        **kwargs: Any,
    ) -> None:
        """
        This class is created upon connect to a browser. It is essentially a
        container for the individual pages and browser contexts.

        Args:
            browser_type (Literal["chrome", "firefox"]): The type of browser.
            connection (`mokr.network.Connection`): Websocket connection.
            context_ids (list[str]): Browser context identifiers.
            ignore_https_errors (bool): Ignore site security errors.
            default_viewport (dict | None): Default viewport configuration.
            process (Popen | None, optional): Local browser process, if any.
                Defaults to None.
            close_callback (Callable | None, optional): Callback to run on
                close. Defaults to None.
            proxy_credentials: (dict | None, optional): Dictionary with proxy
                credentials keyed as "username" and "password". Credentials
                should be for the proxy the browser process is bound to.
            default_user_agent (str, optional): Default user agent to use on
                all new pages.
        """
        super().__init__()
        self._browser_type = browser_type
        self._ignore_https_errors = ignore_https_errors
        self._default_viewport = default_viewport
        self._default_user_agent = default_user_agent
        self._process = process
        self._screenshot_task_queue: list = []
        self._connection = connection
        self._proxy_credentials = proxy_credentials
        self._version = None
        loop = self._connection._loop
        if close_callback:
            self._close_callback = close_callback
        else:
            self._close_callback = self._dummy_callback
        self._default_context = BrowserContext(self, None)
        self._contexts: dict[str, BrowserContext] = dict()
        for context_id in context_ids:
            self._contexts[context_id] = BrowserContext(self, context_id)
        self._targets: dict[str, Target] = dict()
        self._connection._set_closed_callback(
            lambda: self.emit(DISCONNECTED)
        )
        self._connection.on(
            TARGET_TARGET_CREATED,
            lambda event: loop.create_task(self._target_created(event)),
        )
        self._connection.on(
            TARGET_TARGET_DESTROYED,
            lambda event: loop.create_task(self._target_destroyed(event)),
        )
        self._connection.on(
            TARGET_INFO_CHANGED,
            lambda event: loop.create_task(self._target_info_changed(event)),
        )

    @property
    def kind(self) -> str:
        """One of "chrome" or "firefox"."""
        return self._browser_type

    @property
    def process(self) -> Popen | None:
        """The local browser process. If created via `mokr.connect`, will
        return None.
        """
        return self._process

    @property
    def version(self) -> str:
        """Get browser version (product from browser full version info.)"""
        return self._version['product'] if self._version else ''

    @property
    def user_agent(self) -> str:
        """
        Get the user agent the browser was spawned with or that is set as the
        default to override with. This can be overidden later again
        with `mokr.browser.Page.set_user_agent`.
        """
        default = self._version.get("userAgent", '') if self._version else ''
        return self._default_user_agent if self._default_user_agent else default

    @property
    def browser_contexts(self) -> list[BrowserContext]:
        """
        A list of all `mokr.browser.BrowserContext` instances attached to this
        browser. By default, this will be a single context.
        """
        return [self._default_context] + [
            context for context in self._contexts.values()
        ]

    @property
    def ws_endpoint(self) -> str:
        """
        The websocket URL that this `Browser`'s `mokr.connection.Connection`
        object is using.
        """
        return self._connection.url

    async def _get_version(self) -> Awaitable:
        return await self._connection.send(BROWSER_GET_VERSION)

    def _dummy_callback(self) -> Awaitable[None]:
        fut = self._connection._loop.create_future()
        fut.set_result(None)
        return fut

    def _emit_cascade(
        self,
        event: str,
        context: BrowserContext,
        *args,
        **kwargs,
    ) -> bool:
        # Emit the same event on this object and the given context.
        obj_result = self.emit(event, *args, **kwargs)
        context_result = context.emit(event, *args, **kwargs)
        return obj_result and context_result

    async def _dispose_context(self, context_id: str) -> None:
        await self._connection.send(
            TARGET_DISPOSE_BROWSER_CONTEXT,
            {'browserContextId': context_id},
        )
        self._contexts.pop(context_id, None)

    async def _target_created(self, event: dict) -> None:
        target_info = event['targetInfo']
        browser_context_id = target_info.get('browserContextId')
        if browser_context_id and browser_context_id in self._contexts:
            context = self._contexts[browser_context_id]
        else:
            context = self._default_context
        # Indicate if overriden to avoid needless override with the default.
        user_agent_data = {
            "overridden": True if self._default_user_agent else False,
            "user_agent": self.user_agent,
        }
        target = Target(
            self,
            target_info,
            context,
            lambda: self._connection.create_session(target_info),
            self._ignore_https_errors,
            self._default_viewport,
            self._screenshot_task_queue,
            self._connection._loop,
            self._proxy_credentials,
            user_agent_data,
        )
        if target_info['targetId'] in self._targets:
            raise BrowserError('Target should not exist before create.')
        self._targets[target_info['targetId']] = target
        if await target._initialized_promise:
            self._emit_cascade(TARGET_CREATED, context, target)

    async def _target_destroyed(self, event: dict) -> None:
        target = self._targets.pop(event['targetId'])
        target._closed_callback()
        if await target._initialized_promise:
            self._emit_cascade(
                TARGET_DESTROYED,
                target.browser_context,
                target,
            )
        target._initialized_callback(False)

    async def _target_info_changed(self, event: dict) -> None:
        target = self._targets.get(event['targetInfo']['targetId'])
        if not target:
            raise BrowserError('Target should exist before info changed.')
        previous_url = target.url
        was_initialized = target._is_initialized
        target._target_info_changed(event['targetInfo'])
        if was_initialized and previous_url != target.url:
            self._emit_cascade(
                TARGET_CHANGED,
                target.browser_context,
                target,
            )

    async def _create_page_in_context(self, context_id: str | None) -> Page:
        options = {'url': 'about:blank'}
        if context_id:
            options['browserContextId'] = context_id
        response = await self._connection.send(TARGET_CREATE_TARGET, options)
        target_id = response.get('targetId')
        target = self._targets.get(target_id)
        if target is None or not await target._initialized_promise:
            raise BrowserError('Failed to create target for page.')
        page = await target.page()
        if page is None:
            raise BrowserError('Failed to create page.')
        return page

    async def first_page(self) -> Page | None:
        """
        Return the first page in the default context's `BrowserContext.pages`.
        If no pages active, returns None.

        Returns:
            Page | None: First active page in the default context, if any.
        """
        return await self._default_context.first_page()

    async def ready(self) -> Browser:
        """
        Enable target discovery in the remote connection.

        Returns:
            Browser: This `Browser` class.
        """
        self._version = await self._get_version()
        await self._connection.send(
            TARGET_SET_DISCOVER_TARGETS,
            {'discover': True},
        )
        return self

    async def create_incognito_browser_context(self) -> BrowserContext:
        """
        Create a new browser context. This is akin to spawning an incognito
        browser window, it will not share cookies or storage with pages
        in other contexts. To do so, use `Browser.new_page` instead.

        Example::

            browser = await launch().launch()
            # Navigate and login or perform another storage-accessed action.
            context = await browser.create_incognito_browser_context()
            page = await context.first_page()
            # Navigate to the same site. Session isn't shared!
            ...

        Returns:
            BrowserContext: A new `mokr.browser.BrowserContext`.
        """
        obj = await self._connection.send(TARGET_CREATE_BROWSER_CONTEXT)
        browser_context_id = obj['browserContextId']
        context = BrowserContext(self, browser_context_id)
        self._contexts[browser_context_id] = context
        return context

    async def new_page(self) -> Page:
        """
        Spawn a new page within the default context.

        Returns:
            Page: A new `mokr.browser.Page` at "about:blank".
        """
        return await self._default_context.new_page()

    def targets(self) -> list[Target]:
        """
        A list of all `mokr.browser.Target`s in all contexts attached to this
        `Browser` object.

        Returns:
            list[Target]: All initialised targets within all contexts in
                this browser.
        """
        return [
            target for target in self._targets.values()
            if target._is_initialized
        ]

    async def pages(self) -> list[Page]:
        """
        A list of all `mokr.browser.Page`s in all contexts attached to this
        `Browser` object.

        Returns:
            list[Page]: All pages within all contexts in this browser.
        """
        return [
            page for page_list in [
                await context.pages() for context in self.browser_contexts
            ]
            for page in page_list
        ]

    async def close(self) -> None:
        """Run the `close_callback` given during initialisation."""
        await self._close_callback()

    async def disconnect(self) -> None:
        """
        Disconnect the `Browser`'s `Connection` object's websocket connection
        and fail any `Browser.targets` that haven't finished initialising.
        """
        await self._connection.dispose()
        for target in self._targets.values():
            if not target._is_initialized:
                target._initialized_callback(False)
