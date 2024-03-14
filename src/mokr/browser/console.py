from mokr.execution import JavascriptHandle


class ConsoleMessage():
    def __init__(
        self,
        kind: str,
        text: str,
        args: list[JavascriptHandle] = None
    ) -> None:
        """
        Representation of console messages, dispatched on `console` event in
        `mokr.browser.Page`.

        Args:
            kind (str): The type of message.
            text (str): The message body.
            args (list[JavascriptHandle], optional): Arguments attached to this
                message. Defaults to None.
        """
        self._type = kind
        self._text = text
        self._args = args if args is not None else []

    @property
    def kind(self) -> str:
        """Return type of this message."""
        return self._type

    @property
    def text(self) -> str:
        """Return text representation of the message body."""
        return self._text

    @property
    def args(self) -> list[JavascriptHandle]:
        """Return list of argumentss (JavascriptHandle) of this message."""
        return self._args
