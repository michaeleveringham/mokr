import asyncio
import gc
import logging
import socket
import subprocess
from abc import ABC

from mokr.browser.browser import Browser
from mokr.browser.target import Target
from mokr.connection import Connection
from mokr.constants import BROWSER_CLOSE
from mokr.download import browser_binary, ensure_binary
from mokr.utils import (
    add_event_listener,
    get_ws_endpoint,
    remove_event_listeners,
)


LOGGER = logging.getLogger(__name__)


class Launcher(ABC):
    kind = "abstract"

    def __init__(
        self,
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
    ) -> None:
        """
        Class to handle launching browser process and creation of a
        `mokr.browser.Browser` object.

        Args:
            binary_path (str, optional): Path to executable to use.
                Defaults to None (looks for default executable that can be
                installed via `mokr install`).
            headless (bool, optional): Run the browser in headless (no window)
                mode. Defaults to None (uses opposite value to `devtools`).
            user_data_dir (str, optional): Path to a user data directory.
                Defaults to None.
            devtools (bool, optional): Automatically open the developer tools
                panel. Defaults to False.
            ignore_default_args (bool | list[str], optional): Either a bool to
                indicate ignoring all arguments or a list of arguments to
                ignore. Be cautious, ignoring some arguments may cause
                unexpected results.
                Defaults to False.
            ignore_https_errors (bool, optional): Ignore site security errors.
                Defaults to False.
            default_viewport (dict[str, int], optional): Set the default
                viewport for new pages. Accepts a dictionary keyed with viewport
                options. Not all viewport options are considered, only:
                "isMobile", "width", "height", "deviceScaleFactor",
                "isLandscape", and "hasTouch".
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
                into ``process.stdout`` and ``process.stderr``.
                Defaults to False.
            env (dict[str, str], optional): Additional environment variables
                that the browser process will be able to read. Defaults to None.
            loop (asyncio.AbstractEventLoop, optional): A running asyncio loop
                to execute within. Defaults to None (uses
                `asyncio.get_event_loop`).
            firefox_user_prefs (dict): Firefox only. User preferences to load.
            firefox_addons_paths (list[str]): Firefox only. A list of paths to
                addons that will be installed as temporary extensions.

        Example::

            ```python
            from mokr.launch import ChromeLauncher, FirefoxLauncher

            async with ChromeLauncher() as browser:
                page = await browser.first_page()
                await page.goto("https://example.com")

            # Or, to avoid the contextmanager.
            launcher = FirefoxLauncher()
            browser = await launcher.launch()
            page = await browser.first_page()
            await page.goto("https://example.com")
            await launcher.stop()
            ```
        """
        self.port = self._get_free_port()
        self.url = f'http://127.0.0.1:{self.port}'
        self._loop = loop if loop else asyncio.get_event_loop()
        self.dumpio = dumpio
        self.env = env
        self.ignore_https_errors = ignore_https_errors
        self.default_viewport = (
            default_viewport if default_viewport
            else {'width': 800, 'height': 600}
        )
        self.default_user_agent = default_user_agent
        self.slow_mo = slow_mo
        self.firefox_user_prefs = firefox_user_prefs
        self.firefox_addons_paths = firefox_addons_paths
        if log_level is not None:
            logging.getLogger('mokr').setLevel(log_level)
        self.browser_closed = True
        self.browser_arguments: list[str] = list()
        args = args if args else []
        self._compute_launch_args(
            headless,
            user_data_dir,
            devtools,
            ignore_default_args,
            proxy,
            args,
        )
        self.browser_binary = binary_path
        browser_type = getattr(self, "kind", "")
        if not self.browser_binary:
            binary = str(browser_binary(browser_type))
            if not ensure_binary(browser_type):
                self._print_needs_install_message(binary)
            self.browser_binary = binary
        self.cmd = [self.browser_binary] + self.browser_arguments
        self.initial_page_promise = self._loop.create_future()

    async def __aenter__(self, *args, **kwargs) -> Browser:
        browser = await self.launch()
        return browser

    async def __aexit__(self, *args, **kwargs) -> None:
        await self.stop()

    def _default_args(
        self,
        headless: bool = None,
        args: list[str] = None,
        user_data_dir: str = None,
        devtools: bool = False,
    ) -> list[str]:
        if headless is None:
            headless = not devtools
        args = args if args else []
        browser_arguments = self._custom_default_args(
            headless,
            user_data_dir,
            devtools,
        )
        browser_arguments.extend(args)
        if all(arg.startswith("-") for arg in args):
            browser_arguments.append('about:blank')
        return browser_arguments

    def _compute_launch_args(
        self,
        headless: bool = None,
        user_data_dir: str = None,
        devtools: bool = False,
        ignore_default_args: bool | list[str] = False,
        proxy: str = None,
        args: list[str] = None,
    ) -> None:
        if not ignore_default_args:
            self.browser_arguments.extend(
                self._default_args(headless, args, user_data_dir, devtools)
            )
        elif isinstance(ignore_default_args, list):
            self.browser_arguments.extend(
                filter(
                    lambda arg: arg not in ignore_default_args,
                    self._default_args(headless, args, user_data_dir, devtools)
                )
            )
        else:
            self.browser_arguments.extend(args)

    @staticmethod
    def _print_needs_install_message(binary: str) -> None:
        install_error = (
            f"Failed to find browser binary at {binary}\n"
            f'\n\t{"*" * 53}'
            "\n\t* Please install binary via \"mokr install\" or       *"
            "\n\t* specify the target binary path via \"binary_path\"  *"
            "\n\t* in the \"launch\" command.                          *"
            "\n\t*                                       >>>✈        *"
            f'\n\t{"*" * 53}'
        )
        raise FileNotFoundError(install_error)

    def _parse_proxy(self, proxy: str) -> None:
        raise NotImplementedError

    def _get_free_port(self) -> int:
        sock = socket.socket()
        sock.bind(('localhost', 0))
        port = sock.getsockname()[1]
        sock.close()
        del sock
        gc.collect()
        return port

    async def stop(self) -> None:
        """Stop the browser process if it is running."""
        if not self.browser_closed:
            await self.kill_browser()

    def _initial_page_callback(self) -> None:
        self.initial_page_promise.set_result(True)

    def _check_target(self, target: Target) -> None:
        if target.kind == 'page':
            self._initial_page_callback()

    async def launch(self) -> Browser:
        """Start browser process and return a `mokr.browser.Browser` object."""
        self.browser_closed = False
        self.connection = None
        options = {}
        options['env'] = self.env
        if not self.dumpio:
            options['stdout'] = subprocess.DEVNULL
            options['stderr'] = subprocess.STDOUT
        self.proc = subprocess.Popen(self.cmd, **options)
        self.browser_ws_endpoint = get_ws_endpoint(self.url)
        LOGGER.info(f'Browser listening on: {self.browser_ws_endpoint}')
        self.connection = Connection(
            self.browser_ws_endpoint,
            self._loop,
            self.slow_mo,
        )
        browser = Browser(
            self.kind,
            self.connection,
            [],
            self.ignore_https_errors,
            self.default_viewport,
            self.proc,
            self.kill_browser,
            self.proxy_credentials,
            self.default_user_agent,
        )
        await browser.ready()
        await self.ensure_initial_page(browser)
        return browser

    def _wait_for_browser_close(self) -> None:
        if self.proc.poll() is None and not self.browser_closed:
            self.browser_closed = True
            try:
                self.proc.terminate()
                self.proc.wait()
            except Exception:
                # Browser process may be already closed.
                pass

    async def ensure_initial_page(self, browser: Browser) -> None:
        """
        Wait for a new page in a given `browser` to be created.

        Args:
            browser (Browser): Target `mokr.browser.Browser`.
        """
        for target in browser.targets():
            if target.kind == 'page':
                return
        listeners = [
            add_event_listener(browser, 'targetcreated', self._check_target)
        ]
        await self.initial_page_promise
        remove_event_listeners(listeners)

    async def kill_browser(self) -> None:
        """Kill running browser process."""
        LOGGER.info('Killing browser process...')
        if self.connection and self.connection._connected:
            try:
                await self.connection.send(BROWSER_CLOSE)
                await self.connection.dispose()
            except Exception:
                LOGGER.warning("Ignored error killing browser.", exc_info=True)
        self._wait_for_browser_close()
        self._clean_restore_data_dirs()
