from __future__ import annotations

import io
import math

import pytest
from pyee import EventEmitter

from mokr.exceptions import ElementHandleError
from mokr.utils.remote import (
    add_event_listener,
    format_javascript_exception,
    is_javascript_method,
    remove_event_listeners,
    serialize_remote_object,
)
from mokr.utils.launch import get_bidi_ws_endpoint


class ClosedProcess:
    def __init__(self) -> None:
        self.stdout = io.StringIO("")

    def poll(self) -> int:
        return 1


@pytest.mark.parametrize(
    ("remote_object", "expected"),
    [
        ({"value": "text"}, "text"),
        ({"unserializableValue": "-0"}, 0),
        ({"unserializableValue": "NaN"}, None),
        ({"unserializableValue": "Infinity"}, math.inf),
        ({"unserializableValue": "-Infinity"}, -math.inf),
    ],
)
def test_serialize_remote_object_primitives(remote_object, expected) -> None:
    assert serialize_remote_object(remote_object) == expected


def test_serialize_remote_object_rejects_non_primitives() -> None:
    with pytest.raises(ElementHandleError, match="objectId"):
        serialize_remote_object({"objectId": "remote-1"})

    with pytest.raises(ElementHandleError, match="Unserializable value"):
        serialize_remote_object({"unserializableValue": "123n"})


def test_event_listener_helpers_remove_registered_listener() -> None:
    emitter = EventEmitter()
    received = []
    listeners = [
        add_event_listener(
            emitter, "ready", lambda value: received.append(value)
        )
    ]

    emitter.emit("ready", "first")
    remove_event_listeners(listeners)
    emitter.emit("ready", "second")

    assert received == ["first"]
    assert listeners == []


def test_javascript_exception_formatting_and_method_detection() -> None:
    formatted = format_javascript_exception(
        {
            "text": "ReferenceError",
            "stackTrace": {
                "callFrames": [
                    {
                        "functionName": "run",
                        "url": "script.js",
                        "lineNumber": 4,
                        "columnNumber": 2,
                    }
                ]
            },
        }
    )

    assert "ReferenceError" in formatted
    assert "at run (script.js:4:2)" in formatted
    assert is_javascript_method(" function() {} ")
    assert is_javascript_method("async () => {}")
    assert not is_javascript_method("document.title")


def test_bidi_endpoint_uses_known_port_after_windows_process_handoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class OpenSocket:
        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            pass

    monkeypatch.setattr(
        "mokr.utils.launch.socket.create_connection",
        lambda address, timeout: OpenSocket(),
    )

    assert (
        get_bidi_ws_endpoint(ClosedProcess(), "ws://127.0.0.1:9222/session")
        == "ws://127.0.0.1:9222/session"
    )
