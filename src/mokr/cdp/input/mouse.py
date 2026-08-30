import asyncio
from typing import Literal

from mokr.cdp.connection import CdpSession
from mokr.constants import INPUT_MOUSE
from mokr.cdp.input.keyboard import CdpKeyboard


class CdpMouse:
    """Emulate mouse movement and clicks through CDP input events.

    The remote position is measured in pixels, with origin at the top-left
    corner of the viewport. Mokr tracks the last successfully requested
    position so coordinate-free clicks can reuse it.
    """

    def __init__(self, client: CdpSession, keyboard: CdpKeyboard) -> None:
        """
        Args:
            client (CdpSession): Remote `CdpSession` instance.
            keyboard (CdpKeyboard): Active `mokr.cdp.input.CdpKeyboard` from the parent
                `mokr.cdp.input.CdpKeyboard`. Passes active modifiers such as CTRL.
        """
        self._client = client
        self._keyboard = keyboard
        self._x = 0.0
        self._y = 0.0
        self._button = "none"

    async def move(
        self,
        x: float,
        y: float,
        steps: int = 1,
    ) -> None:
        """
        Move the mouse to target coordinates (`x`, `y`), sending intermittent
        events along the trail for each step in `steps`.

        Args:
            x (float): Target X coordinate.
            y (float): Target Y coordinate.
            steps (int, optional): Number of times to stop along the path.
                Defaults to 1 (final destination only).

        Raises:
            ValueError: If `steps` is less than one.
        """
        if steps < 1:
            raise ValueError("Mouse movement steps must be at least 1.")
        start_x = self._x
        start_y = self._y
        self._x = x
        self._y = y
        for i in range(1, steps + 1):
            x = round(start_x + (self._x - start_x) * (i / steps))
            y = round(start_y + (self._y - start_y) * (i / steps))
            await self._client.send(
                INPUT_MOUSE,
                {
                    "type": "mouseMoved",
                    "button": self._button,
                    "x": x,
                    "y": y,
                    "modifiers": self._keyboard._modifiers,
                },
            )

    async def down(
        self,
        button: Literal["left", "right", "middle"] = "left",
        click_count: int = 1,
    ) -> None:
        """
        Send a "mousePressed" event with given mouse `button`, repeat for
        `click_count` number of times.

        Args:
            button (Literal["left", "right", "middle"], optional): CdpMouse button
                to send with. Defaults to "left".
            click_count (int, optional): Number of click events to
                send. Defaults to 1.
        """
        self._button = button
        await self._client.send(
            INPUT_MOUSE,
            {
                "type": "mousePressed",
                "button": self._button,
                "x": self._x,
                "y": self._y,
                "modifiers": self._keyboard._modifiers,
                "clickCount": click_count,
            },
        )

    async def up(
        self,
        button: Literal["left", "right", "middle"] = "left",
        click_count: int = 1,
    ) -> None:
        """
        Send a "mouseReleased" event with given mouse `button`, repeat for
        `click_count` number of times.

        Args:
            button (Literal["left", "right", "middle"], optional): CdpMouse button
                to send with. Defaults to "left".
            click_count (int, optional): Number of click events to
                send. Defaults to 1.
        """
        self._button = button
        await self._client.send(
            INPUT_MOUSE,
            {
                "type": "mouseReleased",
                "button": self._button,
                "x": self._x,
                "y": self._y,
                "modifiers": self._keyboard._modifiers,
                "clickCount": click_count,
            },
        )

    async def click(
        self,
        x: float | None = None,
        y: float | None = None,
        button: Literal["left", "right", "middle"] = "left",
        click_count: int = 1,
        delay: int | float | None = 1000,
    ) -> None:
        """
        Click at the target coordinates or at the current pointer position.

        When coordinates are supplied, this is a shortcut to running
        `CdpMouse.move`, `CdpMouse.down`, then `CdpMouse.up`.

        Args:
            x (float | None, optional): X coordinate to move to. Must be
                supplied with `y`; omit both to use the current position.
            y (float | None, optional): Y coordinate to move to. Must be
                supplied with `x`; omit both to use the current position.
            button (Literal["left", "right", "middle"], optional): CdpMouse button
                to click with. Defaults to "left".
            click_count (int, optional): Number of clicks to run. Defaults to 1.
            delay (int | float | None, optional): Time in milliseconds to wait
                before each click. Defaults to 1000.

        Raises:
            ValueError: If only one coordinate is supplied.
        """
        if (x is None) != (y is None):
            raise ValueError(
                "Mouse click coordinates must include both x and y."
            )
        if x is not None and y is not None:
            await self.move(x, y)
        await self.down(button, click_count)
        if delay is not None:
            await asyncio.sleep(delay / 1000)
        await self.up(button, click_count)
