from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse

from mokr.bidi import BidiConnection, BidiSession, FirefoxBrowser
from mokr.constants import INSTALL_PATH
from mokr.launch.base import Launcher
from mokr.utils import get_bidi_ws_endpoint

CHROME_PROFILE_PATH = INSTALL_PATH / ".dev_profile"
LOGGER = logging.getLogger(__name__)

# Some of these comments
DEFAULT_FIREFOX_USER_PREFS = {
    # Make sure Shield doesn't hit the network.
    "app.normandy.api_url": "",
    # Disable Firefox old build background check
    "app.update.checkInstallTime": False,
    # Disable automatically upgrading Firefox
    "app.update.disabledForTesting": True,
    # Increase the APZ content response timeout to 1 minute
    "apz.content_response_timeout": 60000,
    # Prevent various error message on the console
    # jest-puppeteer asserts that no error message is emitted by the console
    "browser.contentblocking.features.standard": "-tp,tpPrivate,cookieBehavior0,-cm,-fp",
    # Enable the dump function: which sends messages to the system
    # console
    # https://bugzilla.mozilla.org/show_bug.cgi?id=1543115
    "browser.dom.window.dump.enabled": True,
    # Disable topstories
    "browser.newtabpage.activity-stream.feeds.system.topstories": False,
    # Always display a blank page
    "browser.newtabpage.enabled": False,
    # Background thumbnails in particular cause grief: and disabling
    # thumbnails in general cannot hurt
    "browser.pagethumbnails.capturing_disabled": True,
    # Disable safebrowsing components.
    "browser.safebrowsing.blockedURIs.enabled": False,
    "browser.safebrowsing.downloads.enabled": False,
    "browser.safebrowsing.malware.enabled": False,
    "browser.safebrowsing.phishing.enabled": False,
    # Disable updates to search engines.
    "browser.search.update": False,
    # Do not restore the last open set of tabs if the browser has crashed
    "browser.sessionstore.resume_from_crash": False,
    # Skip check for default browser on startup
    "browser.shell.checkDefaultBrowser": False,
    # Disable newtabpage
    "browser.startup.homepage": "about:blank",
    # Do not redirect user when a milstone upgrade of Firefox is detected
    "browser.startup.homepage_override.mstone": "ignore",
    # Start with a blank page about:blank
    "browser.startup.page": 0,
    # Do not allow background tabs to be zombified on Android: otherwise for
    # tests that open additional tabs: the test harness tab itself might get
    # unloaded
    "browser.tabs.disableBackgroundZombification": False,
    # Do not warn when closing all other open tabs
    "browser.tabs.warnOnCloseOtherTabs": False,
    # Do not warn when multiple tabs will be opened
    "browser.tabs.warnOnOpen": False,
    # Do not automatically offer translations, as tests do not expect this.
    "browser.translations.automaticallyPopup": False,
    # Disable the UI tour.
    "browser.uitour.enabled": False,
    # Turn off search suggestions in the location bar so as not to trigger
    # network connections.
    "browser.urlbar.suggest.searches": False,
    # Disable first run splash page on Windows 10
    "browser.usedOnWindows10.introURL": "",
    # Do not warn on quitting Firefox
    "browser.warnOnQuit": False,
    # Defensively disable data reporting systems
    "datareporting.healthreport.documentServerURI": "http://dummy.test/dummy/healthreport/",  # noqa
    "datareporting.healthreport.logging.consoleEnabled": False,
    "datareporting.healthreport.service.enabled": False,
    "datareporting.healthreport.service.firstRun": False,
    "datareporting.healthreport.uploadEnabled": False,
    # Do not show datareporting policy notifications
    "datareporting.policy.dataSubmissionEnabled": False,
    "datareporting.policy.dataSubmissionPolicyBypassNotification": True,
    # DevTools JSONViewer sometimes fails to load dependencies with require.js.
    # This doesn't affect Puppeteer but spams console (Bug 1424372)
    "devtools.jsonview.enabled": False,
    # Disable popup-blocker
    "dom.disable_open_during_load": False,
    # Enable the support for File object creation in the content process
    # Required for |Page.setFileInputFiles| protocol method.
    "dom.file.createInChild": True,
    # Disable the ProcessHangMonitor
    "dom.ipc.reportProcessHangs": False,
    # Disable slow script dialogues
    "dom.max_chrome_script_run_time": 0,
    "dom.max_script_run_time": 0,
    # Only load extensions from the application and user profile
    # AddonManager.SCOPE_PROFILE + AddonManager.SCOPE_APPLICATION
    "extensions.autoDisableScopes": 0,
    "extensions.enabledScopes": 5,
    # Disable metadata caching for installed add-ons by default
    "extensions.getAddons.cache.enabled": False,
    # Disable installing any distribution extensions or add-ons.
    "extensions.installDistroAddons": False,
    # Disabled screenshots extension
    "extensions.screenshots.disabled": True,
    # Turn off extension updates so they do not bother tests
    "extensions.update.enabled": False,
    # Turn off extension updates so they do not bother tests
    "extensions.update.notifyUser": False,
    # Make sure opening about:addons will not hit the network
    "extensions.webservice.discoverURL": "http://dummy.test/dummy/discoveryURL",
    # Allow the application to have focus even it runs in the background
    "focusmanager.testmode": True,
    # Disable useragent updates
    "general.useragent.updates.enabled": False,
    # Always use network provider for geolocation tests so we bypass the
    # macOS dialog raised by the corelocation provider
    "geo.provider.testing": True,
    # Do not scan Wifi
    "geo.wifi.scan": False,
    # No hang monitor
    "hangmonitor.timeout": 0,
    # Show chrome errors and warnings in the error console
    "javascript.options.showInConsole": True,
    # Disable download and usage of OpenH264: and Widevine plugins
    "media.gmp-manager.updateEnabled": False,
    # Disable the GFX sanity window
    "media.sanity-test.disabled": True,
    # Disable experimental feature that is only available in Nightly
    "network.cookie.sameSite.laxByDefault": False,
    # Do not prompt for temporary redirects
    "network.http.prompt-temp-redirect": False,
    # Disable speculative connections so they are not reported as leaking
    # when they are hanging around
    "network.http.speculative-parallel-limit": 0,
    # Do not automatically switch between offline and online
    "network.manage-offline-status": False,
    # Make sure SNTP requests do not hit the network
    "network.sntp.pools": "dummy.test",
    # Disable Flash.
    "plugin.state.flash": 0,
    "privacy.trackingprotection.enabled": False,
    # Can be removed once Firefox 89 is no longer supported
    # https://bugzilla.mozilla.org/show_bug.cgi?id=1710839
    "remote.enabled": True,
    # Don't do network connections for mitm priming
    "security.certerrors.mitm.priming.enabled": False,
    # Local documents have access to all other local documents,
    # including directory listings
    "security.fileuri.strict_origin_policy": False,
    # Do not wait for the notification button security delay
    "security.notification_enable_delay": 0,
    # Ensure blocklist updates do not hit the network
    "services.settings.server": "http://dummy.test/dummy/blocklist/",
    # Do not automatically fill sign-in forms with known usernames and
    # passwords
    "signon.autofillForms": False,
    # Disable password capture, so that tests that include forms are not
    # influenced by the presence of the persistent doorhanger notification
    "signon.rememberSignons": False,
    # Disable first-run welcome page
    "startup.homepage_welcome_url": "about:blank",
    # Disable first-run welcome page
    "startup.homepage_welcome_url.additional": "",
    # Disable browser animations (tabs, fullscreen, sliding alerts)
    "toolkit.cosmeticAnimations.enabled": False,
    # Prevent starting into safe mode after application crashes
    "toolkit.startup.max_resumed_crashes": -1,
    # Do not close the window when the last tab gets closed
    "browser.tabs.closeWindowWithLastTab": False,
    # Prevent various error message on the console
    # jest-puppeteer asserts that no error message is emitted by the console
    "network.cookie.cookieBehavior": 0,
    # Temporarily force disable BFCache in parent (https://bit.ly/bug-1732263)
    "fission.bfcacheInParent": False,
    # Force all web content to use a single content process. TODO: remove
    # this once Firefox supports mouse event dispatch from the main frame
    # context. Once this happens, webContentIsolationStrategy should only
    # be set for CDP. See
    # https://bugzilla.mozilla.org/show_bug.cgi?id=1773393
    "fission.webContentIsolationStrategy": 0,
    # Disable safe-mode on crashes.
    "browser.sessionstore.max_resumed_crashes": 0,
    "browser.sessionstore.restore_on_demand": False,
    "browser.sessionstore.restore_tabs_lazily": False,
    # Set loads of first run / whats new flags.
    "browser.messaging-system.whatsNewPanel.enabled": False,
    "app.normandy.first_run": False,
    "browser.aboutConfig.showWarning": False,
    "browser.aboutwelcome.enabled": False,
    "browser.shell.skipDefaultBrowserCheckOnFirstRun": True,
    "browser.startup.firstrunSkipsHomepage": True,
    "browser.suppress_first_window_animation": True,
    "browser.tabs.warnOnClose": False,
    "devtools.webconsole.timestampMessages": True,
    "doh-rollout.doneFirstRun": True,
    "extensions.formautofill.firstTimeUse": False,
    "pdfjs.firstRun": True,
    "toolkit.telemetry.reportingpolicy.firstRun": False,
    "trailhead.firstrun.branches": "nofirstrun-empty",
    "trailhead.firstrun.didSeeAboutWelcome": True,
}


class FirefoxLauncher(Launcher[FirefoxBrowser]):
    kind = "firefox"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._create_profile()

    def _parse_proxy(self, proxy: str) -> None:
        proxy_parts = urlparse(proxy)
        scheme = proxy_parts.scheme
        host = proxy_parts.hostname
        port = proxy_parts.port
        proxy = f"{scheme}://{host}:{port}"
        credentials = {}
        credentials["proxy"] = proxy
        credentials["host"] = host
        credentials["port"] = port
        if proxy_parts.username:
            credentials["username"] = proxy_parts.username
        if proxy_parts.password:
            credentials["password"] = proxy_parts.password
        return credentials

    def _make_proxy_prefs(self) -> dict:
        prefs = {}
        proxy_data = self.proxy_credentials
        if proxy_data["proxy"].startswith("socks"):
            prefs.update(
                {
                    "network.proxy.socks": proxy_data["host"],
                    "network.proxy.socks_port": proxy_data["port"],
                    "network.proxy.socks_remote_dns": True,
                }
            )
        else:
            prefs.update(
                {
                    "network.proxy.http": proxy_data["host"],
                    "network.proxy.ssl": proxy_data["host"],
                    "network.proxy.http_port": proxy_data["port"],
                    "network.proxy.ssl_port": proxy_data["port"],
                }
            )
        prefs.update(
            {
                "network.proxy.type": 1,
                "network.IDN_show_punycode": True,
                "network.websocket.allowInsecureFromHTTPS": True,
                "network.websocket.auto-follow-http-redirects": True,
            }
        )
        return prefs

    def _create_profile(self):
        # Populates the user.js file with the automation preferences required
        # by the launched Firefox profile. Firefox's current Remote Agent is
        # WebDriver BiDi-only; no CDP preference is needed here.
        extra_prefs = self.firefox_user_prefs if self.firefox_user_prefs else {}
        if not os.path.exists(self.user_data_dir):
            os.mkdir(self.user_data_dir, parents=True)  # recursive: True,
        preferences = DEFAULT_FIREFOX_USER_PREFS.copy()
        preferences.update(extra_prefs)
        if self.proxy_credentials:
            preferences.update(self._make_proxy_prefs())
        lines = [
            f"user_pref({json.dumps(key)}, {json.dumps(value)});"
            for key, value in preferences.items()
        ]
        content = "\n".join(lines)
        with open(os.path.join(self.user_data_dir, "user.js"), "w") as f:
            f.write(content)
        # Create a backup of the preferences file if it already exitsts.
        prefs_path = os.path.join(self.user_data_dir, "prefs.js")
        if os.path.exists(prefs_path):
            prefs_backup_path = os.path.join(
                self.user_data_dir,
                "prefs.js.mokr",
            )
            shutil.copy(prefs_path, prefs_backup_path)

    def _custom_default_args(
        self,
        headless: bool = None,
        user_data_dir: str = None,
        devtools: bool = False,
    ):
        browser_arguments = [
            "-no-remote",
            "-new-instance",
            "-no-default-browser-check",
        ]
        if headless is None:
            headless = not devtools
        if sys.platform == "darwin":
            browser_arguments.append("-foreground")
        if user_data_dir:
            browser_arguments.append("-profile")
            browser_arguments.append(user_data_dir)
        if headless:
            browser_arguments.append("-headless")
        if devtools:
            browser_arguments.append("-devtools")
        return browser_arguments

    def _compute_launch_args(
        self,
        headless: bool = None,
        user_data_dir: str = None,
        devtools: bool = False,
        ignore_default_args: bool | list[str] = False,
        proxy: str = None,
        args: list[str] = None,
    ):
        super()._compute_launch_args(
            headless=headless,
            user_data_dir=user_data_dir,
            devtools=devtools,
            ignore_default_args=ignore_default_args,
            proxy=proxy,
            args=args,
        )
        self.browser_arguments.append(f"--remote-debugging-port={self.port}")
        self.proxy_credentials = self._parse_proxy(proxy) if proxy else None
        # Check for the profile argument, which will always be set even
        # with a custom directory specified via the user_data_dir option.
        profile_arg_index = next(
            (
                index
                for index, arg in enumerate(self.browser_arguments)
                if arg in ["-profile", "--profile"]
            ),
            None,
        )
        if profile_arg_index is not None:
            data_dir = self.browser_arguments[profile_arg_index + 1]
            if not data_dir or not os.path.exists(data_dir):
                raise ValueError(f"Firefox profile not found at '{data_dir}'")
            # When using a custom Firefox profile it needs to be populated
            # with required preferences.
            self.user_data_dir = data_dir
            self.temp_user_data_dir = None
        else:
            data_dir = tempfile.mkdtemp("mokr_dev_firefox_profile-")
            self.browser_arguments.append("--profile")
            self.browser_arguments.append(data_dir)
            self.temp_user_data_dir = self.user_data_dir = data_dir

    def _clean_restore_data_dirs(self) -> None:
        prefs_backup_path = os.path.join(self.user_data_dir, "prefs.js.mokr")
        # Firefox can keep the profile lock briefly after ``browser.close``
        # has answered, especially on Windows. Wait long enough for its child
        # processes to release it before treating cleanup as a failure.
        for _ in range(500):
            if self.temp_user_data_dir and os.path.exists(
                self.temp_user_data_dir
            ):
                shutil.rmtree(self.temp_user_data_dir, ignore_errors=True)
                if os.path.exists(self.temp_user_data_dir):
                    time.sleep(0.01)
            elif not self.temp_user_data_dir:
                # When an existing user profile has been used remove the user
                # preferences file and restore possibly backuped preferences.
                if not os.path.exists(prefs_backup_path):
                    return
                try:
                    os.unlink(os.path.join(self.user_data_dir, "user.js"))
                    if os.path.exists(prefs_backup_path):
                        prefs_path = os.path.join(
                            self.user_data_dir,
                            "prefs.js",
                        )
                        os.unlink(prefs_path)
                        os.rename(prefs_backup_path, prefs_path)
                except Exception:
                    pass
            else:
                return
        else:
            error = (
                "Unable to remove temporary user data dir"
                f" at {self.temp_user_data_dir}"
            )
            if self.temp_user_data_dir:
                raise IOError(error)
            else:
                raise IOError(
                    f"{error} or restore original preferences"
                    f" at {prefs_backup_path}"
                )

    async def launch(self) -> FirefoxBrowser:
        """Launch Firefox and connect to its native WebDriver BiDi endpoint."""
        self.browser_closed = False
        self.connection = None
        options = {"env": self.env}
        # Firefox announces its BiDi WebSocket address on stdout. Capture it
        # even when dumpio is requested so endpoint discovery remains reliable.
        options["stdout"] = subprocess.PIPE
        options["stderr"] = subprocess.STDOUT
        options["text"] = True
        self.proc = subprocess.Popen(self.cmd, **options)
        try:
            self.browser_ws_endpoint = await asyncio.to_thread(
                get_bidi_ws_endpoint,
                self.proc,
                f"ws://127.0.0.1:{self.port}/session",
            )
            self.connection = BidiConnection(
                self.browser_ws_endpoint,
                self._loop,
                create_session=True,
                session_capabilities={
                    "alwaysMatch": {
                        "unhandledPromptBehavior": {"default": "ignore"}
                    }
                },
            )
            await self.connection.start()
            browser = FirefoxBrowser(
                self.kind,
                BidiSession(self.connection),
                self.proc,
                self.kill_browser,
                self.default_viewport,
                self.default_user_agent,
                ignore_https_errors=self.ignore_https_errors,
                proxy_credentials=self.proxy_credentials,
            )
            await browser.ready()
        except Exception:
            await self.kill_browser()
            raise
        if self.proxy_credentials and self.proxy_credentials.get("username"):
            await browser.set_credentials(
                self.proxy_credentials["username"],
                self.proxy_credentials.get("password", ""),
            )
        if self.firefox_addons_paths:
            for addon_path in self.firefox_addons_paths:
                await browser.install_extension(addon_path)
        return browser

    async def kill_browser(self) -> None:
        """Close the native BiDi session, then ensure Firefox has exited."""
        if self.browser_closed:
            return
        self.browser_closed = True
        if self.connection and self.connection.connected:
            try:
                await self.connection.send("browser.close")
            except Exception:
                LOGGER.warning(
                    "Ignored error closing Firefox BiDi.", exc_info=True
                )
            await self.connection.dispose()
        if self.proc and self.proc.poll() is None:
            try:
                await asyncio.to_thread(self.proc.wait, timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.terminate()
                try:
                    await asyncio.to_thread(self.proc.wait, timeout=5)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    await asyncio.to_thread(self.proc.wait)
        self._clean_restore_data_dirs()
