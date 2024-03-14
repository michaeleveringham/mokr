import asyncio


class MokrTimeoutError(asyncio.TimeoutError):
    """Timeout Error class."""
    pass


class BaseMokrException(Exception):
    """Base exception for mokr."""
    pass


class ElementHandleError(BaseMokrException):
    """ElementHandle related exception."""
    def __init__(
        self,
        message: str = 'Node is either not visible or not an HTMLElement.',
    ) -> None:
        super().__init__(message)


class NetworkError(BaseMokrException):
    """Network/Protocol related exception."""
    pass


class BrowserError(BaseMokrException):
    """Exception raised from browser."""
    pass


class PageError(BrowserError):
    """Page/Frame related exception."""
    pass


class FirefoxNotImplementedError(NotImplementedError):
    """Exception due to Firefox lacking CDP methods."""
    pass
