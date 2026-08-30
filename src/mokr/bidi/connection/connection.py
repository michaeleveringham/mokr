from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from pyee import EventEmitter
from websockets.legacy.client import connect


class BidiProtocolError(Exception):
    """An error response received from a WebDriver BiDi remote end."""

    def __init__(self, error: str, message: str, stacktrace: str = "") -> None:
        self.error = error
        self.stacktrace = stacktrace
        super().__init__(f"BiDi error ({error}): {message}")


class BidiConnection(EventEmitter):
    """Maintain an event-capable WebSocket connection to WebDriver BiDi.

    Commands are sent with :meth:`send`; protocol events are exposed through
    :class:`pyee.EventEmitter`. Pending command futures are resolved by the
    matching BiDi response or failed when the transport closes.
    """

    def __init__(
        self,
        url: str,
        loop: asyncio.AbstractEventLoop | None = None,
        connector: Callable[..., Awaitable[Any]] = connect,
        create_session: bool = False,
        session_capabilities: dict[str, Any] | None = None,
    ) -> None:
        """Create a WebDriver BiDi connection.

        Args:
            url: WebSocket URL for the remote BiDi endpoint.
            loop: Event loop used for transport tasks. Defaults to the current
                event loop.
            connector: Async WebSocket connector, injectable for tests.
            create_session: Whether :meth:`start` should issue
                ``session.new`` after connecting.
            session_capabilities: Capabilities supplied to ``session.new``.
        """
        super().__init__()
        self._url = url
        self._loop = loop or asyncio.get_event_loop()
        self._connector = connector
        self._create_session = create_session
        self._session_capabilities = session_capabilities or {}
        self._connection: Any | None = None
        self._recv_task: asyncio.Task | None = None
        self._pending: dict[int, asyncio.Future] = {}
        self._last_id = 0
        self._closed = False

    @property
    def url(self) -> str:
        """The WebSocket endpoint supplied by the WebDriver session."""
        return self._url

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        """Event loop used by this transport."""
        return self._loop

    @property
    def connected(self) -> bool:
        """Whether the WebSocket connection has completed its handshake."""
        return self._connection is not None and not self._closed

    async def start(self) -> BidiConnection:
        """Connect to a BiDi endpoint, optionally creating a native session.

        Firefox's direct Remote Agent endpoint has no HTTP WebDriver session
        and therefore requires the static ``session.new`` command. An endpoint
        returned by an existing WebDriver session must leave this disabled.

        Returns:
            This connected instance.
        """
        if self.connected:
            return self
        self._connection = await self._connector(
            self._url,
            max_size=None,
            ping_interval=None,
            ping_timeout=None,
        )
        self._closed = False
        self._recv_task = self._loop.create_task(self._recv_loop())
        if self._create_session:
            await self.send(
                "session.new", {"capabilities": self._session_capabilities}
            )
        return self

    def send(
        self, method: str, params: dict[str, Any] | None = None
    ) -> asyncio.Future:
        """Send a command to the remote BiDi endpoint.

        Args:
            method: Fully qualified BiDi command name.
            params: Command parameters. Defaults to an empty mapping.

        Raises:
            ConnectionError: If the WebSocket connection is closed.

        Returns:
            A future that resolves to the command's result mapping.
        """
        if not self.connected:
            raise ConnectionError("WebDriver BiDi connection is closed.")
        self._last_id += 1
        command_id = self._last_id
        future = self._loop.create_future()
        self._pending[command_id] = future
        payload = {
            "id": command_id,
            "method": method,
            "params": params or {},
        }
        task = self._loop.create_task(
            self._connection.send(json.dumps(payload))
        )
        task.add_done_callback(
            lambda completed: self._handle_send_result(command_id, completed)
        )
        return future

    def _handle_send_result(self, command_id: int, task: asyncio.Task) -> None:
        try:
            task.result()
        except Exception as error:
            future = self._pending.pop(command_id, None)
            if future and not future.done():
                future.set_exception(error)

    async def _recv_loop(self) -> None:
        try:
            while self._connection is not None:
                message = await self._connection.recv()
                self._on_message(json.loads(message))
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._fail_pending(error)
        finally:
            self._closed = True
            self.emit("disconnected")

    def _on_message(self, message: dict[str, Any]) -> None:
        message_type = message.get("type")
        if message_type == "event":
            self.emit(message["method"], message.get("params", {}))
            return
        command_id = message.get("id")
        future = self._pending.pop(command_id, None)
        if future is None or future.done():
            return
        if message_type == "success":
            future.set_result(message.get("result", {}))
            return
        if message_type == "error":
            future.set_exception(
                BidiProtocolError(
                    message.get("error", "unknown error"),
                    message.get("message", ""),
                    message.get("stacktrace", ""),
                )
            )
            return
        future.set_exception(BidiProtocolError("invalid message", str(message)))

    def _fail_pending(self, error: Exception) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(error)
        self._pending.clear()

    async def dispose(self) -> None:
        """Close the WebSocket and fail commands that are still pending.

        Repeated calls are safe and have no effect after the first close.
        """
        if self._closed:
            return
        self._closed = True
        self._fail_pending(ConnectionError("WebDriver BiDi connection closed."))
        if self._connection is not None:
            await self._connection.close()
        if self._recv_task and not self._recv_task.done():
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
