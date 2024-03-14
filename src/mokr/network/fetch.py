from __future__ import annotations

import asyncio
import concurrent.futures
import json
import uuid
from typing import TYPE_CHECKING, Any, Literal

from pyee import EventEmitter

from mokr.constants import (
    HTTP_CACHE_TYPES,
    HTTP_METHODS,
    FETCH_DOMAIN_REQUEST_SENT,
    METHOD_FETCH_REQUEST,
    NETWORK_REQUEST,
    NETWORK_RESPONSE,
    REFERRER_POLICIES,
)
from mokr.exceptions import MokrTimeoutError, NetworkError, PageError
from mokr.execution.handle.javascript import JavascriptHandle
from mokr.network.request import Request
from mokr.network.response import Response
from mokr.waiters import EventWaiter

if TYPE_CHECKING:
    from mokr.browser.page import Page


class _FirefoxResponseReady(Exception):
    """Used to cancel timeout and transfer response data."""
    def __init__(self, data: dict) -> None:
        self.data = data


class FetchDomain(EventEmitter):
    def __init__(
        self,
        page: Page,
    ) -> None:
        """
        Client to handle sending manual fetch requests.

        Note that sending fetch requests from this class will temporarily
        enable request interception globally. However, these fetch requests
        won't be caught by the request interception chain, however "response"
        and "requestfinished" events will still be caught.

        For Firefox this is not applicable. Fetch requests in Firefox
        are built manually from the response data. Unlike standard Firefox
        request responses, the response body is available for `FetchDomain`
        responses.

        Chrome requests take advantage of the existing fetch system in its
        `mokr.network.NetworkManager` while Firefox cannot; Chrome could
        do the same as Firefox does here and build the objects directly but
        some features would be lost like redirect chain.

        Args:
            page (Page): Parent `mokr.browser.Page` this was spawned from.
        """
        super().__init__()
        self._page = page
        self._requests_in_flight = set()
        self._request_id_to_response: dict[str, Request] = {}
        self._is_firefox = self._page._is_firefox(mute=True)
        self._page.on(NETWORK_RESPONSE, self._response_intercept)

    async def _request_has_response(self, request: Request) -> Response:
        if not request._mokr_request_uuid:
            return
        while True:
            done = False
            if not request.redirect_chain and request.response:
                done = True
            elif request.redirect_chain:
                for _request in request.redirect_chain:
                    response = _request.response
                    # If redirect, wait for the final response.
                    if response and not 299 < response.status < 400:
                        done = True
                    else:
                        done = False
            if not done:
                # Yield while waiting for response to be recieved.
                await asyncio.sleep(0)
            else:
                break
        return True

    async def _register_requests(self, request: Request) -> Request:
        if not request._mokr_request_uuid:
            return request
        else:
            self.emit(FETCH_DOMAIN_REQUEST_SENT, request)
            self._request_id_to_response[request._request_id] = None
            # Bypass the rest of the existing request intercept chain.
            await request.release()

    async def _evaluate_handle(
        self,
        page_function: str,
        *args: Any,
        eval_script_url_suffix: str | None = None,
    ) -> JavascriptHandle:
        frame = self._page._ensure_frame()
        context = await frame.execution_context()
        if not context:
            raise PageError('No context attached to frame.')
        try:
            return await context.evaluate_handle(
                page_function,
                *args,
                eval_script_url_suffix=eval_script_url_suffix,
            )
        except NetworkError as error:
            # Ignore, we likely intentionally destroyed it due to timeout.
            if "Execution context destroyed" in str(error):
                pass
            else:
                raise

    async def _fetch(self, request_uuid: str, url: str, params: dict) -> None:
        self._requests_in_flight.add(request_uuid)
        # The uuid is tacked onto the script name and extracted in interception.
        response = await self._evaluate_handle(
            METHOD_FETCH_REQUEST,
            url,
            params,
            eval_script_url_suffix=request_uuid,
        )
        try:
            response_data = json.loads(response._remote_object["value"])
            # Use this to cancel timer in Firefox as predicate will be useless
            # since the stack in browser won't share the javascript url with
            # the uuid in it.
            if self._is_firefox:
                raise _FirefoxResponseReady(response_data)
        except (json.JSONDecodeError, TypeError, KeyError):
            return None

    def _response_intercept(self, response: Response) -> None:
        request = response._request
        if not request._mokr_request_uuid:
            return
        self._request_id_to_response[response._request._request_id] = response

    def _select_response_chrome(self, request_uuid: str) -> Response:
        responses = {
            request_id: response for request_id, response in
            self._request_id_to_response.items()
            if response and response._request._mokr_request_uuid == request_uuid
        }
        # This should never happen.
        if not responses:
            raise NetworkError(
                "Fetch request failed, no response could be found for request."
                " The destination URL may have a CORS policy enabled that this"
                " page does not have access to."
            )
        request_id = next(iter(responses))
        return self._request_id_to_response.pop(request_id)

    def _make_response_firefox(self, response_data: dict) -> Response:
        request = response_data["request"]
        payload = {
            "method": request["method"],
            "postData": request.get("body", ""),
            "headers": request.get("headers", {}),  # Will be incomplete.
        }
        mokr_request = Request(
            self._page,
            self._page._client,
            "firefoxfetch",
            None,
            False,
            False,
            response_data["url"],
            response_data["type"],
            payload,
            None,
            [],
            [],
        )
        mokr_response = Response(
            self._page._client,
            mokr_request,
            response_data["status"],
            response_data["headers"],
            False,
            False,
            True,
        )
        mokr_response._request = mokr_request
        mokr_response._content = response_data["body"]
        mokr_request._response = mokr_response
        return mokr_response

    def _select_response(self, request_uuid: str, data: dict) -> Response:
        if self._is_firefox:
            return self._make_response_firefox(data)
        else:
            return self._select_response_chrome(request_uuid)

    def _check_for_response_data(
        self,
        task: asyncio.Task,
        params: dict,
    ) -> dict | None:
        # Check if Firefox fetch resolved.
        response_data = None
        error = task.exception()
        if error and isinstance(error, _FirefoxResponseReady):
            response_data = error.data
            # Pass params to build request from, too.
            response_data["request"] = params
        elif error:
            # This should never happen here...
            raise MokrTimeoutError("Timeout waiting for fetch to resolve.")
        return response_data

    async def fetch(
        self,
        url: str | None = None,
        timeout: int = None,
        request: Request | None = None,
        body: str | None = None,
        browsing_topics: bool | None = None,
        cache: HTTP_CACHE_TYPES | None = None,
        credentials: Literal["omit", "same-origin", "include"] | None = None,
        headers: dict | None = None,
        method: HTTP_METHODS = "GET",
        mode: Literal["cors", "no-cors", "same-origin"] = None,
        priority: Literal["high", "low", "auto"] | None = None,
        redirect: Literal["follow", "error", "manual"] | None = None,
        referrer: str | None = None,
        referrer_policy: REFERRER_POLICIES | None = None,
    ) -> Response:
        """
        Send a fetch request.

        Note that fetch is sensitive to the current site's CORS settings.
        Additionally, trying to send a fetch request before the DOM loads can
        hang forever.

        Args:
            url (str | None, optional): The url to request.
                Ignored if `request` is given.
                Defaults to None.
            timeout (int, optional): Time in milliseconds to wait.
                Defaults to None.
            request (Request | None, optional): A request object to pull `url`,
                `method`, and `headers` from. Defaults to None.
            body (str | None, optional): Body to add to the request.
                Defaults to None.
            browsing_topics (bool | None, optional): If True, selected topics
                will be sent in a Sec-Browsing-Topics header with the associated
                request.
                Defaults to None.
            cache (HTTP_CACHE_TYPES): How the request should interact with the
                HTTP cache. One of: "default", "no-store", "reload", "no-cache",
                "force-cache", or "only-if-cache".
                Defaults to None.
            credentials (Literal[str] | None, optional): How to handle
                credentials. One of "omit", "same-origin", or "include".
                Defaults to None.
            headers (dict | None, optional): Headers to pass with the request.
                Defaults to None.
            method (HTTP_METHODS, optional): HTTP method. Defaults to "GET".
            mode (Literal["cors", "no-cors", "same-origin"], optional):
                CORS mode to use. Defaults to None.
            priority (Literal["high", "low", "auto"] | None, optional):
                Priority of request relative to others. Defaults to None.
            redirect (Literal["follow", "error", "manual"] | None, optional):
                How to handle redirects. Defaults to None ("follow").
            referrer (str | None, optional): Request referrer. Defaults to None.
            referrer_policy (REFERRER_POLICIES): The referrer policy to use.
                One of "no-referrer", "no-referrer-when-downgrade",
                "same-origin", "origin", "strict-origin",
                "origin-when-cross-origin", "strict-origin-when-cross-origin",
                or "unsafe-url".
                Defaults to None ("strict-origin-when-cross-origin").

        Raises:
            ValueError: Raised if neither `url` nor `request` given.
            NetworkError: Raised if no response found when request resolves.

        Returns:
            Response: Last response recieved after all redirects, if any.
        """
        request_uuid = uuid.uuid4().hex.upper()
        interception_enabled = (
            self._page._network_manager._protocol_request_interception_enabled
        )
        # Must enable request interception, if not already enabled.
        if not interception_enabled and not self._is_firefox:
            await self._page.set_request_interception_enabled(True)
        # Done here instead of in constructor, should be 0th priority.
        self._page.on(NETWORK_REQUEST, self._register_requests)
        if request:
            url = request.url
            headers = request.headers
            method = request.method
        elif not url:
            raise ValueError("Must provide URL or request.")
        params = {
            name: value for name, value in {
                "body": body,
                "browsingTopics": browsing_topics,
                "cache": cache,
                "credentials": credentials,
                "headers": headers,
                "method": method,
                "mode": mode,
                "priority": priority,
                "redirect": redirect,
                "referrer": referrer,
                "referrerPolicy": referrer_policy,
            }.items() if value is not None
        }
        waiter = EventWaiter(
            self,
            FETCH_DOMAIN_REQUEST_SENT,
            self._request_has_response,
            timeout if timeout else self._page._default_navigation_timeout,
            self._page._client._loop,
        )
        # Setup waiter and make request.
        promise = asyncio.ensure_future(waiter.wait())
        done, _ = await asyncio.wait(
            [
                promise,
                self._fetch(request_uuid, url, params),
            ],
            return_when=concurrent.futures.FIRST_EXCEPTION,
        )
        if promise.done() and promise.exception():
            raise MokrTimeoutError("Timeout waiting for fetch to resolve.")
        response_data = self._check_for_response_data(done.pop(), params)
        self._requests_in_flight.remove(request_uuid)
        # Remove intercept callback if no more FetchDomain requests in flight.
        if not self._requests_in_flight:
            self._page._interception_callback_chain.remove(
                self._register_requests
            )
            if not interception_enabled and not self._is_firefox:
                await self._page.set_request_interception_enabled(False)
        response = self._select_response(request_uuid, response_data)
        return response
