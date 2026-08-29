from __future__ import annotations

import pytest

from mokr.cdp.browser.viewport import CdpViewportManager
from mokr.constants import EMULATION_ENABLE_TOUCH, EMULATION_OVERRIDE_METRICS

from .conftest import FakeDevtoolsClient


async def test_emulate_viewport_sends_metrics_and_touch_configuration() -> None:
    client = FakeDevtoolsClient()
    viewport = CdpViewportManager(client)

    reload_needed = await viewport.emulate_viewport(
        {
            "width": 390,
            "height": 844,
            "isMobile": True,
            "hasTouch": True,
            "isLandscape": True,
            "deviceScaleFactor": 3,
        }
    )

    assert reload_needed is True
    assert client.calls == [
        (
            EMULATION_OVERRIDE_METRICS,
            {
                "mobile": True,
                "width": 390,
                "height": 844,
                "deviceScaleFactor": 3,
                "screenOrientation": {
                    "angle": 90,
                    "type": "landscapePrimary",
                },
            },
        ),
        (
            EMULATION_ENABLE_TOUCH,
            {"enabled": True, "configuration": "mobile"},
        ),
    ]

    assert (
        await viewport.emulate_viewport({"isMobile": True, "hasTouch": True})
        is False
    )


@pytest.mark.parametrize("axis", ["width", "height"])
async def test_emulate_viewport_rejects_invalid_dimensions(axis: str) -> None:
    viewport = CdpViewportManager(FakeDevtoolsClient())

    with pytest.raises(TypeError, match="positive integers"):
        await viewport.emulate_viewport({axis: "wide"})
