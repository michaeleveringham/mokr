import re
import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import requests
from tqdm import tqdm

from mokr.constants import CHROME_VERSION, FIREFOX_BUILD, INSTALL_PATH


CHROME_DL_HOST = f'https://storage.googleapis.com/chrome-for-testing-public/{CHROME_VERSION}'  # noqa
FIREFOX_DL_HOST = f"https://archive.mozilla.org/pub/firefox/nightly/2024/01/2024-01-21-20-40-46-mozilla-central/firefox-{FIREFOX_BUILD}"  # noqa

CR_DOWNLOAD_URLS = {
    'linux': f'{CHROME_DL_HOST}/linux64/chrome-linux64.zip',
    'darwin': f'{CHROME_DL_HOST}/mac-x64/chrome-mac-x64.zip',
    'mac_arm': f'{CHROME_DL_HOST}/mac-arm64/chrome-mac-arm64.zip',
    'win32': f'{CHROME_DL_HOST}/win64/chrome-win64.zip',
}
FF_DOWNLOAD_URLS = {
    "linux": f"{FIREFOX_DL_HOST}.en-US.linux-x86_64.tar.bz2",
    "darwin": f"{FIREFOX_DL_HOST}.en-US.mac.dmg",
    "win32": f"{FIREFOX_DL_HOST}.en-US.win64.zip",
}

CR_BINARY_NAMES = {
    'linux': INSTALL_PATH / CHROME_VERSION / 'chrome-linux64' / 'chrome',
    'darwin': INSTALL_PATH / CHROME_VERSION / 'chrome-mac-x64' / 'Chrome.app' / 'Contents' / 'MacOS' / 'Chrome',  # noqa
    'mac_arm': INSTALL_PATH / CHROME_VERSION / 'chrome-mac-arm64' / 'Google chrome for Testing.app' / 'Contents' / 'MacOS' / 'Google Chrome for Testing',  # noqa
    'win32': INSTALL_PATH / CHROME_VERSION / 'chrome-win64' / 'chrome.exe',
}
FF_BINARY_NAMES = {
    "linux": INSTALL_PATH / FIREFOX_BUILD / 'firefox' / 'firefox',
    "darwin": INSTALL_PATH / FIREFOX_BUILD / 'Firefox Nightly.app' / 'Contents' / 'MacOS' / 'firefox',  # noqa
    "win32": INSTALL_PATH / FIREFOX_BUILD / 'firefox' / 'firefox.exe',
}
CR_BINARY_PATHS = {
    k: v.expanduser().absolute() for k, v in CR_BINARY_NAMES.items()
}
FF_BINARY_PATHS = {
    k: v.expanduser().absolute() for k, v in FF_BINARY_NAMES.items()
}


def get_platform() -> str:
    """Small utility to get different URL for MacOS Silicon machines."""
    machine = platform.machine()
    if sys.platform == "darwin" and machine == "arm64":
        return "mac_arm"
    else:
        return sys.platform


def download_zip(browser_type: str, url: str) -> BytesIO:
    """
    Download browser from the given `url`.

    Args:
        browser_type (str): Target browser type, of "chrome" or "firefox".
        url (str): URL to download from.

    Raises:
        requests.HTTPError: Raised if response is bad (status code over 399).

    Returns:
        BytesIO: The browser content as a BytesIO object.
    """
    print(f'Starting {browser_type.title()} download.')
    data = BytesIO()
    with requests.get(url, stream=True) as response:
        if response.status_code >= 400:
            raise requests.HTTPError(f"Bad response from server at: {url}")
        try:
            total_length = int(response.headers['content-length'])
        except (KeyError, ValueError, AttributeError):
            total_length = 0
        process_bar = tqdm(total=total_length, unit_scale=True, unit='b')
        for chunk in response.iter_content(chunk_size=8192):
            data.write(chunk)
            process_bar.update(len(chunk))
        process_bar.close()
    return data


def browser_binary(browser_type: str) -> Path:
    """
    Get path of the system target browser binary.

    Args:
        browser_type (str): Target browser type, of "chrome" or "firefox".

    Returns:
        Path: Browser binary Path object.
    """
    types_to_maps = {
        "chrome": CR_BINARY_PATHS,
        "firefox": FF_BINARY_PATHS,
    }
    mapping = types_to_maps[browser_type]
    binary = mapping.get(get_platform()) or mapping[sys.platform]
    return binary


def ensure_binary(browser_type: str) -> bool:
    """
    Ensure the target browser exists on this machine.

    Args:
        browser_type (str): Target browser type, of "chrome" or "firefox".

    Returns:
        bool: True if binary exists, otherwise False.
    """
    return browser_binary(browser_type).exists()


def install_dmg(process_bar: tqdm, dmg_path: str, dest_path: Path) -> None:
    """
    Install browser from dmg file. Mounts the dmg and copies to target path.

    Args:
        process_bar (tqdm): A process bar to update as actions occur.
        dmg_path (str): Path to dmg file.
        dest_path (Path): Path to final directory.

    Raises:
        OSError: Raised if mount fails.
        FileNotFoundError: Raised if dmg contains no .app files.
    """
    process_bar.update(2)
    proc = subprocess.run(
        ["hdiutil", "attach", "-nobrowse", "-noautoopen", dmg_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    process_bar.update(5)
    stdout = proc.stdout.decode()
    volumes = re.search(r"[\t]/Volumes/(.*)[\n]", stdout)
    if not volumes:
        raise OSError(f"Couldn't mount dmg: {stdout}")
    mount_path = Path(volumes[0].strip())
    process_bar.update(6)
    exception = None
    try:
        app_paths = list(mount_path.glob("**/*.app"))
        if not app_paths:
            raise FileNotFoundError(f"Failed to find an app in: {mount_path}")
        app_path = app_paths[0]
        dest_path = dest_path / app_path.name
        shutil.copytree(app_path, dest_path, dirs_exist_ok=True)
        process_bar.update(9)
    except Exception as e:
        exception = e
    finally:
        proc = subprocess.run(
            ['hdiutil', "detach", dmg_path, "-quiet"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if exception:
            raise type(exception)(str(exception))
    process_bar.update(10)


def extract(browser_type: str, data: BytesIO, path: Path, url: str) -> None:
    """
    Extract given loaded zip file to target `path`.

    Args:
        browser_type (str): Target browser type, of "chrome" or "firefox".
        data (BytesIO): Zip file as BytesIO.
        path (Path): Destination path to extract to.
        url (str): Download URL the file came from.

    Raises:
        IOError: Raised if an unhandled error occurs and the browser simply
            doesn't end up extracted to the target.
    """
    # On mac, Firefox is a dmg file, need to mount it and copy contents.
    print(f'Beginning {browser_type.title()} extraction.')
    if url.lower().endswith(".dmg"):
        process_bar = tqdm(range(11))
        temp_dmg = tempfile.NamedTemporaryFile()
        temp_dmg.write(data.getbuffer())
        process_bar.update(1)
        try:
            install_dmg(process_bar, temp_dmg.name, path)
        except Exception:
            temp_dmg.close()
            raise
        process_bar.close()
    elif url.lower().endswith(".tar.bz2"):
        temp_bz = tempfile.NamedTemporaryFile()
        temp_bz.write(data.getbuffer())
        try:
            with open(temp_bz.name, "rb") as fileobj:
                total_bytes = os.stat(temp_bz.name).st_size
                process_bar = tqdm(total=total_bytes, unit_scale=True, unit='b')
                with tarfile.open(fileobj=fileobj, mode="r:bz2") as tar:
                    last = 0
                    for member in tar:
                        member_data = tar.extractfile(member)
                        if member_data is None:
                            continue
                        subpath = (path / member.name)
                        subpath.parent.mkdir(parents=True, exist_ok=True)
                        subpath.write_bytes(member_data.read())
                        process_bar.update(fileobj.tell() - last)
                        last = fileobj.tell()
                process_bar.close()
        except Exception:
            temp_bz.close()
            raise
    else:
        with ZipFile(data) as zf:
            for member in tqdm(zf.infolist()):
                zf.extract(member, str(path))
    if not ensure_binary(browser_type):
        raise IOError('Failed to extract browser.')
    # On MacOS and Linux, helpers need execute too or process crashes instantly.
    if sys.platform == "win32":
        browser_binary(browser_type).chmod(
            browser_binary(browser_type).stat().st_mode | stat.S_IXOTH
            | stat.S_IXGRP | stat.S_IXUSR | stat.S_IEXEC
        )
    else:
        for subpath in path.glob("**/*"):
            subpath.chmod(
                subpath.stat().st_mode | stat.S_IXOTH
                | stat.S_IXGRP | stat.S_IXUSR | stat.S_IEXEC
            )
    print(f'{browser_type.title()} successfully extracted to: {path}')


def install_binary(browser_type: str) -> None:
    """
    Download and extract binary.

    Args:
        browser_type (str): Target browser type, of "chrome" or "firefox".
    """
    type_to_infos = {
        "chrome": (CR_DOWNLOAD_URLS, CHROME_VERSION),
        "firefox": (FF_DOWNLOAD_URLS, FIREFOX_BUILD),
    }
    download_urls, version = type_to_infos[browser_type]
    download_url = (
        download_urls.get(get_platform()) or download_urls[sys.platform]
    )
    extract(
        browser_type,
        download_zip(browser_type, download_url),
        INSTALL_PATH / version,
        download_url,
    )
