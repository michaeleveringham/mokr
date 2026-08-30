from __future__ import annotations

from typing import Literal

from mokr.bidi.connection import BidiSession


class BidiMouse:
    """Emulate mouse movement and clicks through WebDriver BiDi actions.

    The remote position is measured in pixels, with origin at the top-left
    corner of the viewport. Mokr tracks the last successfully dispatched
    position because BiDi does not expose a pointer-position query.
    """

    def __init__(self, session: BidiSession, context_id: str) -> None:
        """
        Args:
            session: Remote BiDi session used to perform input actions.
            context_id: Browsing context that receives mouse events.
        """
        self._session = session
        self._context_id = context_id
        self._x = 0.0
        self._y = 0.0

    async def move(self, x: float, y: float, steps: int = 1) -> None:
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
        actions = []
        for step in range(1, steps + 1):
            actions.append(
                {
                    "type": "pointerMove",
                    "x": round(start_x + (x - start_x) * (step / steps)),
                    "y": round(start_y + (y - start_y) * (step / steps)),
                    "origin": "viewport",
                    "duration": 0,
                }
            )
        await self._perform(actions)
        self._x = x
        self._y = y

    async def click(
        self,
        x: float | None = None,
        y: float | None = None,
        button: Literal["left", "right", "middle"] = "left",
        click_count: int = 1,
        delay: int = 0,
    ) -> None:
        """
        Click at the target coordinates or at the current pointer position.

        Args:
            x (float | None, optional): X coordinate to move to. Must be
                supplied with `y`; omit both to use the current position.
            y (float | None, optional): Y coordinate to move to. Must be
                supplied with `x`; omit both to use the current position.
            button (Literal["left", "right", "middle"], optional): Mouse
                button to click with. Defaults to "left".
            click_count (int, optional): Number of clicks to run. Defaults to 1.
            delay (int, optional): Time in milliseconds to wait before each
                click. Defaults to 0.

        Raises:
            ValueError: If only one coordinate is supplied or `button` is not
                supported.
        """
        if (x is None) != (y is None):
            raise ValueError(
                "Mouse click coordinates must include both x and y."
            )
        buttons = {"left": 0, "middle": 1, "right": 2}
        if button not in buttons:
            raise ValueError(f"Unsupported mouse button: {button}")
        target_x = self._x if x is None else x
        target_y = self._y if y is None else y
        actions: list[dict] = [
            {
                "type": "pointerMove",
                "x": target_x,
                "y": target_y,
                "origin": "viewport",
                "duration": 0,
            }
        ]
        for _ in range(click_count):
            actions.append({"type": "pointerDown", "button": buttons[button]})
            if delay:
                actions.append({"type": "pause", "duration": delay})
            actions.append({"type": "pointerUp", "button": buttons[button]})
        await self._perform(actions)
        self._x = target_x
        self._y = target_y

    async def _perform(self, actions: list[dict]) -> None:
        await self._session.perform_actions(
            self._context_id,
            [
                {
                    "type": "pointer",
                    "id": "mokr-mouse",
                    "parameters": {"pointerType": "mouse"},
                    "actions": actions,
                }
            ],
        )
