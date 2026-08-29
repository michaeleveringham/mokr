from __future__ import annotations

from mokr.bidi.connection import BidiSession


class BidiTouchscreen:
    """Class to emulate touchscreen."""

    def __init__(self, session: BidiSession, context_id: str) -> None:
        """
        Args:
            session (BidiSession): Remote `BidiSession` instance.
            context_id (str): The browsing context ID to send touch events to.
        """
        self._session = session
        self._context_id = context_id

    async def tap(self, x: float, y: float) -> None:
        """
        Send touch down and up events to the center of the target coordinates.

        Args:
            x (float): X coordinate to move to.
            y (float): Y coordinate to move to.
        """
        await self._session.perform_actions(
            self._context_id,
            [
                {
                    "type": "pointer",
                    "id": "mokr-touch-0",
                    "parameters": {"pointerType": "touch"},
                    "actions": [
                        {
                            "type": "pointerMove",
                            "x": x,
                            "y": y,
                            "origin": "viewport",
                        },
                        {"type": "pointerDown", "button": 0},
                        {"type": "pointerUp", "button": 0},
                    ],
                }
            ],
        )
