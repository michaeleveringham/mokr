import asyncio
import logging
from asyncio import Future
from typing import Awaitable, Callable

import websockets
from pyee import EventEmitter
from websockets.legacy.client import connect

from mokr.connection.base import RemoteConnection
from mokr.connection.devtools import DevtoolsConnection
from mokr.constants import TARGET_ATTACH
from mokr.exceptions import NetworkError


LOGGER = logging.getLogger(__name__)


class Connection(EventEmitter, RemoteConnection):
    def __init__(
        self,
        url: str,
        loop: asyncio.AbstractEventLoop,
        delay: int = 0,
    ) -> None:
        """
        Create remote connection.

        Args:
            url (str): Websocket URL for remote connection.
            loop (asyncio.AbstractEventLoop): Running asyncio loop.
            delay (int, optional): Time in milliseconds to wait before
                handling messages. Defaults to 0.
        """
        super().__init__()
        self._url = url
        self._last_id = 0
        self._callbacks: dict[int, asyncio.Future] = dict()
        self._delay = delay / 1000
        self._loop = loop
        self._sessions: dict[str, DevtoolsConnection] = dict()
        self._connected = False
        self._ws = connect(
            self._url,
            max_size=None,
            loop=self._loop,
            ping_interval=None,
            ping_timeout=None,
        )
        self._recv_fut = self._loop.create_task(self._recv_loop())
        self._close_callback: Callable | None = None
        self.connection: DevtoolsConnection = None

    @property
    def url(self) -> str:
        """Get remote websocket URL."""
        return self._url

    async def _recv_loop(self) -> None:
        async with self._ws as connection:
            self._connected = True
            self.connection = connection
            while self._connected:
                try:
                    resp = await self.connection.recv()
                    if resp:
                        await self._handle_response(resp)
                except (websockets.ConnectionClosed, ConnectionResetError):
                    LOGGER.info('Connection closed.')
                    break
                await asyncio.sleep(0)
        if self._connected:
            self._loop.create_task(self.dispose())

    async def _handle_response(self, response: str) -> None:
        await asyncio.sleep(self._delay)
        self._on_message(response)

    async def _async_send(self, msg: str, callback_id: int) -> None:
        while not self._connected:
            await asyncio.sleep(self._delay)
        try:
            await self.connection.send(msg)
        except websockets.ConnectionClosed:
            LOGGER.warning('Connection closed unexpectedly.')
            callback = self._callbacks.get(callback_id, None)
            if callback and not callback.done():
                callback.set_result(None)
                await self.dispose()

    def _on_successful_response(self, callback: Future, msg: dict) -> None:
        callback.set_result(msg.get('result'))

    def _on_query(self, msg: dict) -> None:
        result, method, params = self._handle_detached_or_received(msg)
        if not result:
            self.emit(method, params)

    async def _on_close(self) -> None:
        if self._close_callback:
            self._close_callback()
            self._close_callback = None
        for callback in self._callbacks.values():
            callback.set_exception(
                self._rewrite_exception(
                    callback.error,
                    f'Protocol error {callback.method}: Target closed.',
                )
            )
        self._callbacks.clear()
        for session in self._sessions.values():
            session._on_closed()
        self._sessions.clear()
        if hasattr(self, 'connection'):
            await self.connection.close()
        if not self._recv_fut.done():
            self._recv_fut.cancel()

    def _set_closed_callback(self, callback: Callable) -> None:
        self._close_callback = callback

    def send(self, method: str, params: dict = None) -> Awaitable[dict]:
        """
        Send message to remote connection via websocket.

        Args:
            method (str): Method to run.
            params (dict, optional): Arguments for method, if any.
                Defaults to None.

        Raises:
            ConnectionError: Raised if the connection is closed.

        Returns:
            Awaitable[dict]: Remote response as dictionary.
        """
        # Detect connection availability from the second transmission.
        if self._last_id and not self._connected:
            raise ConnectionError('Connection is closed.')
        msg = self._prepare_message(method, params)
        self._loop.create_task(self._async_send(msg, self._last_id))
        callback = self._loop.create_future()
        self._callbacks[self._last_id] = callback
        callback.error = NetworkError()
        callback.method = method
        return callback

    async def dispose(self) -> None:
        """Sever all connections."""
        self._connected = False
        await self._on_close()

    async def create_session(self, target_info: dict) -> DevtoolsConnection:
        """
        Create a new `mokr.connection.DevtoolsConnection`.

        Args:
            target_info (dict): Target info from triggered event.

        Returns:
            DevtoolsConnection: New `DevtoolsConnection`.
        """
        resp = await self.send(
            TARGET_ATTACH,
            {'targetId': target_info['targetId']}
        )
        session_id = resp.get('sessionId')
        session = DevtoolsConnection(
            self,
            target_info['type'],
            session_id,
            self._loop,
        )
        self._sessions[session_id] = session
        return session
