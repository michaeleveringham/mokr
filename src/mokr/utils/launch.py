import json
import logging
import time
from http.client import HTTPException
from urllib.error import URLError
from urllib.request import urlopen

from mokr.exceptions import BrowserError


LOGGER = logging.getLogger(__name__)


def get_ws_endpoint(url) -> str:
    """
    Get the websocket URL for the remote browser at `url`.

    Args:
        url (_type_): Remote browser URL.

    Raises:
        BrowserError: Raised if browser closes while trying to resolve.

    Returns:
        str: Websocket URL from `<url>/json/version` response.
    """
    url = url + '/json/version'
    timeout = time.time() + 30
    while True:
        if time.time() > timeout:
            raise BrowserError('Browser closed unexpectedly:\n')
        try:
            with urlopen(url) as f:
                data = json.loads(f.read().decode())
            break
        except (URLError, HTTPException):
            pass
        time.sleep(0.1)
    return data['webSocketDebuggerUrl']
