import asyncio
import logging
from typing import Literal

from mokr.browser import Browser
from mokr.connection import Connection
from mokr.constants import BROWSER_CLOSE, MOKR_VERSION, TARGET_GET_CONTEXTS
from mokr.launch import ChromeLauncher, FirefoxLauncher
from mokr.utils import get_ws_endpoint


version = MOKR_VERSION
version_info = tuple(int(i) for i in version.split('.'))


def launch(
    browser_type: Literal["chrome", "firefox"] = "chrome",
    binary_path: str = None,
    headless: bool = None,
    user_data_dir: str = None,
    devtools: bool = False,
    ignore_default_args: bool | list[str] = False,
    ignore_https_errors: bool = False,
    default_viewport: dict[str, int] = None,
    proxy: str = None,
    default_user_agent: str = None,
    slow_mo: int = 0,
    log_level: str | int = None,
    args: list[str] = None,
    dumpio: bool = False,
    env: dict[str, str] = None,
    loop: asyncio.AbstractEventLoop = None,
    firefox_user_prefs: dict = None,
    firefox_addons_paths: list[str] = None,
) -> Browser:
    """
    Launch a browser process and create a `mokr.browser.Browser`.
    Wrapper for `mokr.launch.Launcher.launch`.

    Args:
        browser_type (Literal["chrome", "firefox"]): The type of browser to,
            use. One of "chrome" or "firefox". Note that Firefox is not fully
            implemented and only offers partial functionality.
        binary_path (str, optional): Path to executable to use.
            Defaults to None (looks for default executable that can be installed
            via `mokr install`).
        headless (bool, optional): Run the browser in headless (no window) mode.
            Defaults to None (uses opposite value to `devtools`).
        user_data_dir (str, optional): Path to a user data directory.
            Defaults to None.
        devtools (bool, optional): Automatically open the developer tools panel.
            Defaults to False.
        ignore_default_args (bool | list[str], optional): Either a bool to
            indicate ignoring all arguments or a list of arguments to
            ignore.
            Be cautious, ignoring some arguments may cause unexpected results.
            Defaults to False.
        ignore_https_errors (bool, optional): Ignore site security errors.
            Defaults to False.
        default_viewport (dict[str, int], optional): Set the default viewport
            for new pages. Accepts a dictionary keyed with viewport options.
            Not all viewport options are considered, only: "isMobile", "width",
            "height", "deviceScaleFactor", "isLandscape", and "hasTouch".
            Defaults to None (800x600 viewport).
        proxy (str, optional): Proxy to route all requests through. Can
            be a regular HTTP/S proxy or SOCKS proxy. Expects proxy as
            `<scheme>://[(optional)<username>:<password>]@<host><password>`.
        default_user_agent (str, optional): Default user agent to use on
            all new pages.
        slow_mo (int, optional): Slow execution of remote calls by the given
            time in milliseconds. Defaults to 0.
        log_level (str | int, optional): Log level to log at.
            Defaults to None (same as root).
        args (list[str], optional): Additional arguments to pass to the
            browser process when launching. Defaults to None.
        dumpio (bool, optional): Pipe the browser process' stdout and stderr
            into ``process.stdout`` and ``process.stderr``. Defaults to False.
        env (dict[str, str], optional): Additional environment variables that
            the browser process will be able to read. Defaults to None.
        loop (asyncio.AbstractEventLoop, optional): A running asyncio loop
            to execute within. Defaults to None (uses `asyncio.get_event_loop`).
        firefox_user_prefs (dict): Firefox only. User preferences to load.
        firefox_addons_paths (list[str]): Firefox only. A list of paths to
            addons that will be installed as temporary extensions.

    Example::

        ```python
        from mokr import launch

        async with launch() as browser:
            page = await browser.first_page()
            await page.goto("https://example.com")

        # Or, to avoid the contextmanager.
        launcher = launch()
        browser = await launcher.launch()
        page = await browser.first_page()
        await page.goto("https://example.com")
        await launcher.stop()
        ```

    Raises:
        ValueError: Raised if `browser_type` isn't of "chrome" or "firefox".

    Returns:
        Browser: A newly created `mokr.browser.Browser` instance.
    """
    launcher_classes = {
        "chrome": ChromeLauncher,
        "firefox": FirefoxLauncher,
    }
    launcher_class = launcher_classes.get(browser_type.lower())
    if not launcher_class:
        raise ValueError(f"Invalid browser type given: {browser_type}")
    return launcher_class(
        binary_path,
        headless,
        user_data_dir,
        devtools,
        ignore_default_args,
        ignore_https_errors,
        default_viewport,
        proxy,
        default_user_agent,
        slow_mo,
        log_level,
        args,
        dumpio,
        env,
        loop,
        firefox_user_prefs,
        firefox_addons_paths,
    )


async def connect(
    browser_type: Literal["chrome", "firefox"] = "chrome",
    browser_ws_endpoint: str = None,
    browser_url: str = None,
    ignore_https_errors: bool = False,
    default_viewport: dict[str, int] = None,
    slow_mo: int = 0,
    log_level: str | int = None,
    loop: asyncio.AbstractEventLoop = None,
) -> Browser:
    """
    Connect to an existing running browser.

    Args:
        browser_type (Literal["chrome", "firefox"]): The type of browser to
            connect to. One of "chrome" or "firefox". Note that Firefox is not
            fully implemented and only offers partial functionality.
        browser_ws_endpoint (str, optional): An existing browser websocket
            endpoint to connect to. Should be formated like
            `"ws://${host}:${port}/devtools/browser/<id>"`.
            Defaults to None, if not given, must give `browser_url`.
        browser_url (str, optional): An existing browser URL to connect to and
            get the websocket URL from.  Should follow format of
            "http://${host}:${port}".
            Defaults to None, if not given, must give `browser_ws_endpoint`.
        ignore_https_errors (bool, optional): Ignore site security errors.
            Defaults to False.
        default_viewport (dict[str, int], optional): Set the default viewport
            for new pages. Accepts a dictionary keyed with viewport options.
            Not all viewport options are considered, only: "isMobile", "width",
            "height", "deviceScaleFactor", "isLandscape", and "hasTouch".
            Defaults to None (800x600 viewport).
        slow_mo (int, optional): Slow execution of remote calls by the given
            time in milliseconds. Defaults to 0.
        log_level (str | int, optional): Log level to log at.
            Defaults to None (same as root).
        loop (asyncio.AbstractEventLoop, optional): A running asyncio loop
            to execute within. Defaults to None (uses `asyncio.get_event_loop`).

    Raises:
        ValueError: Raised if `browser_type` isn't of "chrome" or "firefox" or
            neither `browser_ws_endpoint` nor `browser_url` are given.

    Returns:
        Browser: A newly created `mokr.browser.Browser` instance.
    """
    if log_level is not None:
        logging.getLogger('mokr').setLevel(log_level)
    if browser_type not in ("chrome", "firefox"):
        raise ValueError(f"Invalid browser type given: {browser_type}")
    if not browser_ws_endpoint:
        if not browser_url:
            raise ValueError(
                'Must give one of browser_ws_endpoint or browser_url.'
            )
        browser_ws_endpoint = get_ws_endpoint(browser_url)
    connection = Connection(
        browser_ws_endpoint,
        loop if loop else asyncio.get_event_loop(),
        slow_mo,
    )
    browser_context_ids = (
        await connection.send(TARGET_GET_CONTEXTS)
    ).get('browserContextIds', [])
    default_viewport = (
        default_viewport if default_viewport
        else {'width': 800, 'height': 600}
    )
    browser = Browser(
        browser_type,
        connection,
        browser_context_ids,
        ignore_https_errors,
        default_viewport,
        None,
        lambda: connection.send(BROWSER_CLOSE),
    )
    await browser.start()
    return browser
