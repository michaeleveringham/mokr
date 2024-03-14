from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Literal, Set

from mokr.connection import DevtoolsConnection
from mokr.constants import (
    METHOD_EMBED_JAVASCRIPT_BY_CONTENT,
    METHOD_EMBED_JAVASCRIPT_BY_URL,
    METHOD_EMBED_STYLE_BY_CONTENT,
    METHOD_EMBED_STYLE_BY_URL,
    METHOD_GET_CONTENT,
    METHOD_SELECT_VALUES,
    METHOD_SET_CONTENT,
    METHOD_WAIT_FOR_XPATH_OR_SELECTOR,
)
from mokr.exceptions import ElementHandleError, PageError
from mokr.execution.context import ExecutionContext, JavascriptHandle
from mokr.execution.handle.element import ElementHandle
from mokr.frame.wait import WaitTask


LOGGER = logging.getLogger(__name__)


class Frame():
    def __init__(
        self,
        client: DevtoolsConnection,
        parent_frame: Frame | None,
        frame_id: str,
    ) -> None:
        """
        Representative of a frame within a page, spawned from a
        `mokr.frame.FrameManager` in a `mokr.browser.Page`.

        Args:
            client (DevtoolsConnection): `mokr.execution.ExecutionContext` of
                the `mokr.frame.FrameManager` that spawned this.
            parent_frame (Frame | None): Parent `Frame` in tree, if any.
            frame_id (str): Unique remote identifier.
        """
        self._client = client
        self._parent_frame = parent_frame
        self._url = ''
        self._detached = False
        self._id = frame_id
        self._document_promise: ElementHandle | None = None
        self._context_resolve_callback = lambda _: None
        self._navigation_url = None
        self._set_default_context(None)
        self._wait_tasks: Set[WaitTask] = set()
        self._loader_id = ''
        self._lifecycle_events: Set[str] = set()
        self._child_frames: Set[Frame] = set()
        if self._parent_frame:
            self._parent_frame._child_frames.add(self)

    @property
    def name(self) -> str:
        """Get the name of the remote frame."""
        return self.__dict__.get('_name', '')

    @property
    def url(self) -> str:
        """The URL for the remote frame."""
        return self._url

    @property
    def parent_frame(self) -> Frame | None:
        """
        The parent `Frame` in the tree. If the remote frame is the top or is
        detached, will return None.
        """
        return self._parent_frame

    @property
    def child_frames(self) -> list[Frame]:
        """A list of all child `Frame`s in the tree."""
        return list(self._child_frames)

    @property
    def is_detached(self) -> bool:
        """True if remote frame is detached to the page, otherwise False."""
        return self._detached

    def _add_execution_context(self, context: ExecutionContext) -> None:
        if context._is_default:
            self._set_default_context(context)

    def _remove_execution_context(self, context: ExecutionContext) -> None:
        if context._is_default:
            self._set_default_context(None)

    def _set_default_context(self, context: ExecutionContext | None) -> None:
        if context is not None:
            self._context_resolve_callback(context)
            self._context_resolve_callback = lambda _: None
            for wait_task in self._wait_tasks:
                self._client._loop.create_task(wait_task.rerun())
        else:
            self._document_promise = None
            self._context_promise = self._client._loop.create_future()
            self._context_resolve_callback = (
                lambda _context: self._context_promise.set_result(_context)
            )

    def _wait_for_selector_or_xpath(
        self,
        selector_or_xpath: str,
        is_xpath: bool,
        visible: bool = False,
        hidden: bool = False,
        timeout: int = 30000,
    ) -> WaitTask:
        polling = 'raf' if hidden or visible else 'mutation'
        title = (
            f'{"XPath" if is_xpath else "selector"} "{selector_or_xpath}"'
            f'{" to be hidden" if hidden else ""}'
        )
        return WaitTask(
            self,
            METHOD_WAIT_FOR_XPATH_OR_SELECTOR,
            title,
            polling,
            timeout,
            self._client._loop,
            selector_or_xpath,
            is_xpath,
            visible,
            hidden,
        )

    def _navigated(self, frame_payload: dict) -> None:
        self._name = frame_payload.get('name', '')
        self._navigation_url = frame_payload.get('url', '')
        self._url = frame_payload.get('url', '')

    def _navigated_within_document(self, url: str) -> None:
        self._url = url

    def _on_lifecycle_event(self, loader_id: str, name: str) -> None:
        if name == 'init':
            self._loader_id = loader_id
            self._lifecycle_events.clear()
        else:
            self._lifecycle_events.add(name)

    def _on_loading_stopped(self) -> None:
        self._lifecycle_events.add('DOMContentLoaded')
        self._lifecycle_events.add('load')

    def _detach(self) -> None:
        for wait_task in self._wait_tasks:
            wait_task.terminate(
                PageError('Method wait_for_* failed: Frame detached.'))
        self._detached = True
        if self._parent_frame:
            self._parent_frame._child_frames.remove(self)
        self._parent_frame = None

    async def _ensure_execution_context(self) -> ExecutionContext:
        context = await self.execution_context()
        if context is None:
            raise PageError('Frame has no context.')
        return context

    async def _ensure_handle(self, selector: str) -> ElementHandle:
        handle = await self.query_selector(selector)
        if not handle:
            raise PageError(f'No node found for selector: {selector}')
        return handle

    async def _document(self) -> ElementHandle:
        if self._document_promise:
            return self._document_promise
        context = await self._ensure_execution_context()
        document = (await context.evaluate_handle('document'))._as_element()
        self._document_promise = document
        if document is None:
            raise PageError('Could not find document.')
        return document

    async def execution_context(self) -> ExecutionContext | None:
        """
        Return the newly created `mokr.execution.ExecutionContext`.
        Created by `mokr.frame.FrameManager`.

        Returns:
            ExecutionContext: `mokr.execution.ExecutionContext`.
        """
        return await self._context_promise

    async def evaluate_handle(
        self,
        page_function: str,
        *args: Any,
    ) -> JavascriptHandle:
        """
        Execute a JavaScript function with given arguments.
        Runs this `Frame`'s `mokr.execution.ExecutionContext.evaluate_handle`.

        Args:
            page_function (str): JavaScript function to run.

        Returns:
            JavascriptHandle: `mokr.execution.JavascriptHandle`.
        """
        context = await self._ensure_execution_context()
        return await context.evaluate_handle(page_function, *args)

    async def evaluate(
        self,
        page_function: str,
        *args: Any,
        force_expr: bool = False,
    ) -> Any:
        """
        Execute a JavaScript function with given arguments.
        Runs this `Frame`'s `mokr.execution.ExecutionContext.evaluate`.

        Args:
            page_function (str): JavaScript function to run.
            force_expr (bool): If True, treat `page_function` as an expression.
                Otherwise, automatically determine if it is a function or
                an expression. Defaults to False.

        Raises:
            `mokr.exceptions.NetworkError` if an unhandled error occurs
            either evaluating the function or requesting the resulting object.

        Returns:
            dict | None: The decoded object (dict) via
                `mokr.execution.JavascriptHandle.json` or None if a known
                error occurs decoding it.
        """
        context = await self._ensure_execution_context()
        return await context.evaluate(
            page_function,
            *args,
            force_expr=force_expr,
        )

    async def query_selector(self, selector: str) -> ElementHandle | None:
        """
        Return the first element in the DOM that matches the selector, if any.

        Args:
            selector (str): Element selector to locate.

        Returns:
            ElementHandle | None: ElementHandle if found or None.
        """
        document = await self._document()
        value = await document.query_selector(selector)
        return value

    async def query_selector_all(self, selector: str) -> list[ElementHandle]:
        """
        Return all elements in the DOM that match the selector, if any.

        Args:
            selector (str): Element selector to locate.

        Returns:
            list[ElementHandle]: List of ElementHandle if any or empty list.
        """
        document = await self._document()
        value = await document.query_selector_all(selector)
        return value

    async def xpath(self, expression: str) -> list[ElementHandle]:
        """
        Return all elements in the DOM that match the expression, if any.

        Args:
            expression (str): XPath expression to evaluate.

        Returns:
            list[ElementHandle]: List of ElementHandle if any or empty list.
        """
        document = await self._document()
        value = await document.xpath(expression)
        return value

    async def content(self) -> str:
        """
        Get encoded string representation of HTML in this `Frame`.

        Returns:
            str: HTML content.
        """
        return await self.evaluate(METHOD_GET_CONTENT.strip())

    async def set_content(self, html: str) -> None:
        """
        Set the value of the HTML on this `Frame`.

        This does not change the value of the "document" request's response,
        it only changes what is shown in the window.

        Response values can be changed by intercepting requests or responses,
        see `Page.on` for more.

        Args:
            html (str): HTML content to set to.
        """
        await self.evaluate(METHOD_SET_CONTENT, html)

    async def embed_javascript(
        self,
        file_content: str = None,
        file_path: str = None,
        url: str = None,
        script_type: str = None,
    ) -> ElementHandle:
        """
        Add script tag to this `Frame`.

        Args:
            file_content (str, optional): Encoded file content for script to
                embed. If not given, must give `file_path` or `url`. Defaults
                to None.
            file_path (str, optional): File path for script to embed.
                If not given, must give `file_content` or `url`. Defaults to
                None.
            url (str, optional): URL for script to embed. If not given, must
                give `file_content` or `file_path`. Defaults to None.
            script_type (str, optional): Use "module" to load as JavaScript
                ES6 module, if not given, defaults to "text/javascript".
                Defaults to None.

        Raises:
            ValueError: Raised if none of `file_content`, `file_path`, or
                `url` are given.
            PageError: Raised if error occurs sending embed request to remote
                connection (from ElementHandleError).

        Returns:
            ElementHandle: Newly embedded element.
        """
        if not any(url, file_path, file_content):
            raise ValueError("Must provide url, file_path, or file_content.")
        context = await self._ensure_execution_context()
        if file_content:
            args = [METHOD_EMBED_JAVASCRIPT_BY_CONTENT, file_content]
        elif file_path:
            with open(file_path) as f:
                contents = f.read()
            contents = contents + '//# sourceURL={}'.format(
                file_path.replace('\n', '')
            )
            args = [METHOD_EMBED_JAVASCRIPT_BY_CONTENT, contents]
        elif url:
            args = [METHOD_EMBED_JAVASCRIPT_BY_URL, url]
        if script_type:
            args.append(script_type)
        try:
            return (await context.evaluate_handle(*args))._as_element()
        except ElementHandleError:
            raise PageError('Failed to embed script, likely a network error.')

    async def embed_style(
        self,
        file_content: str = None,
        file_path: str = None,
        url: str = None,
    ) -> ElementHandle:
        """
        Add style tag to this `Frame`.

        Args:
            file_content (str, optional): Encoded file content for style to
                embed. If not given, must give `file_path` or `url`. Defaults
                to None.
            file_path (str, optional): File path for style to embed.
                If not given, must give `file_content` or `url`. Defaults to
                None.
            url (str, optional): URL for style to embed. If not given, must
                give `file_content` or `file_path`. Defaults to None.

        Raises:
            ValueError: Raised if none of `file_content`, `file_path`, or
                `url` are given.
            PageError: Raised if error occurs sending embed request to remote
                connection (from ElementHandleError).

        Returns:
            ElementHandle: Newly embedded element.
        """
        if not any(url, file_path, file_content):
            raise ValueError("Must provide url, file_path, or file_content.")
        context = await self._ensure_execution_context()
        if file_content:
            args = [METHOD_EMBED_STYLE_BY_CONTENT, file_content]
        elif file_path:
            with open(file_path) as f:
                contents = f.read()
            contents = contents + '/*# sourceURL={}*/'.format(
                file_path.replace('\n', '')
            )
            args = [METHOD_EMBED_STYLE_BY_CONTENT, contents]
        elif url:
            args = [METHOD_EMBED_STYLE_BY_URL, url]
        try:
            return (await context.evaluate_handle(*args))._as_element()
        except ElementHandleError:
            raise PageError('Failed to embed style, likely a network error.')

    async def click(
        self,
        selector: str,
        button: Literal["left", "right", "middle"] = "left",
        click_count: int = 1,
        delay: int | float | None = 1000,
    ) -> None:
        """
        Click the first element that matches `selector`.

        This method is a shortcut for running `Frame.query_selector` and then
        running `mokr.execution.ElementHandle.click` on the resultant
        ElementHandle. In either case, an element will be scrolled into view
        if needed, and the center of it clicked with the ElementHandle's
        bound `Page.mouse`.

        Args:
            selector (str): Selector to query element by.
            button (Literal["left", "right", "middle"], optional): Mouse button
                to click with. Defaults to "left".
            click_count (int, optional): Number of clicks to run. Defaults to 1.
            delay (int | float | None, optional): Time in milliseconds to wait
                before each click. Defaults to 1000.

        Raises:
            PageError: Raised if no element is found with given `selector`.
        """
        handle = await self._ensure_handle(selector)
        await handle.click(button, click_count, delay)
        await handle.dispose()

    async def focus(self, selector: str) -> None:
        """
        Focus on the first element that matches `selector`.

        Raises:
            PageError: Raised if no element is found with given `selector`.

        Args:
            selector (str): Selector to query element by.
        """
        handle = await self._ensure_handle(selector)
        await handle.focus()
        await handle.dispose()

    async def hover(self, selector: str) -> None:
        """
        Mouse hover over the first element that matches `selector`.

        Raises:
            PageError: Raised if no element is found with given `selector`.

        Args:
            selector (str): Selector to query element by.
        """
        handle = await self._ensure_handle(selector)
        await handle.hover()
        await handle.dispose()

    async def select(self, selector: str, values: list[str]) -> list[str]:
        """
        Select options on a "select" element.

        Args:
            selector (str): Selector to query element by.
            values (list[str]): List of string options to select by.

        Returns:
            list[str]: List of selected values.
        """
        if any(not isinstance(value, str) for value in values):
            raise TypeError("Select values must all be str.")
        handle = await self._ensure_handle(selector)
        context = await self._ensure_execution_context()
        result = context.evaluate(METHOD_SELECT_VALUES, handle, *values)
        await handle.dispose()
        return result

    async def tap(self, selector: str) -> None:
        """
        Tap the first element that matches `selector`.

        This method is a shortcut for running `Frame.query_selector` and then
        running `mokr.execution.ElementHandle.tap` on the resultant
        ElementHandle. In either case, an element will be scrolled into view
        if needed, and the center of it clicked with the ElementHandle's
        bound `Page.touchscreen`.

        Args:
            selector (str): Selector to query element by.

        Raises:
            PageError: Raised if no element is found with given `selector`.
        """
        handle = await self._ensure_handle(selector)
        await handle.tap()
        await handle.dispose()

    async def type_text(
        self,
        selector: str,
        text: str,
        delay: int | float = 0,
    ) -> None:
        """
        Focus on the first element that matches `selector` and type characters
        into it. Uses the newly created `ElementHandle`'s bound `Page.keyboard`.

        Note that modifier keys do not alter text case, meaning sending
        `mokr.input.Keyboard.press("shift")` and typing
        `Frame.type_text("input", "mokr")` will not type "MOKR" into the it.

        Raises:
            PageError: Raised if no element is found with given `selector`.

        Args:
            selector (str): Selector to query element by.
            text (str): Text to type.
            delay (int | float, optional): Time in milliseconds to wait between
                each character typed. Defaults to 0.
        """
        handle = await self._ensure_handle(selector)
        await handle.type_text(text, delay)
        await handle.dispose()

    def wait_for_timeout(
        self,
        timeout: int | float,
    ) -> Awaitable[None]:
        """
        Wait for the given amount of time. Same as `asyncio.sleep`.

        Args:
            timeout (int | float): Time in milliseconds to wait.

        Returns:
            Awaitable[None]: Task to be awaited.
        """
        return self._client._loop.create_task(asyncio.sleep(timeout / 1000))

    def wait_for_selector(
        self,
        selector: str,
        visible: bool = False,
        hidden: bool = False,
        timeout: int = 30000,
    ) -> WaitTask:
        """
        Wait for element that matches `selector` to appear in DOM.
        If element is in DOM already when called, return immediately.

        Args:
            selector (str): Selector to query element by.
            visible (bool, optional): Element must also not be hidden.
                Defaults to False.
            hidden (bool, optional): Element must also be hidden.
                Defaults to False.
            timeout (int, optional): Time in milliseconds to wait.
                Defaults to 30000.

        Raises:
            MokrTimeoutError: Raised if timeout exceeded before element found.
        Returns:
            Awaitable[JavascriptHandle]: None.
        """
        return self._wait_for_selector_or_xpath(
            selector,
            False,
            visible,
            hidden,
            timeout,
        )

    def wait_for_xpath(
        self,
        xpath: str,
        visible: bool = False,
        hidden: bool = False,
        timeout: int = 30000,
    ) -> WaitTask:
        """
        Wait for element that matches `xpath` expression to appear in DOM.
        If element is in DOM already when called, return immediately.

        Args:
            xpath (str): Expression to query element by.
            visible (bool, optional): Element must also not be hidden.
                Defaults to False.
            hidden (bool, optional): Element must also be hidden.
                Defaults to False.
            timeout (int, optional): Time in milliseconds to wait.
                Defaults to 30000.

        Raises:
            MokrTimeoutError: Raised if timeout exceeded before element found.
        Returns:
            Awaitable[JavascriptHandle]: None.
        """
        return self._wait_for_selector_or_xpath(
            xpath,
            True,
            visible,
            hidden,
            timeout,
        )

    def wait_for_function(
        self,
        page_function: str,
        polling: Literal['raf', 'mutation'] | int | float,
        timeout: int = 30000,
    ) -> Awaitable[JavascriptHandle]:
        """
        Wait until the given `page_function` returns a truthy value.

        Args:
            page_function (str): JavaScript function to run.
            polling (Literal["raf", "mutation"] | int | float, optional):
                Polling type; if set to "raf", executes continously in
                "requestAnimationFrame", else if set to "mutation" executes
                only on DOM mutations.
                Defaults to "raf".
            timeout (int, optional): Time in milliseconds to wait.
                Defaults to 30000.

        Returns:
            Awaitable[JavascriptHandle]: JavascriptHandle from JavaScript
                `page_function` successful result.
        """
        return WaitTask(
            self,
            page_function,
            'function',
            polling,
            timeout,
            self._client._loop,
        )

    async def title(self) -> str:
        """
        Get the document title.

        Returns:
            str: Document title.
        """
        return await self.evaluate('() => document.title')
