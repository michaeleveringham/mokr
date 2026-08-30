from __future__ import annotations

import base64
from typing import TYPE_CHECKING, Any, Callable
from urllib.parse import urlsplit

from pyee import EventEmitter

from mokr.bidi.input import BidiKeyboard, BidiMouse
from mokr.core.routes import RouteStack
from mokr.exceptions import UnsupportedOperationError

if TYPE_CHECKING:
    from mokr.bidi.browser.browser import BidiBrowser


class BidiPage(EventEmitter):
    """A browser tab backed by a WebDriver BiDi browsing context."""

    def __init__(
        self,
        browser: BidiBrowser,
        context_id: str,
        url: str = "about:blank",
    ) -> None:
        """Create a page facade for an existing browsing context.

        Args:
            browser: Parent BiDi browser.
            context_id: Top-level browsing-context identifier.
            url: Initially known page URL. Defaults to ``"about:blank"``.
        """
        super().__init__()
        self._browser = browser
        self._context_id = context_id
        self._url = url
        self._closed = False
        self._route_stack = RouteStack(lambda request: request.release())
        self._request_callbacks = self._route_stack.callbacks
        self._network_enabled = False
        self._interception_enabled = False
        self._request_intercept: str | None = None
        self._response_collector: str | None = None
        self._viewport: dict[str, Any] | None = None
        self._user_agent: str | None = None
        self._keyboard = BidiKeyboard(browser._session, context_id)
        self._mouse = BidiMouse(browser._session, context_id)

    @property
    def url(self) -> str:
        """Return the current top-level browsing-context URL."""
        return self._url

    @property
    def viewport(self) -> dict[str, Any] | None:
        """Return the configured viewport, if one has been applied."""
        return self._viewport

    @property
    def user_agent(self) -> str | None:
        """Return the page-specific user-agent override, if any."""
        return self._user_agent

    @property
    def is_closed(self) -> bool:
        """Whether this browsing context has been closed."""
        return self._closed

    @property
    def keyboard(self) -> BidiKeyboard:
        """Return the keyboard input controller for this page."""
        return self._keyboard

    @property
    def mouse(self) -> BidiMouse:
        """Return the mouse input controller for this page."""
        return self._mouse

    async def goto(
        self,
        url: str,
        timeout: int | None = None,
        wait_until: str = "load",
    ) -> dict[str, Any]:
        """Navigate this page and wait for the requested readiness state.

        Args:
            url: Destination URL.
            timeout: Navigation timeout in milliseconds. Base BiDi navigation
                currently delegates timeout handling to the browser.
            wait_until: ``"load"``, ``"domcontentloaded"``, or an immediate
                navigation when another value is supplied.

        Returns:
            Navigation metadata returned by WebDriver BiDi.
        """
        waits = {"load": "complete", "domcontentloaded": "interactive"}
        collect_response_data = bool(self.listeners("response"))
        if self._request_callbacks or collect_response_data:
            await self._enable_network(
                bool(self._request_callbacks), collect_response_data
            )
        result = await self._browser._session.navigate(
            self._context_id,
            url,
            waits.get(wait_until, "none"),
        )
        self._url = result.get("url", url)
        return result

    def on(self, event: str, listener: Callable):
        """Register an event listener or request-interception callback.

        Request callbacks form a newest-first route stack. Other events use
        the normal :class:`pyee.EventEmitter` behavior.

        Args:
            event: Event name.
            listener: Callback invoked for the event.

        Returns:
            This page, matching ``EventEmitter.on`` chaining behavior.
        """
        if event == "request":
            self._route_stack.add(listener)
            return self
        return super().on(event, listener)

    async def _enable_network(
        self,
        intercept: bool = True,
        collect_response_data: bool = False,
    ) -> None:
        if (
            self._network_enabled
            and (not intercept or self._interception_enabled)
            and (
                not collect_response_data
                or self._response_collector is not None
            )
        ):
            return
        await self._browser._enable_network_for_page(
            self, intercept, collect_response_data
        )
        self._network_enabled = True
        self._interception_enabled = self._interception_enabled or intercept

    async def set_request_interception_enabled(self, choice: bool) -> None:
        """Enable or disable blocking request interception for this page.

        Args:
            choice: Whether requests should pause for route callbacks.
        """
        if choice:
            await self._enable_network(True)
            return
        if self._request_intercept is not None:
            await self._browser._session.remove_intercept(
                self._request_intercept
            )
            self._request_intercept = None
        self._interception_enabled = False

    async def bring_to_front(self) -> None:
        """Activate this browsing context in the browser window."""
        await self._browser._session.activate_page(self._context_id)

    async def reload(
        self, timeout: int | None = None, wait_until: str = "load"
    ) -> dict[str, Any]:
        """Reload this page and wait for the requested readiness state.

        Args:
            timeout: Reload timeout in milliseconds. Base BiDi reloads
                currently delegate timeout handling to the browser.
            wait_until: ``"load"``, ``"domcontentloaded"``, or an immediate
                reload when another value is supplied.

        Returns:
            Navigation metadata returned by WebDriver BiDi.
        """
        waits = {"load": "complete", "domcontentloaded": "interactive"}
        return await self._browser._session.reload_page(
            self._context_id, waits.get(wait_until, "none")
        )

    async def refresh(
        self, timeout: int | None = None, wait_until: str = "load"
    ) -> dict[str, Any]:
        """Alias for :meth:`reload`."""
        return await self.reload(timeout, wait_until)

    async def screenshot(
        self,
        path: str | None = None,
        type: str = "png",
        quality: int | None = None,
        full_page: bool = False,
        encoding: str | None = None,
        **kwargs: Any,
    ) -> bytes | str:
        """Capture a viewport or full-document screenshot.

        Args:
            path: Optional destination file path.
            type: Image format, ``"png"`` or ``"jpeg"``.
            quality: JPEG quality from 0 to 100.
            full_page: Whether to capture the complete document.
            encoding: Return base64 text when set to ``"base64"``.
            **kwargs: Reserved screenshot options for backend extensions.

        Returns:
            Image bytes, or base64 text when requested.
        """
        options: dict[str, Any] = {
            "origin": "document" if full_page else "viewport"
        }
        if type == "jpeg":
            options["format"] = {"type": "image/jpeg"}
            if quality is not None:
                options["format"]["quality"] = quality / 100
        data = await self._browser._session.capture_screenshot(
            self._context_id, options
        )
        if encoding == "base64":
            return data
        result = base64.b64decode(data)
        if path:
            from pathlib import Path

            Path(path).write_bytes(result)
        return result

    async def set_viewport(self, viewport: dict[str, Any]) -> None:
        """Set this page's CSS viewport and optional device pixel ratio.

        Args:
            viewport: Mapping containing ``width`` and ``height``, optionally
                with ``deviceScaleFactor``.
        """
        params: dict[str, Any] = {
            "viewport": {
                "width": viewport["width"],
                "height": viewport["height"],
            }
        }
        if "deviceScaleFactor" in viewport:
            params["devicePixelRatio"] = viewport["deviceScaleFactor"]
        await self._browser._session.set_viewport(self._context_id, params)
        self._viewport = viewport.copy()

    async def cookies(self) -> list[dict[str, Any]]:
        """Return cookies visible to this browsing context."""
        cookies = await self._browser._session.get_cookies(self._context_id)
        return [self._cookie_from_bidi(cookie) for cookie in cookies]

    async def delete_cookies(self, cookies: list[dict[str, Any]]) -> None:
        """Delete cookies matching supplied name, domain, and path filters.

        Args:
            cookies: Cookie filters; every entry must contain a name.

        Raises:
            ValueError: If a cookie filter has no name.
        """
        for cookie in cookies:
            cookie_filter = {
                key: value
                for key, value in cookie.items()
                if key in {"name", "domain", "path"}
            }
            if not cookie_filter.get("name"):
                raise ValueError("A cookie name is required for deletion.")
            await self._browser._session.delete_cookies(
                cookie_filter, self._context_id
            )

    async def set_cookies(self, cookies: list[dict[str, Any]]) -> None:
        """Set cookies in this browsing context's storage partition.

        Args:
            cookies: Cookies containing name, value, and either URL or domain.

        Raises:
            ValueError: If a cookie URL is invalid or required fields are
                missing.
        """
        for supplied_cookie in cookies:
            cookie = supplied_cookie.copy()
            url = cookie.pop("url", None)
            if url:
                parsed = urlsplit(url)
                if not parsed.hostname:
                    raise ValueError(f"Invalid cookie URL: {url}")
                cookie.setdefault("domain", parsed.hostname)
                cookie.setdefault("path", "/")
            if not cookie.get("domain"):
                raise ValueError("Cookies require either a domain or a URL.")
            if "name" not in cookie or "value" not in cookie:
                raise ValueError("Cookies require both name and value.")
            if isinstance(cookie["value"], str):
                cookie["value"] = {
                    "type": "string",
                    "value": cookie["value"],
                }
            await self._browser._session.set_cookie(cookie, self._context_id)

    async def set_user_agent(
        self, user_agent: str, user_agent_metadata: str | None = None
    ) -> None:
        """Override the user agent for this page.

        Args:
            user_agent: User-agent string to apply.
            user_agent_metadata: Unsupported client-hint metadata.

        Raises:
            UnsupportedOperationError: If client-hint metadata is supplied.
        """
        if user_agent_metadata is not None:
            raise UnsupportedOperationError(
                "BiDi user-agent client hints are not supported yet."
            )
        await self._browser._session.set_user_agent(
            self._context_id, user_agent
        )
        self._user_agent = user_agent

    async def evaluate_on_new_document(
        self, page_function: str, *args: str
    ) -> str:
        """Install a script that runs in future documents for this page.

        Args:
            page_function: JavaScript function declaration.
            *args: String arguments interpolated into the function call.

        Returns:
            BiDi preload-script identifier.
        """
        if args:
            page_function = f"({page_function})({', '.join(map(repr, args))})"
        return await self._browser._session.add_preload_script(
            page_function, [self._context_id]
        )

    async def set_request_cache(self, choice: bool = True) -> None:
        """Enable or disable normal cache use for this page's requests.

        Args:
            choice: ``True`` to use normal caching; ``False`` to bypass it.
        """
        await self._browser._session.set_cache_behavior(
            self._context_id, choice
        )

    async def set_extra_http_headers(self, headers: dict[str, str]) -> None:
        """Set extra HTTP headers sent with this page's requests.

        Args:
            headers: Header names and string values.

        Raises:
            ValueError: If any header value is not a string.
        """
        if not all(isinstance(value, str) for value in headers.values()):
            raise ValueError("All extra HTTP header values must be strings.")
        await self._browser._session.set_extra_headers(
            self._context_id, headers
        )

    async def evaluate(
        self, page_function: str, *args: Any, force_expr: bool = False
    ) -> Any:
        """Evaluate JavaScript, passing JSON-like arguments when supplied.

        Args:
            page_function: JavaScript expression or function declaration.
            *args: JSON-like arguments passed to a function declaration.
            force_expr: Retained for the shared page signature; BiDi
                determines expression versus function from whether arguments
                are supplied.

        Returns:
            The deserialized JavaScript result.
        """
        if not args:
            return await self._browser._session.evaluate(
                self._context_id,
                page_function,
            )
        value = await self._browser._session.call_function(
            self._context_id,
            page_function,
            [
                self._browser._session.serialize_remote_value(argument)
                for argument in args
            ],
        )
        return self._browser._session._deserialize_remote_value(value)

    async def content(self) -> str:
        """Return the current document's serialized HTML."""
        return await self.evaluate("document.documentElement.outerHTML")

    async def set_content(self, html: str) -> None:
        """Replace the current document's HTML.

        Args:
            html: New markup for ``document.documentElement``.
        """
        await self._browser._session.set_content(self._context_id, html)

    async def title(self) -> str:
        """Return the current document title."""
        return await self.evaluate("document.title")

    async def close(self, run_before_unload: bool = False) -> None:
        """Close this browsing context.

        Args:
            run_before_unload: Retained for shared API compatibility; WebDriver
                BiDi currently closes the context directly.
        """
        await self._browser._session.close_page(self._context_id)
        self._closed = True
        self._browser._pages.pop(self._context_id, None)

    @staticmethod
    def _cookie_from_bidi(cookie: dict[str, Any]) -> dict[str, Any]:
        result = cookie.copy()
        value = result.get("value")
        if isinstance(value, dict):
            result["value"] = value.get("value", "")
        return result
