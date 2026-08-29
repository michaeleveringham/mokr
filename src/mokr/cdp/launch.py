"""Chrome DevTools Protocol process bootstrap."""

from __future__ import annotations

import subprocess

from mokr.cdp.browser import CdpBrowser, CdpTarget
from mokr.cdp.connection import CdpConnection
from mokr.constants import BROWSER_CLOSE
from mokr.launch.base import Launcher
from mokr.utils import (
    add_event_listener,
    get_ws_endpoint,
    remove_event_listeners,
)


class CdpLauncher(Launcher[CdpBrowser]):
    """Launcher behavior shared by browsers driven through a CDP endpoint."""

    def _initial_page_callback(self) -> None:
        self.initial_page_promise.set_result(True)

    def _check_target(self, target: CdpTarget) -> None:
        if target.kind == "page":
            self._initial_page_callback()

    async def _close_connection(self) -> None:
        if self.connection and self.connection._connected:
            await self.connection.send(BROWSER_CLOSE)
        await super()._close_connection()

    async def launch(self) -> CdpBrowser:
        self.browser_closed = False
        self.connection = None
        options = {"env": self.env}
        if not self.dumpio:
            options["stdout"] = subprocess.DEVNULL
            options["stderr"] = subprocess.STDOUT
        self.proc = subprocess.Popen(self.cmd, **options)
        self.browser_ws_endpoint = get_ws_endpoint(self.url)
        self.connection = CdpConnection(
            self.browser_ws_endpoint,
            self._loop,
            self.slow_mo,
        )
        browser = CdpBrowser(
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

    async def ensure_initial_page(self, browser: CdpBrowser) -> None:
        for target in browser.targets():
            if target.kind == "page":
                return
        listeners = [
            add_event_listener(browser, "targetcreated", self._check_target)
        ]
        await self.initial_page_promise
        remove_event_listeners(listeners)
