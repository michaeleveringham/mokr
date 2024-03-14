from mokr.connection import DevtoolsConnection
from mokr.constants import PAGE_HANDLE_DIALOG


class Dialog():
    def __init__(
        self,
        client: DevtoolsConnection,
        dialog_type: str,
        message: str,
        default_value: str | None = None,
    ) -> None:
        """
        Dialog objects are initialised by the parent `mokr.browser.Page`
        when a dialog event is triggered.

        Args:
            client (DevtoolsConnection): A `mokr.connection.DevtoolsConnection`
                spawned by the parent `mokr.browser.Page`.
            dialog_type (str): Dialog type from the triggering event's type.
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
        self._default_value = '' if default_value is None else default_value

    @property
    def kind(self) -> str:
        """
        Get the remote `Dialog` event type. One of "alert", "beforeunload,
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

    async def accept(self, prompt_text: str = '') -> None:
        """
        Accept the remote dialog. Can optionally accept with the given
        `prompt_text`, if `Dialog.type` is "prompt".

        Args:
            prompt_text (str, optional): _description_. Defaults to ''.
        """
        self._handled = True
        await self._client.send(
            PAGE_HANDLE_DIALOG,
            {
                'accept': True,
                'prompt_text': prompt_text,
            }
        )

    async def dismiss(self) -> None:
        """Dismiss the remote dialog."""
        self._handled = True
        await self._client.send(
            PAGE_HANDLE_DIALOG,
            {'accept': False}
        )
