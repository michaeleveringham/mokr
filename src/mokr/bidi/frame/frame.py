from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mokr.bidi.execution.handle.element import BidiElementHandle

if TYPE_CHECKING:
    from mokr.bidi.firefox.page import FirefoxPage


class BidiFrame:
    """A WebDriver BiDi browsing context exposed with frame-like helpers."""

    def __init__(
        self,
        page: FirefoxPage,
        context_id: str,
        url: str = "about:blank",
        parent_id: str | None = None,
    ) -> None:
        """Create a frame facade for a BiDi browsing context.

        Args:
            page: Page that owns this frame.
            context_id: Browsing-context identifier for the frame.
            url: Initially known frame URL. Defaults to ``"about:blank"``.
            parent_id: Parent browsing-context identifier, if any.
        """
        self._page, self._context_id, self._url, self._parent_id = (
            page,
            context_id,
            url,
            parent_id,
        )

    @property
    def url(self) -> str:
        """Return this frame's URL."""
        return self._url

    async def query_selector(self, selector: str) -> BidiElementHandle | None:
        """Return the first element matching a CSS selector, if any.

        Args:
            selector: CSS selector to query.
        """
        handles = await self.query_selector_all(selector)
        return handles[0] if handles else None

    async def query_selector_all(
        self, selector: str
    ) -> list[BidiElementHandle]:
        """Return all elements matching a CSS selector.

        Args:
            selector: CSS selector to query.
        """
        nodes = await self._page._browser._session.locate_nodes(
            self._context_id, {"type": "css", "value": selector}
        )
        return [BidiElementHandle(self, node) for node in nodes]

    async def xpath(self, expression: str) -> list[BidiElementHandle]:
        """Return all elements matching an XPath expression.

        Args:
            expression: XPath expression to query.
        """
        nodes = await self._page._browser._session.locate_nodes(
            self._context_id, {"type": "xpath", "value": expression}
        )
        return [BidiElementHandle(self, node) for node in nodes]

    async def evaluate(self, page_function: str, *args: Any) -> Any:
        """Evaluate JavaScript in this frame with JSON-like arguments.

        Args:
            page_function: JavaScript expression or function source.
            *args: JSON-like arguments passed to a function.

        Returns:
            The deserialized JavaScript result.
        """
        if not args:
            return await self._page._browser._session.evaluate(
                self._context_id, page_function
            )
        value = await self._page._browser._session.call_function(
            self._context_id,
            page_function,
            [
                self._page._browser._session.serialize_remote_value(argument)
                for argument in args
            ],
        )
        return self._page._browser._session._deserialize_remote_value(value)
