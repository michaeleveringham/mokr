from __future__ import annotations

import asyncio
import base64
import inspect
import json
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from mokr.bidi.browser import BidiPage
from mokr.bidi.execution import BidiElementHandle
from mokr.bidi.frame import BidiFrame
from mokr.bidi.input import BidiTouchscreen
from mokr.bidi.network import BidiFetchDomain, BidiResponse
from mokr.core.http import HttpDomain
from mokr.exceptions import MokrTimeoutError, PageError

if TYPE_CHECKING:
    from mokr.bidi.firefox.browser import FirefoxBrowser


class FirefoxPage(BidiPage):
    """Firefox-only page adapter built entirely on the native BiDi endpoint."""

    def __init__(
        self, browser: FirefoxBrowser, context_id: str, url: str = "about:blank"
    ) -> None:
        """Create a Firefox page for an existing BiDi browsing context.

        Args:
            browser: Parent Firefox browser.
            context_id: Top-level browsing-context identifier.
            url: Initially known page URL. Defaults to ``"about:blank"``.
        """
        super().__init__(browser, context_id, url)
        self._main_frame = BidiFrame(self, context_id, url)
        self._frames_by_context = {context_id: self._main_frame}
        self._touchscreen = BidiTouchscreen(browser._session, context_id)
        self._client = browser._session.connection
        self._ignore_https_errors = browser._ignore_https_errors
        self._default_navigation_timeout = 30000
        self._proxy_credentials = browser._proxy_credentials
        self._http_domain: HttpDomain | None = None
        self._fetch_domain: BidiFetchDomain | None = None
        self._page_bindings: dict[str, dict[str, Any]] = {}
        self._script_message_listener_registered = False

    @property
    def main_frame(self) -> BidiFrame:
        """Return this page's top-level frame."""
        return self._main_frame

    @property
    def frames(self) -> list[BidiFrame]:
        """Return the top-level frame and tracked child frames."""
        return list(self._frames_by_context.values())

    @property
    def touchscreen(self) -> BidiTouchscreen:
        """Return the touch input controller for this page."""
        return self._touchscreen

    @property
    def http_domain(self) -> HttpDomain:
        """Return an HTTPX client whose cookies synchronize through BiDi storage."""
        if self._http_domain is None:
            self.make_http_domain()
        return self._http_domain

    @property
    def fetch_domain(self) -> BidiFetchDomain:
        """Return a standards ``fetch`` client executed in this page's realm."""
        if self._fetch_domain is None:
            self._fetch_domain = BidiFetchDomain(self)
        return self._fetch_domain

    def make_http_domain(
        self,
        sync_cookies: Literal["both", "http", "page", "none"] = "both",
        **httpx_client_kwargs: Any,
    ) -> None:
        """Configure the cookie-synchronized HTTP client for this page.

        Args:
            sync_cookies: Direction in which cookies synchronize between the
                page and HTTP client.
            **httpx_client_kwargs: Options forwarded to ``httpx.AsyncClient``.
        """
        self._http_domain = HttpDomain(
            self, sync_cookies, **httpx_client_kwargs
        )

    async def fetch(self, *args: Any, **kwargs: Any) -> BidiResponse:
        """Issue a CORS- and cookie-aware JavaScript ``fetch`` request.

        Args:
            *args: Positional arguments forwarded to :class:`BidiFetchDomain`.
            **kwargs: Keyword arguments forwarded to
                :class:`BidiFetchDomain`.

        Returns:
            A standard :class:`BidiResponse` with an in-memory body.
        """
        return await self.fetch_domain.fetch(*args, **kwargs)

    async def goto(
        self, url: str, timeout: int | None = None, wait_until: str = "load"
    ) -> BidiResponse:
        """Navigate and return the final document response.

        Args:
            url: Destination URL.
            timeout: Maximum wait in milliseconds. Defaults to the page's
                navigation timeout.
            wait_until: ``"load"``, ``"domcontentloaded"``, or an immediate
                navigation when another value is supplied.

        Raises:
            MokrTimeoutError: If the document response is not observed before
                the timeout.

        Returns:
            Final document response associated with the navigation.
        """
        responses: list[BidiResponse] = []
        received: asyncio.Queue[None] = asyncio.Queue()

        def capture(response: BidiResponse) -> None:
            responses.append(response)
            received.put_nowait(None)

        self.on("response", capture)
        try:
            navigation = await super().goto(url, timeout, wait_until)
            navigation_id, target_url = navigation.get(
                "navigation"
            ), navigation.get("url", url)

            def document_response() -> BidiResponse | None:
                for response in reversed(responses):
                    if (
                        navigation_id is not None
                        and response.navigation_id == navigation_id
                    ):
                        return response
                return next(
                    (
                        response
                        for response in reversed(responses)
                        if response.url == target_url
                    ),
                    None,
                )

            deadline = (
                asyncio.get_running_loop().time()
                + (
                    timeout
                    if timeout is not None
                    else self._default_navigation_timeout
                )
                / 1000
            )
            response = document_response()
            while response is None:
                try:
                    await asyncio.wait_for(
                        received.get(),
                        deadline - asyncio.get_running_loop().time(),
                    )
                except asyncio.TimeoutError as error:
                    raise MokrTimeoutError(
                        "Timed out waiting for the navigation response."
                    ) from error
                response = document_response()
            return response
        finally:
            self.remove_listener("response", capture)

    async def expose_function(self, name: str, callback: Callable) -> None:
        """Expose a JavaScript function backed by a Python callback.

        Args:
            name: Function name installed on ``globalThis``.
            callback: Callable invoked with JSON-like JavaScript arguments.

        Raises:
            PageError: If the name is already registered on this page.
        """
        if name in self._page_bindings:
            raise PageError(f"Function '{name}' has already been exposed.")
        channel, state_key = (
            f"mokr-{uuid.uuid4().hex}",
            f"__mokr_binding_{uuid.uuid4().hex}",
        )
        declaration = self._binding_install_script(name, state_key)
        argument = {
            "type": "channel",
            "value": {"channel": channel, "ownership": "root"},
        }
        script_id = await self._browser._session.add_preload_script(
            declaration, [self._context_id], [argument]
        )
        binding = {
            "callback": callback,
            "channel": channel,
            "script_id": script_id,
            "state_key": state_key,
        }
        self._page_bindings[name] = binding
        try:
            if not self._script_message_listener_registered:
                await self._browser._session.subscribe(
                    ["script.message"], [self._context_id]
                )
                self._browser._session.connection.on(
                    "script.message", self._on_script_message
                )
                self._script_message_listener_registered = True
            await self._browser._session.call_function(
                self._context_id, declaration, [argument]
            )
        except Exception:
            self._page_bindings.pop(name, None)
            try:
                await self._browser._session.remove_preload_script(script_id)
            except Exception:
                pass
            raise

    @staticmethod
    def _binding_install_script(name: str, state_key: str) -> str:
        return f"""(channel) => {{ const bindings = globalThis[{json.dumps(state_key)}] ||= new Map(); globalThis[{json.dumps(name)}] = (...args) => new Promise((resolve, reject) => {{ const id = `${{Date.now()}}-${{Math.random()}}`; bindings.set(id, {{resolve, reject}}); channel({{id, args}}); }}); }}"""

    def _on_script_message(self, event: dict[str, Any]) -> None:
        binding = next(
            (
                item
                for item in self._page_bindings.values()
                if item["channel"] == event.get("channel")
            ),
            None,
        )
        if binding is not None:
            task = asyncio.get_running_loop().create_task(
                self._resolve_binding_call(binding, event)
            )
            task.add_done_callback(self._log_binding_task)

    async def _resolve_binding_call(
        self, binding: dict[str, Any], event: dict[str, Any]
    ) -> None:
        data = self._browser._session._deserialize_remote_value(
            event.get("data")
        )
        if not isinstance(data, dict) or not isinstance(data.get("id"), str):
            return
        try:
            result = binding["callback"](*data.get("args", []))
            result = await result if inspect.isawaitable(result) else result
            value, success = (
                self._browser._session.serialize_remote_value(result),
                True,
            )
        except Exception as error:
            value, success = (
                self._browser._session.serialize_remote_value(str(error)),
                False,
            )
        await self._browser._session.call_function(
            self._context_id,
            f"""(id, success, value) => {{ const pending = globalThis[{json.dumps(binding['state_key'])}]?.get(id); if (!pending) return; globalThis[{json.dumps(binding['state_key'])}].delete(id); if (success) pending.resolve(value); else pending.reject(new Error(value)); }}""",
            [
                self._browser._session.serialize_remote_value(data["id"]),
                self._browser._session.serialize_remote_value(success),
                value,
            ],
            target={"realm": event["source"]["realm"]},
        )

    @staticmethod
    def _log_binding_task(task: asyncio.Task) -> None:
        try:
            task.result()
        except (ConnectionError, RuntimeError):
            pass

    async def query_selector(self, selector: str) -> BidiElementHandle | None:
        """Return the first element matching a CSS selector, if any.

        Args:
            selector: CSS selector to query in the main frame.
        """
        return await self._main_frame.query_selector(selector)

    async def query_selector_all(
        self, selector: str
    ) -> list[BidiElementHandle]:
        """Return all elements matching a CSS selector.

        Args:
            selector: CSS selector to query in the main frame.
        """
        return await self._main_frame.query_selector_all(selector)

    async def xpath(self, expression: str) -> list[BidiElementHandle]:
        """Return all elements matching an XPath expression.

        Args:
            expression: XPath expression to query in the main frame.
        """
        return await self._main_frame.xpath(expression)

    async def _element(self, selector: str) -> BidiElementHandle:
        element = await self.query_selector(selector)
        if element is None:
            raise RuntimeError(f"No element matches selector: {selector}")
        return element

    async def click(self, selector: str) -> None:
        """Click the first element matching a CSS selector.

        Args:
            selector: CSS selector to query.

        Raises:
            RuntimeError: If no element matches.
        """
        await (await self._element(selector)).click()

    async def hover(self, selector: str) -> None:
        """Hover over the first element matching a CSS selector.

        Args:
            selector: CSS selector to query.

        Raises:
            RuntimeError: If no element matches.
        """
        await (await self._element(selector)).hover()

    async def focus(self, selector: str) -> None:
        """Focus the first element matching a CSS selector.

        Args:
            selector: CSS selector to query.

        Raises:
            RuntimeError: If no element matches.
        """
        await (await self._element(selector)).focus()

    async def type_text(
        self, selector: str, text: str, delay: int | float = 0
    ) -> None:
        """Type text into the first element matching a CSS selector.

        Args:
            selector: CSS selector to query.
            text: Text to type.
            delay: Time in milliseconds between characters. Defaults to ``0``.

        Raises:
            RuntimeError: If no element matches.
        """
        await (await self._element(selector)).type_text(text, int(delay))

    async def tap(self, selector: str) -> None:
        """Tap the first element matching a CSS selector.

        Args:
            selector: CSS selector to query.

        Raises:
            RuntimeError: If no element matches.
        """
        await (await self._element(selector)).tap()

    async def select(self, selector: str, values: list[str]) -> list[str]:
        """Select values in the first matching ``select`` element.

        Args:
            selector: CSS selector to query.
            values: Option values to select.

        Raises:
            RuntimeError: If no element matches.

        Returns:
            Values selected after the DOM input and change events run.
        """
        return await (await self._element(selector)).select(values)

    async def set_credentials(self, username: str, password: str = "") -> None:
        """Configure credentials for subsequent authentication challenges.

        Args:
            username: Authentication username.
            password: Authentication password. Defaults to ``""``.
        """
        await self._browser.set_credentials(username, password)

    def _register_frame(self, context: dict[str, Any]) -> BidiFrame:
        frame = self._frames_by_context.get(context["context"])
        if frame is None:
            frame = BidiFrame(
                self,
                context["context"],
                context.get("url", "about:blank"),
                context.get("parent"),
            )
            self._frames_by_context[context["context"]] = frame
        return frame

    def _remove_frame(self, context_id: str) -> None:
        if context_id != self._context_id:
            self._frames_by_context.pop(context_id, None)

    async def reload(
        self, timeout: int | None = None, wait_until: str = "load"
    ) -> dict[str, Any]:
        """Reload this page and wait for the requested readiness state."""
        return await self._browser._session.reload_page(
            self._context_id,
            {"load": "complete", "domcontentloaded": "interactive"}.get(
                wait_until, "none"
            ),
        )

    async def go_back(self) -> None:
        """Traverse one entry backward in this page's history."""
        await self._traverse_history(-1)

    async def go_forward(self) -> None:
        """Traverse one entry forward in this page's history."""
        await self._traverse_history(1)

    async def _traverse_history(self, delta: int) -> None:
        completed = asyncio.get_running_loop().create_future()

        def on_navigation(event: dict[str, Any]) -> None:
            if (
                event.get("context") == self._context_id
                and not completed.done()
            ):
                completed.set_result(None)

        connection = self._browser._session.connection
        connection.on("browsingContext.load", on_navigation)
        connection.on("browsingContext.historyUpdated", on_navigation)
        try:
            await self._browser._session.traverse_history(
                self._context_id, delta
            )
            await completed
        finally:
            connection.remove_listener("browsingContext.load", on_navigation)
            connection.remove_listener(
                "browsingContext.historyUpdated", on_navigation
            )

    async def pdf(
        self,
        file_path: str | None = None,
        landscape: bool = False,
        print_background: bool = False,
        **kwargs: Any,
    ) -> bytes:
        """Render this page as PDF bytes and optionally write a file.

        Args:
            file_path: Optional destination path.
            landscape: Whether to use landscape orientation.
            print_background: Whether to render document backgrounds.
            **kwargs: Reserved PDF options for API compatibility.

        Returns:
            PDF document bytes.
        """
        result = base64.b64decode(
            await self._browser._session.print_page(
                self._context_id,
                {
                    "orientation": "landscape" if landscape else "portrait",
                    "background": print_background,
                },
            )
        )
        if file_path:
            Path(file_path).write_bytes(result)
        return result

    async def screenshot(
        self,
        path: str | None = None,
        type: str = "png",
        quality: int | None = None,
        full_page: bool = False,
        encoding: str | None = None,
        clip: dict[str, float] | None = None,
        **kwargs: Any,
    ) -> bytes | str:
        """Capture a viewport, document, or clipped screenshot.

        Args:
            path: Optional destination file path.
            type: Image format, ``"png"`` or ``"jpeg"``.
            quality: JPEG quality from 0 to 100.
            full_page: Whether to capture the complete document.
            encoding: Return base64 text when set to ``"base64"``.
            clip: Optional viewport rectangle.
            **kwargs: Reserved screenshot options for API compatibility.

        Returns:
            Image bytes, or base64 text when requested.
        """
        options: dict[str, Any] = {
            "origin": "document" if full_page else "viewport"
        }
        if type == "jpeg":
            options["format"] = {"type": "image/jpeg"}
            options["format"].update(
                {"quality": quality / 100} if quality is not None else {}
            )
        if clip:
            options["clip"] = {"type": "box", **clip}
        data = await self._browser._session.capture_screenshot(
            self._context_id, options
        )
        if encoding == "base64":
            return data
        result = base64.b64decode(data)
        if path:
            Path(path).write_bytes(result)
        return result

    async def close(self, run_before_unload: bool = False) -> None:
        """Remove page-scoped bindings, then close this browsing context."""
        if self._script_message_listener_registered:
            self._browser._session.connection.remove_listener(
                "script.message", self._on_script_message
            )
        for binding in self._page_bindings.values():
            try:
                await self._browser._session.remove_preload_script(
                    binding["script_id"]
                )
            except Exception:
                pass
        self._page_bindings.clear()
        await super().close(run_before_unload)
