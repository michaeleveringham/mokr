from __future__ import annotations

from typing import Any

from mokr.bidi.connection import BidiSession


class BidiDialog:
    """Represent an alert, confirmation, prompt, or before-unload dialog."""

    def __init__(self, session: BidiSession, event: dict[str, Any]) -> None:
        """Create a dialog from a BiDi ``userPromptOpened`` event.

        Args:
            session: Remote BiDi session used to handle the prompt.
            event: Prompt event payload.
        """
        self._session = session
        self._context_id = event["context"]
        self._type = event.get("type", "")
        self._message = event.get("message", "")
        self._default_value = event.get("defaultValue", "")

    @property
    def kind(self) -> str:
        """Return the dialog kind, such as ``alert`` or ``prompt``."""
        return self._type

    @property
    def message(self) -> str:
        """Return the dialog message."""
        return self._message

    @property
    def default_value(self) -> str:
        """Return the default prompt value, if supplied."""
        return self._default_value

    async def accept(self, prompt_text: str = "") -> None:
        """Accept this dialog, optionally supplying prompt text.

        Args:
            prompt_text: Text submitted when this is a prompt dialog.
        """
        await self._session.handle_user_prompt(
            self._context_id, True, prompt_text
        )

    async def dismiss(self) -> None:
        """Dismiss this dialog."""
        await self._session.handle_user_prompt(self._context_id, False)
