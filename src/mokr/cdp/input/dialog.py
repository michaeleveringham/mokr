from mokr.cdp.connection import CdpSession
from mokr.constants import PAGE_HANDLE_DIALOG


class CdpDialog:
    """Represent an alert, confirmation, prompt, or before-unload dialog."""

    def __init__(
        self,
        client: CdpSession,
        dialog_type: str,
        message: str,
        default_value: str | None = None,
    ) -> None:
        """
        CdpDialog objects are initialized by the parent `CdpPage`
        when a dialog event is triggered.

        Args:
            client (CdpSession): A target-scoped CDP session spawned by the
                parent page.
            dialog_type (str): CdpDialog type from the triggering event's type.
            message (str): Message in the dialog.
            default_value (str | None, optional): Default prompt that
                the dialog spawned with. Defaults to None.

        Example::

            async def close_dialog(dialog):
                print(dialog.message)
                await dialog.dismiss()
            page.on("dialog", close_dialog)
        """
        self._client = client
        self._type = dialog_type
        self._message = message
        self._handled = False
        self._default_value = "" if default_value is None else default_value

    @property
    def kind(self) -> str:
        """
        Get the remote `CdpDialog` event type. One of "alert", "beforeunload,
        "confirm", "prompt, or "".
        """
        return self._type

    @property
    def message(self) -> str:
        """Get the message the dialog spawned with."""
        return self._message

    @property
    def default_value(self) -> str:
        """
        Get default prompt value, if remote dialog type is "prompt".
        Otherwise, get "".
        """
        return self._default_value

    async def accept(self, prompt_text: str = "") -> None:
        """
        Accept the remote dialog. Can optionally accept with the given
        `prompt_text`, if `CdpDialog.type` is "prompt".

        Args:
            prompt_text (str, optional): Text submitted when this is a prompt
                dialog. Defaults to ``""``.
        """
        self._handled = True
        await self._client.send(
            PAGE_HANDLE_DIALOG,
            {
                "accept": True,
                "prompt_text": prompt_text,
            },
        )

    async def dismiss(self) -> None:
        """Dismiss the remote dialog."""
        self._handled = True
        await self._client.send(PAGE_HANDLE_DIALOG, {"accept": False})
