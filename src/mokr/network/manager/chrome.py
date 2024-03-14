from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Callable, Literal

from mokr.connection import DevtoolsConnection
from mokr.constants import (
    FETCH_AUTH_REQD,
    FETCH_CONTINUE,
    FETCH_CONTINUE_AUTH,
    FETCH_DISABLED,
    FETCH_ENABLED,
    FETCH_REQUEST_PAUSED,
    NETWORK_LOADING_FAILED,
    NETWORK_LOADING_FINISHED,
    NETWORK_MGR_REQUEST,
    NETWORK_MGR_REQUEST_FAILED,
    NETWORK_MGR_REQUEST_FINISHED,
    NETWORK_MGR_REQUEST_FROM_CACHE,
    NETWORK_MGR_RESPONSE,
    NETWORK_REQUEST_SERVED_FROM_CACHE,
    NETWORK_REQUEST_WILL_BE_SENT,
    NETWORK_RESPONSE_RECVD,
    NETWORK_RESPONSE_RECVD_EXTRA,

)
from mokr.frame import FrameManager
from mokr.network.event import NetworkEventManager
from mokr.network.manager.base import NetworkManager
from mokr.network.request import Request
from mokr.network.response import Response

if TYPE_CHECKING:
    from mokr.browser.page import Page


LOGGER = logging.getLogger(__name__)


class ChromeNetworkManager(NetworkManager):
    def __init__(
        self,
        page: Page,
        client: DevtoolsConnection,
        frame_manager: FrameManager,
        interception_callback_chain: list[Callable],
    ) -> None:
        """
        Class to handle requests in a given `mokr.browser.Page`.

        This class relies on network events to be emitted, and stores events
        and even requests to handle the various possible chains of events.

        The `interception_callback_chain` this class receives from the parent
        `mokr.browser.Page` is shared with spawned `mokr.network.Request`
        objects. While the request interception callback chain is run from the
        `Request` object, it is initiated during select events from this class.

        There are four possible orders that requests will be triggered and thus
        handled by `NetworkManager`:

        -  `_on_request_will_be_sent`.
        -  `_on_request_will_be_sent`, `_on_request_paused`.
        -  `_on_request_paused`, `_on_request_will_be_sent`.
        -  `_on_request_paused`, `_on_request_will_be_sent`,
            `_on_request_paused`, `_on_request_will_be_sent`,
            `_on_request_paused`, `_on_request_paused` (see
            crbug.com/1196004).

        There are a few different ways requests need to be handled due to this:
        - For `_on_request` we need the event from `_on_request_will_be_sent`
        and optionally the `fetch_request_id` (event["requestId"] also known as
        "interceptionId") from `_on_request_paused`.
        - If request interception is disabled, call `_on_request` once per call
        to `_on_request_will_be_sent`.
        - If request interception is enabled, call `_on_request` once per call
        to `_on_request_paused` (once per `fetch_request_id`).
        - Events are stored via the `mokr.network.NetworkEventManager`
        to allow for subsequent events to call `_on_request`.
        - Chains of redirect requests have the same `requestId` as
        the original request. This means events can be received in multiple
        orders for different requests in the same redirect chain such as:
            - `_on_request_will_be_sent`, `_on_request_will_be_sent`, ...
            - `_on_request_will_be_sent`, `_on_request_paused`,
                `_on_request_will_be_sent`, `_on_request_paused`, ...
            - `_on_request_will_be_sent`, `_on_request_paused`,
                `_on_request_paused`, `_on_request_will_be_sent`, ...
            - `_on_request_paused`, `_on_request_will_be_sent`,
                `_on_request_paused`, `_on_request_will_be_sent`,
                `_on_request_paused`, `_on_request_will_be_sent`,
                `_on_request_paused`, `_on_request_paused`, ...
                (see crbug.com/1196004)

        Args:
            page (Page): Parent `mokr.browser.Page`.
            client (DevtoolsConnection): A `mokr.connection.DevtoolsConnection`
                spawned by the parent `mokr.browser.Page`.
            frame_manager (FrameManager): The `mokr.frame.FrameManager`
                from the `mokr.browser.Page` that spawned this element.
            interception_callback_chain (list[Callable]): A list of callbacks
                to be passed into new `mokr.network.Request`s that will be run
                during "request" event interception, by that object. Inherited
                from the parent `mokr.browser.Page`.
        """
        self._events_to_methods = {
            FETCH_REQUEST_PAUSED: (
                lambda event: self._client._loop.create_task(
                    self._on_request_paused(event)
                )
            ),
            FETCH_AUTH_REQD: self._on_auth_required,
            NETWORK_REQUEST_WILL_BE_SENT: (
                lambda event: self._client._loop.create_task(
                    self._on_request_will_be_sent(event)
                )
            ),
            NETWORK_REQUEST_SERVED_FROM_CACHE: self._on_request_from_cache,
            NETWORK_RESPONSE_RECVD: self._on_response_received,
            NETWORK_LOADING_FINISHED: self._on_loading_finished,
            NETWORK_LOADING_FAILED: self._on_loading_failed,
            NETWORK_RESPONSE_RECVD_EXTRA: (
                lambda event: self._client._loop.create_task(
                    self._on_response_received_extra_info(event)
                )
            ),
        }
        super().__init__(
            page,
            client,
            frame_manager,
            interception_callback_chain,
        )
        self._network_event_manager = NetworkEventManager()

    @staticmethod
    def _patch_request_event_headers(
        request_will_be_sent_event: dict,
        request_paused_event: dict,
    ) -> None:
        request_will_be_sent_event['request']['headers'].update(
            request_paused_event['request']['headers']
        )

    @property
    def extra_http_headers(self) -> dict[str, str]:
        """
        Any extra HTTP headers assigned to this class. These are sent
        with every request this manager handles.
        """
        return self._extra_http_headers

    def _on_auth_required(self, event: dict) -> None:
        response = 'Default'
        if event['requestId'] in self._attempted_authentications:
            response = 'CancelAuth'
        elif self.credentials:
            self._attempted_authentications.add(event['requestId'])
            response = 'ProvideCredentials'
            params = {"response": response}
            creds = getattr(self, 'credentials', {})
            params["username"] = creds.get('username')
            params["password"] = creds.get('password')
            params = {k: v for k, v in params.items() if v}
        self._client.send(
            FETCH_CONTINUE_AUTH,
            {
                'requestId': event['requestId'],
                'authChallengeResponse': params,
            },
        )

    def _on_request_from_cache(self, event: dict) -> None:
        request = self._network_event_manager.get_request(event['requestId'])
        if request:
            request._from_memory_cache = True
        self.emit(NETWORK_MGR_REQUEST_FROM_CACHE, request)

    def _handle_request_redirect(
        self,
        request: Request,
        response_payload: dict[str, Any],
        extra_info: dict = None,
    ):
        response = Response(
            self._client,
            request,
            response_payload.get('status', 0),
            response_payload.get('headers', {}),
            response_payload.get('fromDiskCache'),
            response_payload.get('fromServiceWorker'),
            False,
            response_payload.get('securityDetails'),
            extra_info,
        )
        request._response = response
        if request not in request._redirect_chain:
            request._redirect_chain.append(request)
        self.forget_request(request, False)
        self.emit(NETWORK_MGR_RESPONSE, response)
        self.emit(NETWORK_MGR_REQUEST_FINISHED, request)

    def _emit_response_event(
        self,
        response_received: dict,
        extra_info: dict = None
    ) -> None:
        request_id = response_received['requestId']
        request = self._network_event_manager.get_request(request_id)
        # FileUpload sends a response without a matching request.
        if not request:
            return
        extraInfos = self._network_event_manager.response_extra_info(request_id)
        if extraInfos:
            LOGGER.error(
                'Unexpected extraInfo events for request'
                f' {request_id}'
            )
        # Chrome sends wrong extraInfo events for responses served from cache.
        # See https://github.com/puppeteer/puppeteer/issues/9965 and
        # https://crbug.com/1340398.
        if response_received['response']['fromDiskCache']:
            extra_info = None
        _response = response_received.get('response', {})
        response = Response(
            self._client,
            request,
            _response.get('status', 0),
            _response.get('headers', {}),
            _response.get('fromDiskCache'),
            _response.get('fromServiceWorker'),
            False,
            _response.get('securityDetails'),
            extra_info,
        )
        request._response = response
        self.emit(NETWORK_MGR_RESPONSE, response)

    def _on_response_received(self, event: dict) -> None:
        request_id = event['requestId']
        request = self._network_event_manager.get_request(request_id)
        extra_info = None
        if (
            request and not request._from_memory_cache and event['hasExtraInfo']
        ):
            _responseExtraInfo = (
                self._network_event_manager.response_extra_info(request_id)
            )
            if _responseExtraInfo:
                extra_info = _responseExtraInfo[0]
                _responseExtraInfo.remove(extra_info)
        if not extra_info:
            # Wait until we get the corresponding ExtraInfo event.
            self._network_event_manager.queue_event_group(
                request_id,
                {'responseReceivedEvent': event},
            )
            return
        self._emit_response_event(event, extra_info)

    def _on_loading_finished(self, event: dict) -> None:
        # If the response event for this request is still waiting on a
        # corresponding ExtraInfo event, then wait to emit this event too.
        queued_events = self._network_event_manager.get_queued_event_group(
            event['requestId']
        )
        if queued_events:
            queued_events['loadingFinishedEvent'] = event
        else:
            self._emit_loading_finished(event)

    def _emit_loading_finished(self, event: dict) -> None:
        request = self._network_event_manager.get_request(event['requestId'])
        # For certain requestIds we never receive requestWillBeSent event.
        # @see https://crbug.com/750469
        # Under certain conditions we never get the Network.responseReceived
        # event from protocol. @see https://crbug.com/883475
        if not request:
            return
        self.forget_request(request, True)
        self.emit(NETWORK_MGR_REQUEST_FINISHED, request)

    def _on_loading_failed(self, event: dict) -> None:
        # If the response event for this request is still waiting on a
        # corresponding ExtraInfo event, then wait to emit this event too.
        queued_events = self._network_event_manager.get_queued_event_group(
            event['requestId']
        )
        if queued_events:
            queued_events['loadingFailedEvent'] = event
        else:
            self._emit_loading_failed(event)

    def _emit_loading_failed(self, event):
        request = self._network_event_manager.get_request(event['requestId'])
        # // For certain requestIds we never receive requestWillBeSent event.
        # // @see https://crbug.com/750469
        if not request:
            return
        request._failure_text = event['errorText']
        self.forget_request(request, True)
        self.emit(NETWORK_MGR_REQUEST_FAILED, request)

    async def _apply_protocol_request_interception(self) -> None:
        if self._user_cache_disabled is None:
            self._user_cache_disabled = False
        if self._protocol_request_interception_enabled:
            await asyncio.gather(
                self._apply_protocol_cache_disabled(),
                self._client.send(
                    FETCH_ENABLED,
                    {
                        'handleAuthRequests': True,
                        'patterns': [{'urlPattern': '*'}],
                    }
                ),
            )
        else:
            await asyncio.gather(
                self._apply_protocol_cache_disabled(),
                self._client.send(FETCH_DISABLED),
            )

    async def _on_request_will_be_sent(self, event: dict) -> None:
        # Request interception doesn't happen for data URLs.
        if (
            self._user_request_interception_enabled
            and not event['request']['url'].startswith('data:')
        ):
            network_request_id = event['requestId']
            self._network_event_manager.store_request_will_be_sent(
                network_request_id,
                event,
            )
            # Fetch.requestPaused may have been sent already. Check for it.
            request_paused_event = (
                self._network_event_manager.get_request_paused(
                    network_request_id
                )
            )
            if request_paused_event:
                fetch_request_id = request_paused_event['requestId']
                self._patch_request_event_headers(event, request_paused_event)
                await self._on_request(event, fetch_request_id)
                self._network_event_manager.forget_request_paused(
                    network_request_id
                )
            return
        await self._on_request(event, None)

    async def _on_request_paused(self, event: dict) -> None:
        # CDP may send a "Fetch.requestPaused" event without or before a
        # "Network.requestWillBeSent" event.
        # CDP may also send multiple "Fetch.requestPaused" events
        # for the same "Network.requestWillBeSent" event.
        if (
            not self._user_request_interception_enabled
            and self._protocol_request_interception_enabled
        ):
            self._client.send(
                FETCH_CONTINUE,
                {'requestId': event['requestId']},
            )
        network_request_id = event.get('networkId')
        fetch_request_id = event['requestId']
        if not network_request_id:
            await self._on_request_without_network_instrumentation(event)
            return

        request_will_be_sent_event = (
            self._network_event_manager.get_request_will_be_sent(
                network_request_id
            )
        )
        # Redirect requests have the same requestId.
        if request_will_be_sent_event and (
            (
                request_will_be_sent_event['request']['url']
                != event['request']['url']
            )
            or (
                request_will_be_sent_event['request']['method']
                != event['request']['method']
            )
        ):
            self._network_event_manager.forget_request_will_be_sent(
                network_request_id
            )
            request_will_be_sent_event = None
        if request_will_be_sent_event:
            self._patch_request_event_headers(request_will_be_sent_event, event)
            await self._on_request(request_will_be_sent_event, fetch_request_id)
        else:
            self._network_event_manager.store_request_paused(
                network_request_id,
                event,
            )

    async def _on_request_without_network_instrumentation(
        self,
        event: dict,
    ) -> None:
        mokr_request_uuid = self._inspect_stack_for_mokr_uuid(event)
        # If an event has no networkId it should not have any network events.
        # Still want to dispatch it for the interception by the user.
        frame = (
            self._frame_manager.frame(event['frameId'])
            if event.get('frameId') else None
        )
        request = Request(
            self._page,
            self._client,
            event['requestId'],
            None,
            False,
            self._user_request_interception_enabled,
            event.get('request', {}).get('url'),
            event.get('type', ''),
            event.get('request', {}),
            frame,
            [],
            self._interception_callback_chain,
        )
        # This should never happen here.
        if mokr_request_uuid:
            request._mokr_request_uuid = mokr_request_uuid
        self.emit(NETWORK_MGR_REQUEST, request)
        await request._finalize_interceptions()

    async def _on_request(
        self,
        event: dict,
        fetch_request_id: str = None,
    ) -> None:
        redirect_chain = []
        mokr_request_uuid = self._inspect_stack_for_mokr_uuid(event)
        if event.get('redirectResponse'):
            # Want to emit "response" and "requestfinished" events for the
            # redirectResponse, but can't do so unless we have an event's
            # "responseExtraInfo" ready to pair it up with. If we don't have any
            # "responseExtraInfo" data saved in our queue under this event's
            # requestId, must wait for the next one to emit both "response" and
            # "requestfinished" events, but we also should wait to emit this
            # `mokr.network.Request` via a "NetworkManager.Request" event
            # because it should come after "response"/"requestfinished" events.
            redirect_response_extra_info = None
            if event.get('redirectHasExtraInfo'):
                _response_extra_info = (
                    self._network_event_manager.response_extra_info(
                        event['requestId']
                    )
                )
                if _response_extra_info:
                    redirect_response_extra_info = _response_extra_info[0]
                    _response_extra_info.remove(redirect_response_extra_info)
                if not redirect_response_extra_info:
                    self._network_event_manager.queue_redirect_info(
                        event['requestId'],
                        {"event": event, "fetchRequestId": fetch_request_id},
                    )
                    return
            request = self._network_event_manager.get_request(
                event['requestId']
            )
            # If we connect late, may have missed requestWillBeSent.
            if request:
                self._handle_request_redirect(
                    request,
                    event.get('redirectResponse'),
                    redirect_response_extra_info
                )
                redirect_chain = request._redirect_chain
        frame = (
            self._frame_manager.frame(event['frameId'])
            if event.get('frameId') else None
        )
        is_navigation_request = bool(
            event.get('requestId') == event.get('loaderId')
            and event.get('type') == 'Document'
        )
        # Bind the same FetchDomain request uuid to redirect requests.
        if (
            not mokr_request_uuid
            and any(r._mokr_request_uuid for r in redirect_chain)
        ):
            mokr_request_uuid = next(
                iter(r._mokr_request_uuid for r in redirect_chain)
            )
        request = Request(
            self._page,
            self._client,
            event['requestId'],
            fetch_request_id,
            is_navigation_request,
            self._user_request_interception_enabled,
            event.get('request', {}).get('url'),
            event.get('type', ''),
            event.get('request', {}),
            frame,
            redirect_chain,
            self._interception_callback_chain,
        )
        # Append final request to redirect chain.
        if request not in request._redirect_chain:
            request._redirect_chain.append(request)
        if mokr_request_uuid:
            request._mokr_request_uuid = mokr_request_uuid
        self._network_event_manager.store_request(event['requestId'], request)
        self.emit(NETWORK_MGR_REQUEST, request)
        await request._finalize_interceptions()

    async def _on_response_received_extra_info(self, event: dict) -> None:
        # We may have skipped a redirect response/request pair due to waiting
        # for this ExtraInfo event.
        request_id = event['requestId']
        redirect_info = self._network_event_manager.take_queued_redirect_info(
            request_id
        )
        if redirect_info:
            self._network_event_manager.response_extra_info(
                request_id
            ).append(event)
            await self._on_request(
                redirect_info['event'],
                redirect_info['fetchRequestId'],
            )
            return
        # We may have skipped response and loading events because we didn't have
        # this ExtraInfo event yet. If so, emit those events now.
        queued_events = self._network_event_manager.get_queued_event_group(
            request_id
        )
        if queued_events:
            self._network_event_manager.forget_queued_event_group(request_id)
            self._emit_response_event(
                queued_events['responseReceivedEvent'],
                event,
            )
            if queued_events.get('loadingFinishedEvent'):
                self._emit_loading_finished(
                    queued_events['loadingFinishedEvent']
                )
            if queued_events.get('loadingFailedEvent'):
                self._emit_loading_failed(queued_events['loadingFailedEvent'])
            return
        # Wait until we get another event that can use this ExtraInfo event.
        self._network_event_manager.response_extra_info(
            request_id
        ).append(event)

    def forget_request(self, request: Request, events: bool) -> None:
        """
        Drop a request from the `mokr.network.NetworkEventManager` and
        remove from attempted authentications listing, if relevant.

        Optionally forget all events tied to the remote request networkID, too.

        Args:
            request (Request): `mokr.request.Request` to forget.
            events (bool): If True, drop all events stored for the request, too.
        """
        request_id = request._request_id
        interception_id = request._interception_id
        self._network_event_manager.forget_request(request_id)
        if interception_id:
            try:
                self._attempted_authentications.remove(interception_id)
            except KeyError:
                pass
        if events:
            self._network_event_manager.forget(request_id)

    def get_in_flight_requests_count(self) -> int:
        """
        Get the number of active requests (not resolved).
        Wraps `mokr.network.NetworkEventManager.get_in_flight_requests_count`.

        Returns:
            int: Number of active requests.
        """
        return self._network_event_manager.get_in_flight_requests_count()

    async def set_credentials(
        self,
        credentials: dict[Literal["username", "password"], str],
    ) -> None:
        """
        Set the credentials to use for HTTP authentication.

        Args:
            credentials (dict[str, str]): A dictionary with credentials,
                keyed as "username" and "password".
        """
        self.credentials = credentials
        enabled = (
            self._user_request_interception_enabled or not self.credentials
        )
        if enabled == self._protocol_request_interception_enabled:
            return
        self._protocol_request_interception_enabled = enabled
        self._apply_protocol_request_interception()

    async def set_extra_http_headers(
        self,
        extra_http_headers: dict[str, str],
    ) -> None:
        """
        Set extra headers to be sent with every request.

        Args:
            extra_http_headers (dict[str, str]): A dictionary of headers.

        Raises:
            ValueError: Raised if any header value is not string.
        """
        for key, value in extra_http_headers.items():
            if not isinstance(value, str):
                raise ValueError(
                    f'Expected value of header "{key}"'
                    f' to be str, not {type(value)}.'
                )
        self._extra_http_headers.update(extra_http_headers)
        await self._apply_extra_http_headers()

    async def set_request_interception(self, choice: bool) -> None:
        """
        Disable or enabled request interception (enabled by default).
        See `mokr.browser.Page.on` for details on using the request interception
        callback chain.

        Args:
            choice (bool): False to disable, True to enable.
        """
        self._user_request_interception_enabled = choice
        enabled = (
            self._user_request_interception_enabled or bool(self.credentials)
        )
        if enabled == self._protocol_request_interception_enabled:
            return
        self._protocol_request_interception_enabled = enabled
        await self._apply_protocol_request_interception()
