import json
import logging
from queue import Empty, Queue
import re
import socket
from threading import Thread
import time
from http.client import HTTPException
from urllib.error import URLError
from urllib.request import urlopen

from mokr.exceptions import BrowserError

LOGGER = logging.getLogger(__name__)

BIDI_ENDPOINT_PATTERN = re.compile(r"WebDriver BiDi listening on (ws://[^\s]+)")


def get_ws_endpoint(url: str) -> str:
    """
    Get the websocket URL for the remote browser at `url`.

    Args:
        url (str): Remote browser URL.

    Raises:
        BrowserError: Raised if browser closes while trying to resolve.

    Returns:
        str: Websocket URL from `<url>/json/version` response.
    """
    url = url + "/json/version"
    timeout = time.time() + 30
    while True:
        if time.time() > timeout:
            raise BrowserError("Browser closed unexpectedly:\n")
        try:
            with urlopen(url) as f:
                data = json.loads(f.read().decode())
            break
        except (URLError, HTTPException):
            pass
        time.sleep(0.1)
    return data["webSocketDebuggerUrl"]


def get_bidi_ws_endpoint(
    process: "subprocess.Popen[bytes]",  # type: ignore[type-arg]
    fallback_endpoint: str | None = None,
    timeout: float = 30,
) -> str:
    """
    Read Firefox's WebDriver BiDi endpoint from process output.

    Args:
        process (subprocess.Popen[bytes]): The Firefox process to read output from.
        fallback_endpoint (str | None): Optional fallback BiDi endpoint to use
            if the process output does not contain a BiDi endpoint.
        timeout (float): Maximum time to wait for the BiDi endpoint.

    Raises:
        BrowserError: Raised if the process closes or the BiDi endpoint is not
            found within the timeout period.

    Returns:
        str: The WebDriver BiDi endpoint URL.
    """
    if process.stdout is None:
        raise BrowserError("Firefox output is unavailable for BiDi discovery.")
    lines: Queue[str] = Queue()
    output: list[str] = []
    fallback_address: tuple[str, int] | None = None
    if fallback_endpoint:
        match = re.match(r"ws://([^:/]+):(\d+)/", fallback_endpoint)
        if not match:
            raise ValueError(
                f"Invalid BiDi fallback endpoint: {fallback_endpoint}"
            )
        fallback_address = (match.group(1), int(match.group(2)))

    def read_output() -> None:
        for line in iter(process.stdout.readline, ""):
            lines.put(line)

    Thread(target=read_output, daemon=True).start()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if fallback_address:
            try:
                with socket.create_connection(fallback_address, timeout=0.05):
                    return fallback_endpoint
            except OSError:
                pass
        try:
            line = lines.get(timeout=0.1)
        except Empty:
            if process.poll() is not None and not fallback_endpoint:
                while not lines.empty():
                    output.append(lines.get_nowait())
                details = "".join(output).strip()
                message = "Firefox closed while starting BiDi."
                if details:
                    message = f"{message}\nFirefox output:\n{details}"
                raise BrowserError(message)
            continue
        output.append(line)
        match = BIDI_ENDPOINT_PATTERN.search(line)
        if match:
            endpoint = match.group(1).rstrip("/")
            return f"{endpoint}/session"
    details = "".join(output).strip()
    message = "Timed out waiting for Firefox WebDriver BiDi endpoint."
    if details:
        message = f"{message}\nFirefox output:\n{details}"
    raise BrowserError(message)
