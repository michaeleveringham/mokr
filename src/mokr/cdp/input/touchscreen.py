from mokr.cdp.connection import CdpSession
from mokr.constants import INPUT_TOUCH
from mokr.cdp.input.keyboard import CdpKeyboard


class CdpTouchscreen:
    """Class to emulate touchscreen."""

    def __init__(
        self,
        client: CdpSession,
        keyboard: CdpKeyboard,
    ) -> None:
        """
        Args:
            client (CdpSession): Remote `CdpSession` instance.
            keyboard (CdpKeyboard): Active `mokr.cdp.input.CdpKeyboard` from the parent
                `mokr.cdp.input.CdpKeyboard`. Passes active modifiers such as CTRL.
        """
        self._client = client
        self._keyboard = keyboard

    async def tap(self, x: float, y: float) -> None:
        """
        Send touch down and up events to the center of the target coordinates.

        Args:
            x (float): X coordinate to move to.
            y (float): Y coordinate to move to.
        """
        touch_points = [{"x": round(x), "y": round(y)}]
        await self._client.send(
            INPUT_TOUCH,
            {
                "type": "touchStart",
                "touchPoints": touch_points,
                "modifiers": self._keyboard._modifiers,
            },
        )
        await self._client.send(
            INPUT_TOUCH,
            {
                "type": "touchEnd",
                "touchPoints": [],
                "modifiers": self._keyboard._modifiers,
            },
        )
