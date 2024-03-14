from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from mokr.connection import DevtoolsConnection
from mokr.constants import (
    NETWORK_MGR_REQUEST,
    NETWORK_MGR_REQUEST_FINISHED,
    NETWORK_MGR_RESPONSE,
    NETWORK_REQUEST_WILL_BE_SENT,
    NETWORK_RESPONSE_RECVD,
)
from mokr.frame import FrameManager
from mokr.network.manager.base import NetworkManager
from mokr.network.request import Request
from mokr.network.response import Response

if TYPE_CHECKING:
    from mokr.browser.page import Page


LOGGER = logging.getLogger(__name__)


class FirefoxNetworkManager(NetworkManager):
    def __init__(
        self,
        page: Page,
        client: DevtoolsConnection,
        frame_manager: FrameManager,
        interception_callback_chain: list[Callable],
    ) -> None:
        """
        Class to handle requests in a given `mokr.browser.Page`.

        Note that functionality of this class is severely limited compared to
        it's Chrome counterpart, `mokr.network.ChromeNetworkManager`.

        Request interception does not block requests and can only be used to
        observe partial request and response data.

        The `interception_callback_chain` this class receives from the parent
        `mokr.browser.Page` is shared with spawned `mokr.network.Request`
        objects. While the request interception callback chain is run from the
        `Request` object, it is initiated during select events from this class.

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
            NETWORK_REQUEST_WILL_BE_SENT: (
                lambda event: self._client._loop.create_task(
                    self._on_request(event)
                )
            ),
            NETWORK_RESPONSE_RECVD: self._on_response_received,
        }
        super().__init__(
            page,
            client,
            frame_manager,
            interception_callback_chain,
        )
        self._request_id_to_request = {}

    async def _on_request(self, event: dict) -> None:
        # Firefox request event never has a "redirectResponse", not handling.
        mokr_request_uuid = self._inspect_stack_for_mokr_uuid(event)
        requestId = event['requestId']
        frame = (
            self._frame_manager.frame(event['frameId'])
            if event.get('frameId') else None
        )
        is_navigation_request = bool(
            event.get('requestId') == event.get('loaderId')
            and event.get('type') == 'Document'
        )
        request = Request(
            self._page,
            self._client,
            event['requestId'],
            None,
            is_navigation_request,
            self._user_request_interception_enabled,
            event.get('request', {}).get('url'),
            event.get('type', ''),
            event.get('request', {}),
            frame,
            [],
            self._interception_callback_chain,
        )
        if mokr_request_uuid:
            request._mokr_request_uuid = mokr_request_uuid
        self._request_id_to_request[requestId] = request
        self.emit(NETWORK_MGR_REQUEST, request)
        await request._finalize_interceptions()

    def _on_response_received(self, event: dict) -> None:
        # Firefox doesn't emit on extraInfo event ever so not handling.
        request = self._request_id_to_request.get(event['requestId'])
        # FileUpload sends a response without a matching request.
        if not request:
            return
        _response = event.get('response', {})
        response = Response(
            self._client,
            request,
            _response.get('status', 0),
            _response.get('headers', {}),
            _response.get('fromDiskCache'),
            _response.get('fromServiceWorker'),
            True,
            _response.get('securityDetails'),
            None,
        )
        request._response = response
        self.emit(NETWORK_MGR_RESPONSE, response)
        # Hacky but Firefox doesn't emit a loading finished event.
        # Assume finished Document request means loading finished.
        if event["type"] == "Document":
            self.emit(NETWORK_MGR_REQUEST_FINISHED, request)

    @property
    def extra_http_headers(self) -> dict[str, str]:
        """
        For parity; Firefox doesn't support sending extra headers via CDP.
        """
        return self._extra_http_headers

    async def set_request_interception(self, *args, **kwargs) -> None:
        """
        Not supported by Firefox.

        Raises:
            FirefoxNotImplementedError: When Firefox unsupported errors are on.
        """
        self._page._is_firefox(caller=self)

    async def set_extra_http_headers(self, *args, **kwargs) -> None:
        """
        Not supported by Firefox.

        Raises:
            FirefoxNotImplementedError: When Firefox unsupported errors are on.
        """
        self._page._is_firefox(caller=self)
