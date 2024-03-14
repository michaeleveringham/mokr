from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlparse

import httpx

from mokr.constants import HTTP_METHODS
from mokr.network.request import Request
from mokr.network.response import Response

if TYPE_CHECKING:
    from mokr.browser.page import Page


class HttpDomain():
    def __init__(
        self,
        page: Page,
        sync_cookies: Literal["both", "http", "page", "none"] = "both",
        **httpx_client_kwargs,
    ) -> None:
        """
        Client to handle sending requests outside of the browser, while syncing
        state between itself and the parent `mokr.browser.Page`.

        This client uses `httpx` so requests can be made with HTTP2.

        Args:
            page (Page): Parent `mokr.browser.Page` that this will sync with.
            sync_cookies (Literal["both", "http", "page", "none"], optional):
                Whether to sync cookies between this client and the parent
                `mokr.browser.Page` before/after each request and response.
                Defaults to "both".
        """
        self._page = page
        self._cookie_sync_directive = sync_cookies
        self._build_proxy()
        kwargs = dict(
            http2=True,
            proxies=self._proxies,
            verify=not self._page._ignore_https_errors,
            timeout=self._page._default_navigation_timeout,
            follow_redirects=True,
        )
        if httpx_client_kwargs:
            kwargs.update(**httpx_client_kwargs)
        headers = {"User-Agent": self._page.user_agent}
        if "headers" in kwargs:
            kwargs["headers"].update(headers)
        else:
            kwargs["headers"] = headers
        # Cannot use the AsyncClient due to SOCKS support issue:
        # https://github.com/encode/httpx/discussions/2305
        # For now, throwing methods into threads via asyncio.
        self._client = httpx.Client(**kwargs)

    def _build_proxy(self) -> None:
        creds = self._page._proxy_credentials.copy()
        if not creds:
            self._proxies = None
            return
        if not creds.get("username"):
            proxy = creds["proxy"]
        else:
            proxy_parts = urlparse(creds["proxy"])
            scheme = proxy_parts.scheme
            host = proxy_parts.hostname
            port = proxy_parts.port
            username = creds.get("username", "")
            auth_block = ""
            if username:
                auth_block = f'{username}:{creds.get("password", "")}'
            proxy = f"{scheme}://{auth_block}@{host}:{port}"
        self._proxies = {"http://": proxy, "https://": proxy}
        if proxy.startswith("socks"):
            self._proxies["socks5://"] = proxy

    async def _sync_cookies_from_browser(self) -> None:
        browser_cookies = await self._page.cookies()
        for cookie in browser_cookies:
            self._client.cookies.set(
                cookie["name"],
                cookie["value"],
                cookie.get("domain", ""),
                cookie.get("path", "/"),
            )

    async def _sync_cookies_to_browser(self) -> None:
        cookies_list = []
        for data in self._client.cookies.jar._cookies.values():
            for cookie_map in data.values():
                for cookie in cookie_map.values():
                    cookie_dump = {
                        "name": cookie.name,
                        "value": cookie.value,
                        "domain": cookie.domain,
                        "path": cookie.path,
                        "expires": cookie.expires,
                        "secure": cookie.secure,
                    }
                    cookie_dump = {k: v for k, v in cookie_dump.items() if v}
                    if cookie_dump:
                        cookies_list.append(cookie_dump)
        if cookies_list:
            await self._page.set_cookies(cookies_list)

    async def _sync_cookies(self):
        if not self._cookie_sync_directive:
            return
        if self._cookie_sync_directive in ("both", "http"):
            await self._sync_cookies_from_browser()
        if self._cookie_sync_directive in ("both", "page"):
            await self._sync_cookies_to_browser()

    async def _http_to_mokr(self, response: httpx.Response) -> Request:
        request = response.request
        data = await asyncio.to_thread(request.read)
        payload = {
            "method": request.method,
            "postData": data.decode(),
            "headers": dict(request.headers),
        }
        mokr_request = Request(
            self._page,
            self._page._client,
            "httpxrequest",
            None,
            False,
            False,
            str(request.url),
            "Other",
            payload,
            None,
            [],
            [],
            httpx_request=request,
        )
        mokr_response = Response(
            self._page._client,
            mokr_request,
            response.status_code,
            response.headers,
            False,
            False,
            False,
            httpx_response=response,
        )
        mokr_response._request = mokr_request
        mokr_request._response = mokr_response
        return mokr_request

    async def _transform_http_objs(self, response: httpx.Response) -> Response:
        http_redirect_chain = [response]
        if response.history:
            http_redirect_chain = http_redirect_chain + response.history.copy()
        requests = [(await self._http_to_mokr(r)) for r in http_redirect_chain]
        if len(requests) > 1:
            # The httpx history is reverse to what our redirect_chain is.
            requests.reverse()
            for request in requests:
                request._redirect_chain = requests
        return requests[-1].response

    async def send(
        self,
        url: str,
        method: HTTP_METHODS = "GET",
        params: dict | None = None,
        headers: dict | None = None,
        data: dict | None = None,
        json: dict | None = None,
        **httpx_request_kwargs,
    ) -> Response:
        """
        Send an HTTP request.

        Args:
            url (str): The url to request.
            method (Literal[str], optional): HTTP method. Defaults to "GET".
            params (dict | None, optional): Parameters to encode in the URL
                before sending. Defaults to None (omitted).
            headers (dict | None, optional): Additional headers to send with
                this request beyond what was set when the client was created.
                Defaults to None (omitted).
            data (dict | None, optional): Data payload to deliver with request
                (form-encoded data). Only for "PUT", "POST", and "PATCH".
                Defaults to None (omitted).
            json (dict | None, optional): Data payload to deliver with request
                (JSON-encoded data). Only for "PUT", "POST", and "PATCH".
                Defaults to None (omitted).

        Raises:
            ValueError: Raised if invalid HTTP method given or `data` or `json`
                arguments given with incompatible methods.

        Returns:
            Response: A `mokr.network.Response` created from the
                `httpx.Response`. All redirects will also be created, and
                original requests and responses will be accessible from the
                `mokr.network` objects.
        """
        method = method.upper()
        methods = ("GET", "POST", "OPTIONS", "HEAD", "PUT", "PATCH", "DELETE")
        data_methods = ("POST", "PUT", "PATCH")
        if method not in methods:
            raise ValueError(f"Invalid method: {method}, must be of: {methods}")
        if (data or json) and method not in data_methods:
            raise ValueError(f"Can only send data on methods: {data_methods}")
        kwargs = dict(params=params, headers=headers, data=data, json=json)
        if httpx_request_kwargs:
            kwargs.update(**httpx_request_kwargs)
        kwargs = {k: v for k, v in kwargs.items() if v is not None}
        await self._sync_cookies()
        response = await asyncio.to_thread(
            getattr(self._client, method.lower()),
            url,
            **kwargs,
        )
        await self._sync_cookies()
        return await self._transform_http_objs(response)
