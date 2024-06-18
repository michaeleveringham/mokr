import os
import sys
from pathlib import Path


MOKR_VERSION = "0.1.2"
DEFAULT_CHROME_VERSION = "122.0.6261.128"
DEFAULT_FIREFOX_BUILD = "123.0a1"
CHROME_VERSION = os.environ.get(
    'MOKR_CHROME_VERSION',
    DEFAULT_CHROME_VERSION,
)
FIREFOX_BUILD = os.environ.get(
    'MOKR_CHROME_VERSION',
    DEFAULT_FIREFOX_BUILD,
)

if os.environ.get("MOKR_INSTALL_DIR"):
    INSTALL_DIR_NAME = os.environ["MOKR_INSTALL_DIR"]
elif sys.platform == "linux":
    INSTALL_DIR_NAME = "~/.cache/"
elif sys.platform == "darwin":
    INSTALL_DIR_NAME = "~/Library/Caches/"
elif sys.platform == "win32":
    INSTALL_DIR_NAME = os.path.expandvars("%USERPROFILE%/AppData/Local/")
else:
    raise NotImplementedError(
        "Unsupported platform. Set MOKR_INSTALL_DIR environment variable to"
        " bypass this check."
    )
INSTALL_PATH = Path(INSTALL_DIR_NAME).expanduser() / 'mokr'
