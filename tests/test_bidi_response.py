from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest

import mokr.bidi as bidi
from mokr.bidi.network import BidiFetchDomain, BidiResponse


class RecordingSession:
    def __init__(self, payload) -> None:
        self.payload = payload
        self.calls: list[tuple[str, str]] = []

    async def get_network_data(self, request_id: str, collector: str):
        self.calls.append((request_id, collector))
        return self.payload


def response_event(status: int = 200) -> dict:
    return {
        "navigation": "navigation-1",
        "request": {"request": "request-1"},
        "response": {
            "url": "https://example.test/data",
            "status": status,
            "statusText": "OK" if status == 200 else "Not Found",
            "headers": [
                {
                    "name": "Content-Type",
                    "value": {
                        "type": "string",
                        "value": "application/json",
                    },
                }
            ],
        },
    }


async def test_event_response_normalizes_metadata_and_caches_body() -> None:
    session = RecordingSession(
        {
            "type": "base64",
            "value": base64.b64encode(b'{"answer": 42}').decode(),
        }
    )
    response = BidiResponse(session, response_event(), "collector-1")

    assert response.navigation_id == "navigation-1"
    assert response.url == "https://example.test/data"
    assert response.status == 200
    assert response.reason == "OK"
    assert response.ok is True
    assert response.headers == {"content-type": "application/json"}
    assert await response.json() == {"answer": 42}
    assert await response.buffer() == b'{"answer": 42}'
    assert session.calls == [("request-1", "collector-1")]
    assert await response.to_dict() == {
        "status": 200,
        "headers": {"content-type": "application/json"},
        "body": '{"answer": 42}',
    }


async def test_event_response_requires_a_registered_body_collector() -> None:
    response = BidiResponse(
        RecordingSession(None), response_event(), collector=None
    )

    with pytest.raises(RuntimeError, match="listener before navigating"):
        await response.buffer()


def test_event_response_reports_error_status() -> None:
    response = BidiResponse(
        RecordingSession(None), response_event(status=404), collector=None
    )

    assert response.reason == "Not Found"
    assert response.ok is False


async def test_fetch_response_uses_the_standard_bidi_response_type() -> None:
    body = b"\xff\x00binary"

    async def evaluate(*args):
        return {
            "url": "https://example.test/binary",
            "status": 201,
            "statusText": "Created",
            "headers": [["X-Result", "yes"]],
            "body": base64.b64encode(body).decode(),
        }

    page = SimpleNamespace(
        _default_navigation_timeout=1000,
        evaluate=evaluate,
    )

    response = await BidiFetchDomain(page).fetch("https://example.test/binary")

    assert isinstance(response, BidiResponse)
    assert response.navigation_id is None
    assert response.status == 201
    assert response.reason == "Created"
    assert response.headers == {"x-result": "yes"}
    assert await response.buffer() == body
    assert not hasattr(bidi, "BidiFetchResponse")
