from __future__ import annotations

import base64
import copy
import inspect
import logging
from typing import TYPE_CHECKING, Callable

import httpx

from mokr.connection import DevtoolsConnection
from mokr.constants import (
    FETCH_CONTINUE,
    FETCH_FAIL,
    FETCH_FULFILL,
    HTTP_RESPONSE_CODES_TEXT_MAP,
    NETWORK_ERROR_CODES_TO_REASONS,
)
from mokr.exceptions import NetworkError
from mokr.frame import Frame

if TYPE_CHECKING:
    from mokr.browser.page import Page
    from mokr.network.response import Response


LOGGER = logging.getLogger(__name__)


class Request():
    def __init__(
        self,
        page: Page,
        client: DevtoolsConnection,
        request_id: str | None,
        interception_id: str | None,
        is_navigation_request: bool,
        allow_interception: bool,
        url: str,
        resource_type: str,
        payload: dict,
        frame: Frame | None,
        redirect_chain: list[Request],
        interception_callback_chain: list[Callable],
        httpx_request: httpx.Request | None = None,
    ) -> None:
        """
        Representative of a remote network request, this object is created
        by a `mokr.network.NetworkManager`.

        The creation of a `Request` does not signify the request has been sent,
        or that a request response has been received.

        Args:
            page (Page): Parent `mokr.browser.Page`.
            client (DevtoolsConnection): A `mokr.connection.DevtoolsConnection`
                spawned by the parent `mokr.network.NetworkManager`.
            request_id (str | None): The network request identifier, from the
                remote request event's requestId.
            interception_id (str | None): The fetch request identifier, from the
                remote request event's interceptionId. This can be confusing as
                the fetch domain refers to this as the requestId.
            is_navigation_request (bool): Whether or not this request will
                affect remote frame navigation.
            allow_interception (bool): Whether or not to allow "request" event
                interception.
            url (str): The remote request URL.
            resource_type (str): Resource type as it was perceived by the
                rendering engine. See `Request.resource_type` for more.
            payload (dict): Request data and metadata.
            frame (Frame | None): The `mokr.frame.Frame` this request originated
                from.
            redirect_chain (list[Request]): A list of `Request` objects that
                were redirects and lead to this request.
            interception_callback_chain (list[Callable]): A list of callbacks
                shared with the parent `mokr.network.NetworkManager` and its
                parent `mokr.browser.Page`. These callbacks wil run sequentially
                during "request" event interception. See `mokr.browser.Page` for
                more information.
            httpx_request: (httpx.Request | None, optional): If created by a
                `mokr.network.HttpDomain`, the original `httpx.Request` that
                this will be built from.
        """
        self._page = page
        self._client = client
        self._request_id = request_id
        self._is_navigation_request = is_navigation_request
        self._interception_id = interception_id
        self._allow_interception = allow_interception
        self._interception_handled = False
        self._response: Response | None = None
        self._failure_text: str | None = None
        self._url = url
        self._resource_type = resource_type.lower()
        self._method = payload.get('method')
        self._post_data = payload.get('postData')
        headers = payload.get('headers', {})
        self._headers = {k.lower(): v for k, v in headers.items()}
        self._frame = frame
        self._redirect_chain = redirect_chain
        self._from_memory_cache = False
        self._interception_callback_chain = interception_callback_chain
        # This will only be set in FetchDomain handling.
        self._mokr_request_uuid = None
        self._httpx_request = httpx_request

    def __repr__(self) -> str:
        return f"<Request ({self.method} to {self.url}) at {id(self)}>"

    @property
    def url(self) -> str:
        """URL from the remote request."""
        return self._url

    @property
    def resource_type(self) -> str:
        """
        Resource type as it was perceived by the rendering engine.

        One of "Document", "Stylesheet", "Image", "Media", "Font", "Script",
        "TextTrack", "XHR", "Fetch", "Prefetch", "EventSource", "WebSocket",
        "Manifest", "SignedExchange", "Ping", "CSPViolationReport", "Preflight",
        or "Other".
        """
        return self._resource_type

    @property
    def method(self) -> str | None:
        """
        HTTP request method from remote request, such as "GET", "POST", "PATCH".
        """
        return self._method

    @property
    def post_data(self) -> str | None:
        """Data from this `Request`'s `payload["postData"]`, if any."""
        return self._post_data

    @property
    def headers(self) -> dict:
        """All headers for the target request with keys lowered."""
        return self._headers

    @property
    def response(self) -> Response | None:
        """
        The `mokr.network.Response` object created from the remote response
        bound to the remote request, or None if not yet received.
        """
        return self._response

    @property
    def frame(self) -> Frame | None:
        """The corresponding `mokr.frame.Frame`, if any."""
        return self._frame

    @property
    def redirect_chain(self) -> list['Request']:
        """
        Return the chain of `Request` objects if the first remote request
        was a redirect.

        The chain will be shared will all subsequent `Request` objects initiated
        from the redirect, and the final `Request` in the chain will not be
        a redirect.
        """
        return copy.copy(self._redirect_chain)

    @property
    def httpx_request(self) -> bool:
        """
        If created by a `mokr.network.HttpDomain`, this will hold the original
        `httpx.Request` object this was populated from. Otherwise, None.
        """
        return self._httpx_request

    def _verify_request_allowed(self) -> None:
        if not self._allow_interception:
            raise NetworkError('Request interception is not enabled.')
        if self._interception_handled:
            raise NetworkError('Request is already handled.')
        if self._httpx_request:
            raise ValueError(
                "Cannot run interception methods on HttpDomain-based requests."
            )

    async def _run_callback_chain(self, callback_chain: list[Callable]) -> None:
        result = None
        callback_chain = callback_chain.copy()
        for index, callback in enumerate(callback_chain):
            if index == 0:
                args = [self]
            else:
                if result:
                    args = [result]
                else:
                    return
            if inspect.iscoroutinefunction(callback):
                result = await callback(*args)
            else:
                result = callback(*args)

    async def _default_request_intercept(self, request: Request) -> None:
        if not self._page._is_firefox(mute=True):
            return await request.release()

    async def _finalize_interceptions(self) -> None:
        if not self._allow_interception:
            return
        self._verify_request_allowed()
        # If somehow the default intercept the `Page` added was removed and
        # the chain is completely empty, use a similar default here.
        if not self._interception_callback_chain:
            self._interception_callback_chain.append(
                self._default_request_intercept
            )
        await self._run_callback_chain(self._interception_callback_chain)

    def is_navigation_request(self) -> bool:
        """
        Whether or not this request will affect remote frame navigation.

        Returns:
            bool: True if navigating the frame, otherwise False.
        """
        return self._is_navigation_request

    def failure_text(self) -> str | None:
        """
        Return error text from failed requests. For successful requests, this
        will return None.

        Returns:
            str | None: Error text if request failed, otherwise None.
        """
        return self._failure_text

    async def release(
        self,
        url: str = None,
        method: str = None,
        post_data: str = None,
        headers: dict = None,
    ) -> None:
        """
        Release an intercepted request, optionally altering select parameters.

        Stops execution of the rest of the interception chain.

        Args:
            url (str, optional): The URL to overwrite the request with, if any.
                Defaults to None (use initiated `Request.url`).
            method (str, optional): The HTTP request method (e.g. "GET", "POST")
                to overwrite the request with, if any.
                Defaults to None (use initiated `Request.url`).
            post_data (str, optional): The post data (payload["postData"]) to
                overwrite the request with, if any.
                Defaults to None (use initiated `Request.post_data`).
            headers (dict, optional): Headers, will completely replace existing
                headers. Defaults to None (use `Request.headers`).
        """
        if self._url.startswith('data:'):
            return
        self._verify_request_allowed()
        self._interception_handled = True
        # Sometimes we have no fetch ID (interception ID), but the request ID
        # is usually the interception ID in these edge-cases.
        if not self._interception_id:
            self._interception_id = self._request_id
        params = {'requestId': self._interception_id}
        overrides = {
            k: v for k, v in {
                "url": url,
                "method": method,
                "postData": post_data,
                "headers": headers,
            }.items()
            if v is not None
        }
        params.update(overrides)
        try:
            await self._client.send(FETCH_CONTINUE, params)
        except Exception:
            LOGGER.error("Error continuing network request.", exc_info=True)

    async def fulfill(
        self,
        response: Response | None = None,
        status: int = 200,
        headers: dict | None = None,
        body: str | bytes | None = None,
    ) -> None:
        """
        Respond to a request with the given response data. Prevents the
        remote request from being actually sent. Cannot be used with
        data urls.

        Stops execution of the rest of the interception chain.

        Args:
            response (Response | None, optional): A completed
                `mokr.network.Reponse` object to extract data from. Passing
                this will ignore all other kwargs passed.
                Defaults to None.
            status (int, optional): HTTP status code. Defaults to 200.
            headers (dict | None, optional): Response headers.
                Defaults to None (empty headers).
            body (str | bytes | None, optional): Response body.
                Defaults to None (empty body).
        """
        if self._url.startswith('data:'):
            return
        self._verify_request_allowed()
        if response:
            body = await response.content()
            status = response.status
            headers = response.headers
        overrides = {
            "responseCode": status,
            "responsePhrase": HTTP_RESPONSE_CODES_TEXT_MAP[str(status)],
            "responseHeaders": headers,
            "body": body,
        }
        self._interception_handled = True
        fields = ["responseCode", "responsePhrase", "responseHeaders", "body"]
        overrides = {
            k: v for k, v in overrides.items()
            if v is not None and k in fields
        }
        headers_dict = {}
        if overrides.get('responseHeaders'):
            for name, value in overrides['responseHeaders'].items():
                headers_dict[name.lower()] = value
        if overrides.get('body'):
            if isinstance(overrides['body'], str):
                body = body.encode()
            if 'content-length' not in headers_dict:
                headers_dict['content-length'] = len(body)
            overrides["body"] = base64.b64encode(body).decode()
        prepared_headers = []
        if headers_dict:
            for name, value in headers_dict.items():
                prepared_headers.append({"name": name, "value": str(value)})
        overrides["responseHeaders"] = prepared_headers
        params = {'requestId': self._interception_id, **overrides}
        try:
            await self._client.send(FETCH_FULFILL, params)
        except Exception:
            LOGGER.error("Error fulfilling request.", exc_info=True)

    async def abort(self, error_reason: str = "failed") -> None:
        """
        Abort the remote request. This will prevent the request from being sent,
        which can cause a `mokr.exceptions.PageError` to raise later if
        `Request.is_navigation_request` is True.

        Stops execution of the rest of the interception chain.

        Args:
            error_reason (str, optional): The error reason to give when aborting
                the request. One of "Failed", "Aborted", "TimedOut",
                "AccessDenied", "ConnectionClosed", "ConnectionReset",
                "ConnectionRefused", "ConnectionAborted", "ConnectionFailed",
                "NameNotResolved", "InternetDisconnected", "AddressUnreachable",
                "BlockedByClient", or "BlockedByResponse".
                Defaults to "failed".

        Raises:
            NetworkError: Raised if unknown error reason is given.
        """
        if error_reason not in NETWORK_ERROR_CODES_TO_REASONS.values():
            error_reason = NETWORK_ERROR_CODES_TO_REASONS[error_reason]
            if not error_reason:
                raise NetworkError(f'Unknown error reason: {error_reason}')
        self._verify_request_allowed()
        self._interception_handled = True
        try:
            await self._client.send(
                FETCH_FAIL,
                {
                    "requestId": self._interception_id,
                    "errorReason": error_reason,
                },
            )
        except Exception:
            LOGGER.error("Error aborting request.", exc_info=True)
