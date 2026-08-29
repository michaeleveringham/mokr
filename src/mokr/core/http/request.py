from __future__ import annotations

import copy
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from mokr.core.http.response import HttpResponse


class HttpRequest:
    """Protocol-neutral request produced by :class:`HttpDomain`."""

    def __init__(self, request: httpx.Request) -> None:
        self._httpx_request = request
        self._response: HttpResponse | None = None
        self._redirect_chain: list[HttpRequest] = []

    def __repr__(self) -> str:
        return f"<HttpRequest ({self.method} to {self.url}) at {id(self)}>"

    @property
    def url(self) -> str:
        """Return the requested URL."""
        return str(self._httpx_request.url)

    @property
    def resource_type(self) -> str:
        """Return the non-browser resource classification."""
        return "Other"

    @property
    def method(self) -> str:
        """Return the HTTP method."""
        return self._httpx_request.method

    @property
    def post_data(self) -> str | None:
        """Return the decoded request body, if present."""
        data = self._httpx_request.content
        return data.decode() if data else None

    @property
    def headers(self) -> dict[str, str]:
        """Return request headers with lowercase keys."""
        return {
            name.lower(): value
            for name, value in self._httpx_request.headers.items()
        }

    @property
    def response(self) -> HttpResponse | None:
        """Return the response paired with this request."""
        return self._response

    @property
    def frame(self) -> None:
        """HTTP-domain requests are not associated with a browser frame."""
        return None

    @property
    def redirect_chain(self) -> list[HttpRequest]:
        """Return a copy of the complete redirect request chain."""
        return copy.copy(self._redirect_chain)

    @property
    def httpx_request(self) -> httpx.Request:
        """Return the underlying HTTPX request."""
        return self._httpx_request

    @property
    def is_handled(self) -> bool:
        """HTTP-domain requests are already complete and cannot be intercepted."""
        return True

    def is_navigation_request(self) -> bool:
        """Return ``False`` because this request did not navigate a browser."""
        return False

    def failure_text(self) -> None:
        """Return no browser-network failure text."""
        return None

    @staticmethod
    def _interception_error() -> ValueError:
        return ValueError(
            "Cannot run interception methods on HttpDomain-based requests."
        )

    async def release(self, **kwargs) -> None:
        """Reject interception because this HTTP request is already complete."""
        raise self._interception_error()

    async def fulfill(self, **kwargs) -> None:
        """Reject interception because this HTTP request is already complete."""
        raise self._interception_error()

    async def abort(self, **kwargs) -> None:
        """Reject interception because this HTTP request is already complete."""
        raise self._interception_error()
