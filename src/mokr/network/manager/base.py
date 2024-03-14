from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from pyee import EventEmitter

from mokr.connection import DevtoolsConnection
from mokr.constants import (
    NETWORK_CACHE_DISABLE,
    NETWORK_EMULATE_NETWORK_CONDITIONS,
    NETWORK_ENABLE,
    NETWORK_EXTRA_HEADERS,
    NETWORK_USER_AGENT_OVERRIDE,
    SECURITY_IGNORE_HTTPS_ERRORS,

)
from mokr.frame import FrameManager
from mokr.execution.context import EVALUATION_SCRIPT_URL

if TYPE_CHECKING:
    from mokr.browser.page import Page


class NetworkManager(EventEmitter):
    def __init__(
        self,
        page: Page,
        client: DevtoolsConnection,
        frame_manager: FrameManager,
        interception_callback_chain: list[Callable],
    ) -> None:
        super().__init__()
        self._page = page
        self._client = client
        self._frame_manager = frame_manager
        self._interception_callback_chain = interception_callback_chain
        self._extra_http_headers = {}
        self._protocol_request_interception_enabled = None
        self._user_request_interception_enabled = True
        self._user_cache_disabled = True
        self._attempted_authentications = set()
        self._emulated_network_conditions = {}
        self.credentials = {}
        self.user_agent = ''
        self.user_agent_metadata = ''
        for event, method in self._events_to_methods.items():
            self._client.on(event, method)

    @classmethod
    async def create(
        cls,
        page: Page,
        client: DevtoolsConnection,
        frame_manager: FrameManager,
        ignore_https_errors: bool,
        interception_callback_chain: list[Callable]
    ) -> NetworkManager:
        """
        Async constructor for this class. Necessary to run some asyncronous
        post-initialisation tasks.

        Args:
            page (Page): Parent `mokr.browser.Page`.
            client (DevtoolsConnection): A `mokr.connection.DevtoolsConnection`
                spawned by the parent `mokr.browser.Page`.
            frame_manager (FrameManager): A `mokr.frame.FrameManager`
                spawned by the parent `mokr.browser.Page`.
            ignore_https_errors (bool): Ignore site security errors.
                Inherited from parent `mokr.browser.Page`.
            interception_callback_chain (list[Callable]): A list of callables
                for use with "request" event interception. This list is
                shared by the parent `mokr.browser.Page` and all newly created
                `mokr.network.Request` objects in this manager.

        Returns:
            NetworkManager: New `NetworkManager` with applied configurations.
        """
        network_manager = cls(
            page,
            client,
            frame_manager,
            interception_callback_chain,
        )
        if ignore_https_errors:
            await network_manager._client.send(
                SECURITY_IGNORE_HTTPS_ERRORS,
                {"ignore": True},
            )
        await network_manager._client.send(NETWORK_ENABLE)
        await network_manager._apply_network_conditions()
        await network_manager._apply_protocol_cache_disabled()
        await network_manager._apply_user_agent()
        if not page._is_firefox(mute=True):
            await network_manager._apply_extra_http_headers()
            await network_manager._apply_protocol_request_interception()
        return network_manager

    async def _apply_extra_http_headers(self) -> None:
        if not self._extra_http_headers:
            return
        await self._client.send(
            NETWORK_EXTRA_HEADERS,
            {"headers": self._extra_http_headers},
        )

    async def _apply_network_conditions(self) -> None:
        if not self._emulated_network_conditions:
            return
        await self._client.send(
            NETWORK_EMULATE_NETWORK_CONDITIONS,
            {
                'offline': self._emulated_network_conditions['offline'],
                'latency': self._emulated_network_conditions['latency'],
                'uploadThroughput': self._emulated_network_conditions['upload'],
                'downloadThroughput': (
                    self._emulated_network_conditions['download']
                ),
            }
        )

    async def _apply_protocol_cache_disabled(self) -> None:
        if not self._user_cache_disabled:
            return
        await self._client.send(
            NETWORK_CACHE_DISABLE,
            {'cacheDisabled': self._user_cache_disabled},
        )

    async def _apply_user_agent(self) -> None:
        if not self.user_agent:
            return
        params = {'userAgent': self.user_agent}
        if self.user_agent_metadata:
            params['userAgentMetadata'] = self.user_agent_metadata,
        await self._client.send(NETWORK_USER_AGENT_OVERRIDE, params)

    def _inspect_stack_for_mokr_uuid(self, event: dict) -> str | None:
        mokr_request_uuid = None
        # FetchDomain requests add a unique id to the script URL for tracking.
        stack = event.get("initiator", {}).get("stack", {})
        call_frames = stack.get("callFrames", [])
        if call_frames:
            url = call_frames[0].get("url", "")
            if EVALUATION_SCRIPT_URL in url:
                mokr_request_uuid = url.replace(EVALUATION_SCRIPT_URL, "")
        return mokr_request_uuid

    async def set_extra_http_headers(self) -> None:
        raise NotImplementedError

    async def set_request_interception(self) -> None:
        raise NotImplementedError

    async def set_credentials(self) -> None:
        raise NotImplementedError

    async def emulate_network_conditions(
        self,
        latency: int | None = 0,
        download: int | None = -1,
        upload: int | None = -1,
    ) -> None:
        """
        Emulate the given network conditions. If network conditions unset,
        will set them to the default (disable all throttling and no latency).

        Args:
            latency (int, optional): Minimum latency in milliseconds from
                request sent to response headers received. Defaults to None (0).
            download (int, optional): Maximum download throughput (bytes/sec).
                Defaults to None (-1, disabled).
            upload (int, optional): Minimum download throughput (bytes/sec).
                Defaults to None (-1, disabled).
        """
        if not self._emulated_network_conditions:
            self._emulated_network_conditions = {
                "offline": False,
                "upload": -1,
                "download": -1,
                "latency": 0,
            }
        options = {
            "upload": upload,
            "download": download,
            "latency": latency,
        }
        for option, value in options.items():
            if value is None:
                continue
            self._emulated_network_conditions[option] = value
        await self._apply_network_conditions()

    async def set_offline_mode(self, choice: bool) -> None:
        """
        Enable or diable offline mode. Disabled by default.

        Args:
            enabled (bool): False to disable, True to enable.
        """
        if not self._emulated_network_conditions:
            self._emulated_network_conditions = {
                "offline": False,
                "upload": -1,
                "download": -1,
                "latency": 0,
            }
        self._emulated_network_conditions['offline'] = choice
        await self._apply_network_conditions()

    async def set_request_cache(self, enabled: bool) -> None:
        """
        Enable or disable request caching. Request caching caches requests in
        the browser, not `mokr.network.Request` objects.

        Does not check if request caching was enabled already by parent
        `mokr.browser.Page`.

        Args:
            enabled (bool, optional): True to enable, False to disable.
                Defaults to True.
        """
        self._user_cache_disabled = not enabled
        await self._apply_protocol_cache_disabled()

    async def set_user_agent(
        self,
        user_agent: str,
        user_agent_metadata: str | None = None,
    ) -> None:
        """
        Update the user agent to be sent with every request.

        Args:
            user_agent (str): User agent string.
            user_agent_metadata (str | None, optional): Experimental, used to
                specify user agent client hints to emulate.
        """
        self.user_agent = user_agent
        self.user_agent_metadata = user_agent_metadata
        await self._apply_user_agent()
