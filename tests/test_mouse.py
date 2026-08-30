from __future__ import annotations

from types import SimpleNamespace

import pytest

from mokr.bidi.input import BidiMouse
from mokr.cdp.input import CdpMouse
from mokr.constants import INPUT_MOUSE

from .conftest import FakeDevtoolsClient


class RecordingBidiSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[dict]]] = []

    async def perform_actions(
        self, context_id: str, actions: list[dict]
    ) -> None:
        self.calls.append((context_id, actions))


def pointer_actions(session: RecordingBidiSession) -> list[dict]:
    return session.calls[-1][1][0]["actions"]


async def test_mice_start_at_the_viewport_origin() -> None:
    bidi_session = RecordingBidiSession()
    bidi_mouse = BidiMouse(bidi_session, "context-1")
    await bidi_mouse.click()

    cdp_client = FakeDevtoolsClient()
    cdp_mouse = CdpMouse(cdp_client, SimpleNamespace(_modifiers=0))
    await cdp_mouse.click(delay=None)

    assert pointer_actions(bidi_session)[0]["x"] == 0
    assert pointer_actions(bidi_session)[0]["y"] == 0
    assert cdp_client.calls[0][1]["x"] == 0
    assert cdp_client.calls[0][1]["y"] == 0


async def test_bidi_mouse_tracks_move_steps_and_clicks_in_place() -> None:
    session = RecordingBidiSession()
    mouse = BidiMouse(session, "context-1")

    await mouse.move(12, 6, steps=3)
    assert pointer_actions(session) == [
        {
            "type": "pointerMove",
            "x": 4,
            "y": 2,
            "origin": "viewport",
            "duration": 0,
        },
        {
            "type": "pointerMove",
            "x": 8,
            "y": 4,
            "origin": "viewport",
            "duration": 0,
        },
        {
            "type": "pointerMove",
            "x": 12,
            "y": 6,
            "origin": "viewport",
            "duration": 0,
        },
    ]

    await mouse.click()
    assert pointer_actions(session)[0] == {
        "type": "pointerMove",
        "x": 12,
        "y": 6,
        "origin": "viewport",
        "duration": 0,
    }


async def test_bidi_mouse_explicit_click_updates_position() -> None:
    session = RecordingBidiSession()
    mouse = BidiMouse(session, "context-1")

    await mouse.click(20, 30, delay=5)
    await mouse.click(button="right")

    assert pointer_actions(session)[0]["x"] == 20
    assert pointer_actions(session)[0]["y"] == 30
    assert pointer_actions(session)[1:] == [
        {"type": "pointerDown", "button": 2},
        {"type": "pointerUp", "button": 2},
    ]


async def test_cdp_mouse_clicks_at_its_tracked_position() -> None:
    client = FakeDevtoolsClient()
    mouse = CdpMouse(client, SimpleNamespace(_modifiers=0))

    await mouse.move(20, 30)
    await mouse.click(delay=None)

    assert client.calls[-2:] == [
        (
            INPUT_MOUSE,
            {
                "type": "mousePressed",
                "button": "left",
                "x": 20,
                "y": 30,
                "modifiers": 0,
                "clickCount": 1,
            },
        ),
        (
            INPUT_MOUSE,
            {
                "type": "mouseReleased",
                "button": "left",
                "x": 20,
                "y": 30,
                "modifiers": 0,
                "clickCount": 1,
            },
        ),
    ]


@pytest.mark.parametrize("mouse_kind", ["bidi", "cdp"])
async def test_mouse_rejects_partial_coordinates_and_invalid_steps(
    mouse_kind: str,
) -> None:
    if mouse_kind == "bidi":
        mouse = BidiMouse(RecordingBidiSession(), "context-1")
    else:
        mouse = CdpMouse(FakeDevtoolsClient(), SimpleNamespace(_modifiers=0))

    with pytest.raises(ValueError, match="both x and y"):
        await mouse.click(x=10)
    with pytest.raises(ValueError, match="at least 1"):
        await mouse.move(10, 10, steps=0)
