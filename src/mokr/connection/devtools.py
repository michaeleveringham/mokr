from __future__ import annotations

import asyncio
import logging
from asyncio import Future
from typing import TYPE_CHECKING, Awaitable

from pyee import EventEmitter

from mokr.connection.base import RemoteConnection
from mokr.constants import TARGET_SEND_DETACH, TARGET_SEND_MSG
from mokr.exceptions import NetworkError

if TYPE_CHECKING:
    from mokr.connection.connection import Connection


LOGGER = logging.getLogger(__name__)


class DevtoolsConnection(EventEmitter, RemoteConnection):
    def __init__(
        self,
        connection: Connection | DevtoolsConnection,
        target_type: str,
        session_id: str,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        """
        Create new CDP (Chrome Devtools Protocol) session.

        Most functionality is controlled by calling CDP methods or handling
        CDP events. Read more about these at:
        https://chromedevtools.github.io/devtools-protocol/

        Args:
            connection (Connection | DevtoolsConnection): Parent remote
                connection to use.
            target_type (str): Type of target this connection is for.
            session_id (str): Unique session identifier.
            loop (asyncio.AbstractEventLoop): Running asyncio loop.
        """
        super().__init__()
        self._last_id = 0
        self._callbacks: dict[int, asyncio.Future] = {}
        self._connection: Connection | None = connection
        self._target_type = target_type
        self._sessionId = session_id
        self._sessions: dict[str, DevtoolsConnection] = dict()
        self._loop = loop

    def _on_successful_response(self, callback: Future, msg: dict) -> None:
        if callback and not callback.done():
            callback.set_result(msg.get('result'))

    def _on_query(self, msg: dict) -> None:
        _, method, params = self._handle_detached_or_received(msg)
        self.emit(method, params)

    def _on_closed(self) -> None:
        for cb in self._callbacks.values():
            cb.set_exception(self._rewrite_exception(
                cb.error,
                f'Protocol error {cb.method}: Target closed.',
            ))
        self._callbacks.clear()
        self._connection = None

    def _create_session(
        self,
        target_type: str,
        session_id: str,
    ) -> DevtoolsConnection:
        session = DevtoolsConnection(self, target_type, session_id, self._loop)
        self._sessions[session_id] = session
        return session

    def send(self, method: str, params: dict = None) -> Awaitable[dict]:
        """
        Send a message to the remote connection.

        Args:
            method (str): Method to run.
            params (dict, optional): Arguments for method, if any.
                Defaults to None.

        Raises:
            NetworkError: Raised if connection is closed.

        Returns:
            Awaitable[dict]: Remote response as dictionary.
        """
        if not self._connection:
            raise NetworkError(
                f'Protocol Error ({method}): Session closed. Most likely the'
                f' {self._target_type} has been closed.'
            )
        msg = self._prepare_message(method, params)
        callback = self._loop.create_future()
        self._callbacks[self._last_id] = callback
        callback.error = NetworkError()
        callback.method = method
        try:
            self._connection.send(
                TARGET_SEND_MSG,
                {
                    'sessionId': self._sessionId,
                    'message': msg,
                }
            )
        except Exception as e:
            # The response from target may have already been dispatched.
            if self._last_id in self._callbacks:
                _callback = self._callbacks.pop(self._last_id)
                _callback.set_exception(
                    self._rewrite_exception(
                        _callback.error,
                        e.args[0],
                    )
                )
        return callback

    async def detach(self) -> None:
        """
        Detach session from it's target. Once detached, it is invalid and
        cannot receive or send messages.

        Raises:
            NetworkError: Raised if remote connection is already closed.
        """
        if not self._connection:
            raise NetworkError('Connection already closed.')
        await self._connection.send(
            TARGET_SEND_DETACH,
            {'sessionId': self._sessionId},
        )
