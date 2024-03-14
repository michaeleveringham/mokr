from __future__ import annotations

from mokr.connection.connection import DevtoolsConnection
from mokr.constants import EMULATION_ENABLE_TOUCH, EMULATION_OVERRIDE_METRICS


class ViewportManager():
    def __init__(self, client: DevtoolsConnection) -> None:
        """
        Handler for adjusting the browser viewport. Can adjust size and
        enable functionality such as touchmode.

        Args:
            client (DevtoolsConnection): `mokr.network.DevtoolsConnection`
                object, shared from the parent `mokr.browser.Page`.
        """
        self._client = client
        self._emulating_mobile = False
        self._has_touch = False

    async def emulate_viewport(self, viewport: dict[str, bool | int]) -> bool:
        """
        Run viewport adjustments based off given `viewport` parameters.
        Not all viewport options are considered, only: "isMobile", "width",
        "height", "deviceScaleFactor", "isLandscape", and "hasTouch".

        Args:
            viewport (dict[str, bool  |  int]): The parameters to adjust
                the viewport to.

        Raises:
            TypeError: Raised if "width" or "height" in `viewport` are not
                positive integers.

        Returns:
            bool: True to indicate if a reload of the page is needed to affect
                the changes sent. False if not.
        """
        options = {}
        mobile = viewport.get('isMobile', False)
        options['mobile'] = mobile
        for viewport_axis in ("width", "height"):
            axis_value = viewport.get(viewport_axis)
            if axis_value:
                if not isinstance(axis_value, int) or axis_value < 0:
                    raise TypeError(
                        'Viewport dimensions must be positive integers'
                        f', got: {axis_value} ({type(axis_value)})'
                    )
                options[viewport_axis] = axis_value
        options['deviceScaleFactor'] = viewport.get('deviceScaleFactor', 1)
        if viewport.get('isLandscape'):
            options['screenOrientation'] = {
                'angle': 90,
                'type': 'landscapePrimary',
            }
        else:
            options['screenOrientation'] = {
                'angle': 0,
                'type': 'portraitPrimary',
            }
        has_touch = viewport.get('hasTouch', False)
        await self._client.send(EMULATION_OVERRIDE_METRICS, options)
        await self._client.send(
            EMULATION_ENABLE_TOUCH,
            {
                'enabled': has_touch,
                'configuration': 'mobile' if mobile else 'desktop',
            }
        )
        reload_needed = (
            self._emulating_mobile != mobile or self._has_touch != has_touch
        )
        self._emulating_mobile = mobile
        self._has_touch = has_touch
        return reload_needed
