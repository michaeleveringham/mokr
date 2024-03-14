from mokr.connection import DevtoolsConnection
from mokr.constants import INPUT_TOUCH
from mokr.input.keyboard import Keyboard


class Touchscreen():
    def __init__(
        self,
        client: DevtoolsConnection,
        keyboard: Keyboard,
    ) -> None:
        """
        Class to emulate touchscreen.

        Args:
            client (DevtoolsConnection): Remote `DevtoolsConnection` instance.
            keyboard (Keyboard): Active `mokr.input.Keyboard` from the parent
                `mokr.input.Keyboard`. Passes active modifiers such as CTRL.
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
        touch_points = [{'x': round(x), 'y': round(y)}]
        await self._client.send(
            INPUT_TOUCH,
            {
                'type': 'touchStart',
                'touchPoints': touch_points,
                'modifiers': self._keyboard._modifiers,
            },
        )
        await self._client.send(
            INPUT_TOUCH,
            {
                'type': 'touchEnd',
                'touchPoints': [],
                'modifiers': self._keyboard._modifiers,
            },
        )
