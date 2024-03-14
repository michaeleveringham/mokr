from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
from typing import TYPE_CHECKING, Awaitable

import httpx

from mokr.connection import DevtoolsConnection
from mokr.constants import (
    HTTP_RESPONSE_CODES_TEXT_MAP,
    NETWORK_GET_RESPONSE_BODY,
)
from mokr.exceptions import FirefoxNotImplementedError
from mokr.network.security import SecurityDetails

if TYPE_CHECKING:
    from mokr.network.request import Request


LOGGER = logging.getLogger(__name__)


class Response():
    def __init__(
        self,
        client: DevtoolsConnection,
        request: Request,
        status: int,
        headers: dict[str, str],
        from_disk_cache: bool,
        from_service_worker: bool,
        from_firefox: bool,
        security_details: dict = None,
        extra_info: dict = None,
        httpx_response: httpx.Response | None = None,
    ) -> None:
        """
        Reprentation of a remote response to a network request. `Response`
        objects are created by the `mokr.network.NetworkManager` when a response
        or redirect response is received.

        Pseudo `Response` objects are also made from `httpx.Response` objects
        by a `mokr.network.HttpDomain`.

        Args:
            client (DevtoolsConnection): A `mokr.connection.DevtoolsConnection`
                spawned by the parent `mokr.network.NetworkManager`.
            request (Request): The `mokr.request.Request` that this `Response`
                is bound to. Importantly, the `Request` does not spawn this.
            status (int): Status code for the response.
            headers (dict[str, str]): Response headers as dictionary.
            from_disk_cache (bool): Whether the remote response was served
                from the cache or not.
            from_service_worker (bool): Whether the remote response was served
                by a service worker or not.
            security_details (dict, optional): Security information for a
                given response. Defaults to None.
            extra_info (dict, optional): Any extra info associated with the
                remote response. Defaults to None.
            httpx_response: (httpx.Response | None, optional): If created by a
                `mokr.network.HttpDomain`, the original `httpx.Response` that
                this will be built from.
        """
        self._client = client
        self._request = request
        self._content_promise = self._client._loop.create_future()
        self._url = request.url
        self._from_disk_cache = from_disk_cache
        self._from_service_worker = from_service_worker
        self._from_firefox = from_firefox
        if not extra_info:
            extra_info = {}
        self._status = status
        self._reason = HTTP_RESPONSE_CODES_TEXT_MAP.get(str(status), "Unknown")
        self._extra_status_info = self._parse_extra_info_status_text(extra_info)
        _headers = extra_info.get("headers", headers)
        self._headers = {k.lower(): v for k, v in _headers.items()}
        self._security_details: dict | SecurityDetails = {}
        if security_details:
            self._security_details = SecurityDetails(
                security_details['subjectName'],
                security_details['issuer'],
                security_details['validFrom'],
                security_details['validTo'],
                security_details['protocol'],
            )
        self._httpx_response = httpx_response
        # Overridden via Firefox fetch.
        self._content = None

    def __repr__(self) -> str:
        return f"<Response ({self.status}: {self.reason}) at {id(self)}>"

    @staticmethod
    def _parse_extra_info_status_text(extra_info: dict = None) -> str | None:
        if not extra_info or not extra_info.get("headersText"):
            return
        first_line = extra_info["headersText"].split('\r')[0]
        if not first_line:
            return
        match = re.match(r"/[^ ]* [^ ]* (.*)/", first_line)
        if not match:
            return
        status_text = match[1]
        if not status_text:
            return
        return status_text

    @property
    def url(self) -> str:
        """URL from the remote response."""
        return self._url

    @property
    def ok(self) -> bool:
        """
        Whether the response failed or not (status code between 399 and 600).
        """
        return self._status == 0 or not 400 <= self._status < 599

    @property
    def status(self) -> int:
        """The HTTP status code for the remote response."""
        return self._status

    @property
    def extra_status_info(self) -> str | None:
        """Additional status information from an event's "extraInfo" or None."""
        return self._extra_status_info

    @property
    def reason(self) -> str:
        """The HTTP reason text for the remote response."""
        return self._reason

    @property
    def headers(self) -> dict:
        """All headers for the target response with keys lowered."""
        return self._headers

    @property
    def security_details(self) -> SecurityDetails | None:
        """
        Initialised `mokr.network.SecurityDetails` if the remote response
        was securely received, otherwise None.
        """
        return self._security_details

    @property
    def request(self) -> Request:
        """The `mokr.network.Request` object bound to this `Response`."""
        return self._request

    @property
    def from_cache(self) -> bool:
        """
        Whether the remote response was served from the disk or memory caches.
        """
        return self._from_disk_cache or self._request._from_memory_cache

    @property
    def from_service_worker(self) -> bool:
        """
        Whether the remote response was served by a service worker or not.
        """
        return self._from_service_worker

    @property
    def httpx_response(self) -> bool:
        """
        If created by a `mokr.network.HttpDomain`, this will hold the original
        `httpx.Response` object this was populated from. Otherwise, None.
        """
        return self._httpx_response

    async def _bufread(self) -> bytes:
        response = None
        try:
            response = await self._client.send(
                NETWORK_GET_RESPONSE_BODY,
                {'requestId': self._request._request_id},
            )
        except Exception as e:
            # Redirects have no body.
            if "No data found for resource with given identifier" in str(e):
                pass
            elif 'No resource with given identifier found' in str(e):
                raise type(e)(
                    'Could not load response body, request may be preflight.'
                )
            else:
                raise e
        if not response:
            body = b''
        else:
            body = response.get('body', b'')
            if response.get('base64Encoded'):
                return base64.b64decode(body)
        return body

    def buffer(self, force: bool = False) -> Awaitable[bytes]:
        """
        Return buffer awaitable which queries remote response object's body, if
        not already loaded in this `Response`. Can force querying with the
        `force` option.

        Args:
            force (bool, optional): Whether to bypass checking if the body
                has been cached here. Useful for `mokr.network.FetchDomain`
                requests or other requests where the body may resolve slower.
                Defaults to False.

        Returns:
            Awaitable[bytes]: Awaitable that yields response body as bytes.
        """
        if self._content:
            return self._content
        elif self._from_firefox:
            raise FirefoxNotImplementedError(
                "Firefox doesn't support functionality to use method"
                " Response.buffer."
            )
        elif self._httpx_response:
            # See note in HttpDomain init.
            return asyncio.to_thread(self._httpx_response.read)
        elif force or not self._content_promise.done():
            self._content_promise = self._client._loop.create_task(
                self._bufread()
            )
        return self._content_promise

    async def content(self) -> str | bytes:
        """
        Get body of the remote response object.

        If content is empty, tries to rerun query for the remote response
        object's body via `Response.buffer(force=True)`.

        Returns:
            str | bytes: Content of response.
        """
        if self._content:
            return self._content
        content = await self.buffer()
        if not content:
            # Content may not be accessible yet, retry.
            content = await self.buffer(force=True)
        if isinstance(content, str):
            return content
        else:
            try:
                return content.decode('utf-8')
            except UnicodeDecodeError:
                return content

    async def json(self) -> dict:
        """
        Load the body via `json.loads`.

        Raises:
            JSONDecodeError: Raised from `json.loads` if body is not JSON text.

        Returns:
            dict: Loaded body as dictionary.
        """
        content = await self.content()
        return json.loads(content)

    async def to_dict(self) -> dict:
        """
        Return a dictionary representation of the `Response` including the
        `Response.status`, `Response.headers`, and the response body via
        `Response.content`.

        Returns:
            dict: _description_
        """
        return {
            "status": self.status,
            "headers": self.headers,
            "body": await self.content(),
        }
