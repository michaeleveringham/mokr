from mokr.constants import CHROME_VERSION, FIREFOX_BUILD
from mokr.download import CR_DOWNLOAD_URLS, FF_DOWNLOAD_URLS


def test_default_downloads_point_at_current_browser_artifacts():
    assert CHROME_VERSION in CR_DOWNLOAD_URLS["win32"]
    assert "chrome-for-testing-public" in CR_DOWNLOAD_URLS["win32"]
    assert FIREFOX_BUILD in FF_DOWNLOAD_URLS["win32"]
    assert "latest-mozilla-central" in FF_DOWNLOAD_URLS["win32"]
    assert FF_DOWNLOAD_URLS["linux"].endswith(".tar.xz")
