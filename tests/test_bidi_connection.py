from __future__ import annotations

import asyncio
import json

import pytest

from mokr.bidi.connection import BidiConnection, BidiProtocolError


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent = []
        self.incoming = asyncio.Queue()
        self.closed = False

    async def send(self, message: str) -> None:
        self.sent.append(json.loads(message))

    async def recv(self) -> str:
        return await self.incoming.get()

    async def close(self) -> None:
        self.closed = True


async def test_bidi_connection_routes_commands_and_events() -> None:
    socket = FakeWebSocket()

    async def connector(*args, **kwargs):
        return socket

    connection = BidiConnection("ws://bidi.test", connector=connector)
    await connection.start()
    received = []
    connection.on("log.entryAdded", lambda params: received.append(params))

    command = connection.send("browsingContext.getTree", {})
    await asyncio.sleep(0)
    await socket.incoming.put(
        json.dumps(
            {
                "type": "event",
                "method": "log.entryAdded",
                "params": {"text": "hello"},
            }
        )
    )
    await socket.incoming.put(
        json.dumps({"type": "success", "id": 1, "result": {"contexts": []}})
    )

    assert await command == {"contexts": []}
    assert received == [{"text": "hello"}]
    assert socket.sent == [
        {"id": 1, "method": "browsingContext.getTree", "params": {}},
    ]
    await connection.dispose()


async def test_bidi_connection_surfaces_protocol_errors() -> None:
    socket = FakeWebSocket()

    async def connector(*args, **kwargs):
        return socket

    connection = BidiConnection("ws://bidi.test", connector=connector)
    await connection.start()

    command = connection.send("network.addIntercept")
    await asyncio.sleep(0)
    await socket.incoming.put(
        json.dumps(
            {
                "type": "error",
                "id": 1,
                "error": "invalid argument",
                "message": "bad phase",
            }
        )
    )

    with pytest.raises(BidiProtocolError, match="bad phase"):
        await command
    await connection.dispose()


async def test_native_bidi_connection_creates_a_session_after_connecting() -> (
    None
):
    socket = FakeWebSocket()

    async def connector(*args, **kwargs):
        return socket

    connection = BidiConnection(
        "ws://bidi.test/session",
        connector=connector,
        create_session=True,
    )
    start_task = asyncio.create_task(connection.start())
    await asyncio.sleep(0)
    await socket.incoming.put(
        json.dumps({"type": "success", "id": 1, "result": {}})
    )
    await start_task

    assert socket.sent == [
        {"id": 1, "method": "session.new", "params": {"capabilities": {}}}
    ]
    await connection.dispose()
