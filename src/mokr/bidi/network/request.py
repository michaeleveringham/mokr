from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from mokr.bidi.connection import BidiSession
from mokr.bidi.network._utils import headers_to_dict
from mokr.core.routes import RouteStack


class BidiRequest:
    """A blocking ``network.beforeRequestSent`` interception request."""

    def __init__(
        self,
        session: BidiSession,
        page,
        event: dict[str, Any],
    ) -> None:
        """Create an intercepted request from a BiDi network event.

        Args:
            session: Remote BiDi session used to resolve the request.
            page: Page that initiated the request.
            event: ``network.beforeRequestSent`` event payload.
        """
        self._session = session
        self._page = page
        self._request_id = event["request"]["request"]
        self._payload = event["request"]
        self._handled = False

    @property
    def url(self) -> str:
        """Return the intercepted request URL."""
        return self._payload["url"]

    @property
    def method(self) -> str:
        """Return the intercepted HTTP method."""
        return self._payload["method"]

    @property
    def headers(self) -> dict[str, str]:
        """Return request headers keyed case-insensitively in lowercase."""
        return headers_to_dict(self._payload.get("headers", []))

    @property
    def is_handled(self) -> bool:
        """Whether this interception has already been resolved."""
        return self._handled

    async def release(self) -> None:
        """Continue the intercepted request without modifications."""
        self._ensure_unhandled()
        self._handled = True
        await self._session.continue_request(self._request_id)

    async def abort(self) -> None:
        """Fail the intercepted request."""
        self._ensure_unhandled()
        self._handled = True
        await self._session.fail_request(self._request_id)

    async def fulfill(
        self,
        body: str | bytes = b"",
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Fulfill the intercepted request with a synthetic response.

        Args:
            body: Response body as text or bytes.
            status: HTTP response status code. Defaults to ``200``.
            headers: Response headers.
        """
        self._ensure_unhandled()
        self._handled = True
        if isinstance(body, str):
            body = body.encode()
        await self._session.provide_response(
            self._request_id,
            status,
            headers or {},
            body,
        )

    def _ensure_unhandled(self) -> None:
        if self._handled:
            raise RuntimeError("Request has already been handled.")


async def run_interception_callbacks(
    request: BidiRequest,
    callbacks: RouteStack | list[Callable],
) -> None:
    """Run mokr's newest-first request route stack, then continue by default."""
    try:
        if isinstance(callbacks, RouteStack):
            await callbacks.dispatch(request)
            return
        result: Any = request
        for callback in reversed(callbacks):
            if result is None or request.is_handled:
                break
            result = callback(result)
            if inspect.isawaitable(result):
                result = await result
        if not request.is_handled:
            await request.release()
    except Exception:
        # Leaving a paused request/response unresolved deadlocks the browser.
        if not request.is_handled:
            try:
                await request.abort()
            except Exception:
                pass
        raise
