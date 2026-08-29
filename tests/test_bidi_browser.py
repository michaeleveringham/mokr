from mokr.bidi.browser import BidiBrowser
from mokr.bidi.connection import BidiSession


class RecordingConnection:
    def __init__(self) -> None:
        self.calls = []
        self.handlers = {}

    def on(self, event, handler) -> None:
        self.handlers[event] = handler

    async def send(self, method, params=None):
        self.calls.append((method, params))
        responses = {
            "session.subscribe": {},
            "browsingContext.getTree": {
                "contexts": [{"context": "page-1", "url": "about:blank"}]
            },
            "browsingContext.create": {"context": "page-2"},
            "browsingContext.navigate": {
                "navigation": "nav-1",
                "url": "https://example.test/",
            },
            "script.evaluate": {
                "type": "success",
                "result": {"type": "string", "value": "Example"},
            },
            "network.addIntercept": {"intercept": "intercept-1"},
            "network.removeIntercept": {},
            "browsingContext.activate": {},
            "browsingContext.reload": {
                "navigation": "reload-1",
                "url": "https://example.test/",
            },
        }
        return responses[method]


async def test_bidi_browser_preserves_page_lifecycle_shape() -> None:
    connection = RecordingConnection()
    browser = BidiBrowser("firefox", BidiSession(connection))
    await browser.ready()

    page = await browser.first_page()
    assert page is not None
    assert await page.title() == "Example"

    next_page = await browser.browser_contexts[0].new_page()
    result = await next_page.goto("https://example.test/")

    assert result["navigation"] == "nav-1"
    assert next_page.url == "https://example.test/"


async def test_bidi_page_can_activate_reload_and_remove_an_intercept() -> None:
    connection = RecordingConnection()
    browser = BidiBrowser("firefox", BidiSession(connection))
    await browser.ready()
    page = await browser.first_page()

    await page.bring_to_front()
    assert await page.refresh() == {
        "navigation": "reload-1",
        "url": "https://example.test/",
    }
    await page.set_request_interception_enabled(True)
    await page.set_request_interception_enabled(False)

    assert (
        "browsingContext.activate",
        {"context": "page-1"},
    ) in connection.calls
    assert (
        "network.removeIntercept",
        {"intercept": "intercept-1"},
    ) in connection.calls
