import os
import shutil
import tempfile
import time
from copy import copy
from urllib.parse import urlparse

from mokr.constants import INSTALL_PATH
from mokr.launch.base import Launcher


CHROME_PROFILE_PATH = INSTALL_PATH / '.dev_profile'

DEFAULT_CHROME_ARGS = [
    '--allow-pre-commit-input',
    '--disable-background-networking',
    '--disable-background-timer-throttling',
    '--disable-background-occluded-windows',
    '--disable-breakpad',
    '--disable-client-side-phishing-detection',
    '--disable-component-extensions-with-background-pages',
    '--disable-component-update',
    '--disable-default-apps',
    '--disable-dev-shm-usage',
    '--disable-extensions',
    '--disable-field-trial-config',
    '--disable-infobars',
    '--disable-ipc-flooding-protection',
    '--disable-popup-blocking',
    '--disable-prompt-on-repost',
    '--disable-renderer-backgrounding',
    '--disable-search-engine-choice-screen',
    '--disable-sync',
    '--enable-automation',
    '--export-tagged-pdf',
    '--generate-pdf-document-outline',
    '--force-color-profile=srgb',
    '--metrics-recording-only',
    '--no-first-run',
    '--password-store=basic',
    '--use-mock-keychain',
    '--enable-features=NetworkServiceInProcess2',
    '--disable-features=Translate,AcceptCHFrame,MediaRouter,OptimizationHints,ProcessPerSiteUpToMainFrameThreshold',  # noqa
    # '--disable-browser-side-navigation',
    # '--safebrowsing-disable-auto-update',
    # '--disable-hang-monitor',
    # '--disable-translate',
]


class ChromeLauncher(Launcher):
    kind = "chrome"

    def _parse_proxy(self, proxy: str) -> None:
        proxy_parts = urlparse(proxy)
        scheme = proxy_parts.scheme
        host = proxy_parts.hostname
        port = proxy_parts.port
        if proxy.startswith("socks"):
            args = [
                f'--proxy-server={proxy}',
                f'--host-resolver-rules="MAP * ~NOTFOUND , EXCLUDE {host}"',
            ]
        else:
            proxy = f"{scheme}://{host}:{port}"
            args = [f'--proxy-server={proxy}']
        self.browser_arguments.extend(args)
        credentials = {}
        credentials["proxy"] = proxy
        if proxy_parts.username:
            credentials["username"] = proxy_parts.username
        if proxy_parts.password:
            credentials["password"] = proxy_parts.password
        return credentials

    def _custom_default_args(
        self,
        headless: bool = None,
        user_data_dir: str = None,
        devtools: bool = False,
    ):
        browser_arguments = copy(DEFAULT_CHROME_ARGS)
        if user_data_dir:
            browser_arguments.append(f'--user-data-dir={user_data_dir}')
        if devtools:
            browser_arguments.append('--auto-open-devtools-for-tabs')
        if headless:
            browser_arguments.extend(
                ('--headless=new', '--hide-scrollbars', '--mute-audio')
            )

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
        self.proxy_credentials = self._parse_proxy(proxy) if proxy else None
        self.temp_user_data_dir = None
        if not any(
            arg for arg in self.browser_arguments
            if arg.startswith('--remote-debugging-')
        ):
            self.browser_arguments.append(
                f'--remote-debugging-port={self.port}'
            )
        if not any(
            arg for arg in self.browser_arguments
            if arg.startswith('--user-data-dir')
        ):
            if not CHROME_PROFILE_PATH.exists():
                CHROME_PROFILE_PATH.mkdir(parents=True)
            self.temp_user_data_dir = tempfile.mkdtemp(
                dir=str(CHROME_PROFILE_PATH)
            )
            self.browser_arguments.append(
                f'--user-data-dir={self.temp_user_data_dir}'
            )

    def _clean_restore_data_dirs(self) -> None:
        for _ in range(100):
            if self.temp_user_data_dir and os.path.exists(
                self.temp_user_data_dir
            ):
                shutil.rmtree(self.temp_user_data_dir, ignore_errors=True)
                if os.path.exists(self.temp_user_data_dir):
                    time.sleep(0.01)
            else:
                return
        else:
            raise IOError(
                'Unable to remove temporary user data dir'
                f' at {self.temp_user_data_dir}'
            )
