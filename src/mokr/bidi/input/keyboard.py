from __future__ import annotations

from mokr.bidi.connection import BidiSession


class BidiKeyboard:
    """Emulate keyboard input through WebDriver BiDi actions.

    Use :meth:`type_text` to enter text normally or :meth:`press` to send a
    named key with an optional hold delay. Unlike :class:`CdpKeyboard`, BiDi
    encodes keys directly as WebDriver key values and does not expose mokr's
    CDP key-definition table.
    """

    def __init__(self, session: BidiSession, context_id: str) -> None:
        """Create a keyboard controller for a browsing context.

        Args:
            session: Remote BiDi session used to perform input actions.
            context_id: Browsing context that receives keyboard events.
        """
        self._session = session
        self._context_id = context_id

    async def type_text(self, text: str, delay: int = 0) -> None:
        """Type characters into the currently focused element.

        Args:
            text: Text to type.
            delay: Time in milliseconds to wait between characters. Defaults
                to ``0``.
        """
        actions = []
        for character in text:
            actions.extend(
                [
                    {"type": "keyDown", "value": character},
                    {"type": "keyUp", "value": character},
                ]
            )
            if delay:
                actions.append({"type": "pause", "duration": delay})
        await self._perform(actions)

    async def press(self, key: str, delay: int = 0) -> None:
        """Press and release a key with an optional hold delay.

        Args:
            key: Character or WebDriver key value to press.
            delay: Time in milliseconds to hold the key down. Defaults to
                ``0``.
        """
        actions = [{"type": "keyDown", "value": key}]
        if delay:
            actions.append({"type": "pause", "duration": delay})
        actions.append({"type": "keyUp", "value": key})
        await self._perform(actions)

    async def _perform(self, actions: list[dict]) -> None:
        await self._session.perform_actions(
            self._context_id,
            [{"type": "key", "id": "mokr-keyboard", "actions": actions}],
        )
