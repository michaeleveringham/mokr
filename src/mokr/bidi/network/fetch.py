from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Literal

from mokr.bidi.network.response import BidiResponse
from mokr.exceptions import UnsupportedOperationError

if TYPE_CHECKING:
    from mokr.bidi.browser.page import BidiPage


class BidiFetchDomain:
    """
    Run standards-compliant ``fetch`` in a BiDi page's JavaScript realm.

    The request uses the page's origin, CORS policy, and cookie jar. It is not
    a protocol-level HTTP client; use :class:`mokr.core.http.HttpDomain` for
    external requests that must bypass browser CORS rules.
    """

    _FETCH = """async (url, options) => {
        const response = await fetch(url, options);
        const bytes = new Uint8Array(await response.arrayBuffer());
        let binary = '';
        for (let offset = 0; offset < bytes.length; offset += 0x8000) {
            binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
        }
        return {
            url: response.url,
            status: response.status,
            statusText: response.statusText,
            headers: Array.from(response.headers.entries()),
            body: btoa(binary),
        };
    }"""

    def __init__(self, page: BidiPage) -> None:
        """Create a fetch helper bound to a page.

        Args:
            page: Parent BiDi page whose JavaScript realm performs requests.
        """
        self._page = page

    async def fetch(
        self,
        url: str | None = None,
        timeout: int | None = None,
        request: Any | None = None,
        body: str | None = None,
        browsing_topics: bool | None = None,
        cache: str | None = None,
        credentials: Literal["omit", "same-origin", "include"] | None = None,
        headers: dict[str, str] | None = None,
        method: str = "GET",
        mode: Literal["cors", "no-cors", "same-origin"] | None = None,
        priority: Literal["high", "low", "auto"] | None = None,
        redirect: Literal["follow", "error", "manual"] | None = None,
        referrer: str | None = None,
        referrer_policy: str | None = None,
    ) -> BidiResponse:
        """Issue a standards ``fetch`` request in the page's JavaScript realm.

        Requests use the page's origin, cookies, and CORS policy.

        Args:
            url: Destination URL. Required unless ``request`` is supplied.
            timeout: Request timeout in milliseconds.
            request: Existing request whose URL, method, and headers are used.
            body: Request body.
            browsing_topics: Unsupported Web Platform experimental option.
            cache: Fetch cache mode.
            credentials: Fetch credentials mode.
            headers: Request headers.
            method: HTTP method. Defaults to ``"GET"``.
            mode: Fetch CORS mode.
            priority: Unsupported fetch priority option.
            redirect: Fetch redirect mode.
            referrer: Request referrer.
            referrer_policy: Fetch referrer policy.

        Raises:
            UnsupportedOperationError: If an unsupported option is supplied.
            ValueError: If neither ``url`` nor ``request`` is supplied.
            TimeoutError: If the page-context fetch exceeds its timeout.

        Returns:
            A standard :class:`BidiResponse` with an in-memory body.
        """
        if browsing_topics is not None:
            raise UnsupportedOperationError(
                "FetchDomain.browsing_topics is not available through BiDi."
            )
        if priority is not None:
            raise UnsupportedOperationError(
                "FetchDomain.priority is not available through BiDi."
            )
        if request is not None:
            url = request.url
            method = request.method
            headers = request.headers
        if not url:
            raise ValueError("Must provide URL or request.")
        options = {
            key: value
            for key, value in {
                "body": body,
                "cache": cache,
                "credentials": credentials,
                "headers": headers,
                "method": method,
                "mode": mode,
                "redirect": redirect,
                "referrer": referrer,
                "referrerPolicy": referrer_policy,
            }.items()
            if value is not None
        }
        wait_seconds = (
            timeout
            if timeout is not None
            else self._page._default_navigation_timeout
        ) / 1000
        payload = await asyncio.wait_for(
            self._page.evaluate(self._FETCH, url, options), wait_seconds
        )
        return BidiResponse.from_fetch(payload)
