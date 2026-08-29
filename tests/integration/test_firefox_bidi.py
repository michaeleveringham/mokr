from __future__ import annotations

import asyncio
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

from mokr import launch
from mokr.bidi.network import BidiResponse
from mokr.download import ensure_binary
from mokr.exceptions import PageError, UnsupportedOperationError

pytestmark = pytest.mark.integration


class LocalSiteHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/headers":
            body = (
                "<title>Headers</title><body>"
                f"{self.headers.get('User-Agent', '')}|"
                f"{self.headers.get('X-Mokr-Test', '')}</body>"
            ).encode()
        elif self.path == "/input":
            body = (
                b'<input autofocus><button onclick="document.title='
                b"'clicked'\" onpointerdown=\"document.body.dataset.pointerType="
                b'event.pointerType">click</button>'
            )
        elif self.path == "/elements":
            body = b"""
                <button id='target'
                    onpointerover=\"document.body.dataset.hovered='yes'\"
                    onclick=\"document.title='element-clicked'\">target</button>
                <input id='text'>
                <select id='choice' multiple>
                    <option value='one'>one</option><option value='two'>two</option>
                </select>
                <input id='upload' type='file'>
            """
        elif self.path == "/frame":
            body = b"<iframe src='/frame-child'></iframe>"
        elif self.path == "/frame-child":
            body = (
                b"<title>Frame child</title><button id='child'>child</button>"
            )
        elif self.path == "/auth":
            if self.headers.get("Authorization") != "Basic bW9rcjpiaWRp":
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Basic realm="mokr"')
                self.end_headers()
                return
            body = b"<title>Authenticated</title>native BiDi credentials"
        elif self.path == "/http-set-cookie":
            body = self.headers.get("Cookie", "").encode()
        elif self.path == "/http-echo-cookie":
            body = self.headers.get("Cookie", "").encode()
        elif self.path == "/script":
            body = b"<script>document.title = 'script-ran'</script>"
        elif self.path == "/alert":
            body = b"<script>alert('Firefox BiDi dialog')</script>"
        elif self.path == "/json":
            body = b'{"source":"firefox-bidi","value":7}'
        else:
            body = (
                b"<html><head><title>Firefox BiDi</title></head>"
                b"<body>served by native BiDi</body></html>"
            )
        self.send_response(200)
        if self.path == "/http-set-cookie":
            self.send_header("Set-Cookie", "from_http=client; Path=/")
        content_type = (
            "application/json"
            if self.path == "/json"
            else "text/html; charset=utf-8"
        )
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        pass


@pytest.fixture(scope="module")
def local_site() -> str:
    server = ThreadingHTTPServer(("127.0.0.1", 0), LocalSiteHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.fixture(scope="module", autouse=True)
def require_firefox() -> None:
    if not ensure_binary("firefox"):
        pytest.skip(
            "Firefox is not installed; run `mokr install --type firefox`."
        )


async def test_native_firefox_bidi_launch_navigate_and_evaluate(
    local_site: str,
) -> None:
    async with launch("firefox", headless=True) as browser:
        page = await browser.first_page()
        if page is None:
            page = await browser.browser_contexts[0].new_page()

        response = await page.goto(local_site)

        assert browser.kind == "firefox"
        assert response.url == f"{local_site}/"
        assert response.status == 200
        assert "served by native BiDi" in await response.content()
        assert await page.title() == "Firefox BiDi"
        assert "native BiDi" in await page.content()


async def test_firefox_bidi_request_routes_are_blocking_and_stack_newest_first(
    local_site: str,
) -> None:
    async with launch("firefox", headless=True) as browser:
        page = await browser.first_page()
        if page is None:
            page = await browser.browser_contexts[0].new_page()
        order = []
        intercepted_url = f"{local_site}/intercepted"

        async def first(request):
            if request.url != intercepted_url:
                return request
            order.append("first")
            await request.fulfill(
                "<title>Intercepted</title><p>fulfilled by Firefox BiDi</p>",
                headers={"Content-Type": "text/html; charset=utf-8"},
            )

        def second(request):
            if request.url == intercepted_url:
                order.append("second")
            return request

        page.on("request", first)
        page.on("request", second)
        await page.goto(intercepted_url)

        assert order == ["second", "first"]
        assert await page.title() == "Intercepted"
        assert "fulfilled by Firefox BiDi" in await page.content()


async def test_firefox_bidi_response_events_expose_response_data(
    local_site: str,
) -> None:
    async with launch("firefox", headless=True) as browser:
        page = await browser.first_page()
        if page is None:
            page = await browser.browser_contexts[0].new_page()
        responses = []
        page.on("response", responses.append)
        await page.goto(local_site)

        response = next(
            item for item in responses if item.url == f"{local_site}/"
        )
        assert response.status == 200
        assert "served by native BiDi" in await response.content()


async def test_firefox_bidi_expose_function_uses_channels_across_navigation(
    local_site: str,
) -> None:
    async with launch("firefox", headless=True) as browser:
        page = await browser.first_page()
        assert page is not None

        async def multiply(left: int, right: int) -> int:
            await asyncio.sleep(0)
            return left * right

        await page.expose_function("multiply_from_python", multiply)
        assert (
            await page.evaluate(
                "(async () => await multiply_from_python(6, 7))()"
            )
            == 42
        )
        with pytest.raises(PageError):
            await page.expose_function("multiply_from_python", multiply)

        await page.goto(local_site)
        assert (
            await page.evaluate(
                "(async () => await multiply_from_python(3, 5))()"
            )
            == 15
        )


async def test_firefox_bidi_fetch_domain_runs_in_the_page_context(
    local_site: str,
) -> None:
    async with launch("firefox", headless=True) as browser:
        page = await browser.first_page()
        assert page is not None
        await page.goto(local_site)
        response = await page.fetch(f"{local_site}/json")
        assert isinstance(response, BidiResponse)
        assert response.status == 200
        assert await response.json() == {"source": "firefox-bidi", "value": 7}

        await page.set_cookies(
            [{"name": "from_page", "value": "fetch", "url": local_site}]
        )
        cookie_response = await page.fetch(f"{local_site}/http-echo-cookie")
        assert "from_page=fetch" in await cookie_response.content()
        with pytest.raises(UnsupportedOperationError):
            await page.fetch(f"{local_site}/json", priority="high")


async def test_firefox_bidi_storage_and_network_overrides(
    local_site: str,
) -> None:
    async with launch("firefox", headless=True) as browser:
        page = await browser.first_page()
        assert page is not None
        await page.goto(local_site)

        await page.set_cookies(
            [{"name": "mokr", "value": "bidi", "url": local_site}]
        )
        cookies = await page.cookies()
        assert any(
            cookie["name"] == "mokr" and cookie["value"] == "bidi"
            for cookie in cookies
        )
        assert await page.evaluate("document.cookie") == "mokr=bidi"

        await page.set_extra_http_headers({"X-Mokr-Test": "native"})
        await page.set_user_agent("mokr-integration-agent")
        await page.goto(f"{local_site}/headers")
        content = await page.content()
        assert "mokr-integration-agent|native" in content

        await page.delete_cookies([{"name": "mokr", "url": local_site}])
        assert not any(
            cookie["name"] == "mokr" for cookie in await page.cookies()
        )


async def test_firefox_bidi_http_domain_synchronizes_cookies(
    local_site: str,
) -> None:
    async with launch("firefox", headless=True) as browser:
        page = await browser.first_page()
        assert page is not None
        await page.goto(local_site)
        await page.set_cookies(
            [{"name": "from_page", "value": "browser", "url": local_site}]
        )

        response = await page.http_domain.send(f"{local_site}/http-set-cookie")
        assert response.status == 200
        assert "from_page=browser" in await response.content()

        page_cookies = await page.cookies()
        assert any(
            cookie["name"] == "from_http" and cookie["value"] == "client"
            for cookie in page_cookies
        )
        echoed = await page.http_domain.send(f"{local_site}/http-echo-cookie")
        assert "from_http=client" in await echoed.content()


async def test_firefox_bidi_preload_viewport_and_screenshot(
    local_site: str,
) -> None:
    async with launch("firefox", headless=True) as browser:
        page = await browser.first_page()
        assert page is not None
        await page.evaluate_on_new_document(
            "() => { window.__mokr_preloaded = 'yes'; }"
        )
        await page.set_viewport(
            {"width": 640, "height": 480, "deviceScaleFactor": 1}
        )
        await page.goto(local_site)

        assert await page.evaluate("window.__mokr_preloaded") == "yes"
        image = await page.screenshot(full_page=True)
        assert isinstance(image, bytes)
        assert image.startswith(b"\x89PNG\r\n\x1a\n")
        encoded = await page.screenshot(encoding="base64")
        assert isinstance(encoded, str)
        assert base64.b64decode(encoded).startswith(b"\x89PNG\r\n\x1a\n")


async def test_firefox_bidi_dialog_and_input(local_site: str) -> None:
    async with launch("firefox", headless=True) as browser:
        page = await browser.first_page()
        assert page is not None
        dialogs = []
        page.on("dialog", dialogs.append)

        alert = asyncio.create_task(page.goto(f"{local_site}/alert"))
        while not dialogs:
            await asyncio.sleep(0.01)
        dialog = dialogs[0]
        assert dialog.kind == "alert"
        assert dialog.message == "Firefox BiDi dialog"
        await dialog.accept()
        await alert

        await page.goto(f"{local_site}/input")
        await page.evaluate("document.querySelector('input').focus()")
        await page.keyboard.type_text("native input")
        button_x = await page.evaluate(
            "Math.round(document.querySelector('button').getBoundingClientRect().x + 5)"
        )
        await page.mouse.click(button_x, 10)
        assert (
            await page.evaluate("document.querySelector('input').value")
            == "native input"
        )
        assert await page.title() == "clicked"


async def test_firefox_bidi_touchscreen_input(local_site: str) -> None:
    async with launch("firefox", headless=True) as browser:
        page = await browser.first_page()
        assert page is not None
        await page.goto(f"{local_site}/input")
        x = await page.evaluate(
            "Math.round(document.querySelector('button').getBoundingClientRect().x + 5)"
        )
        await page.touchscreen.tap(x, 10)
        assert (
            await page.evaluate("document.body.dataset.pointerType") == "touch"
        )


async def test_firefox_specific_bidi_page_locators_history_and_rendering(
    local_site: str,
) -> None:
    async with launch("firefox", headless=True) as browser:
        page = await browser.first_page()
        assert page is not None
        await page.goto(f"{local_site}/elements")

        target = await page.query_selector("#target")
        assert target is not None
        assert "target" in await target.content()
        assert await page.evaluate("(left, right) => left + right", 2, 3) == 5
        assert len(await page.xpath("//button[@id='target']")) == 1
        await page.hover("#target")
        assert await page.evaluate("document.body.dataset.hovered") == "yes"
        await page.click("#target")
        assert await page.title() == "element-clicked"

        await page.type_text("#text", "shared facade")
        assert (
            await page.evaluate("document.querySelector('#text').value")
            == "shared facade"
        )
        assert await page.select("#choice", ["one", "two"]) == ["one", "two"]
        await page.bring_to_front()

        upload = await page.query_selector("#upload")
        assert upload is not None
        upload_fixture = Path(__file__).parents[1] / "fixtures" / "upload.txt"
        await upload.upload_file([str(upload_fixture)])
        assert (
            await page.evaluate(
                "document.querySelector('#upload').files[0].name"
            )
            == "upload.txt"
        )

        element_image = await target.screenshot()
        assert element_image.startswith(b"\x89PNG\r\n\x1a\n")

        clipped = await page.screenshot(
            clip={"x": 0, "y": 0, "width": 100, "height": 50}
        )
        assert isinstance(clipped, bytes)
        assert clipped.startswith(b"\x89PNG\r\n\x1a\n")

        await page.goto(local_site)
        await page.go_back()
        assert await page.query_selector("#target") is not None
        await page.go_forward()
        assert await page.title() == "Firefox BiDi"

        pdf = await page.pdf()
        assert pdf.startswith(b"%PDF")


async def test_firefox_bidi_tracks_iframe_contexts(local_site: str) -> None:
    async with launch("firefox", headless=True) as browser:
        page = await browser.first_page()
        assert page is not None
        await page.goto(f"{local_site}/frame")

        child_frames = [
            frame for frame in page.frames if frame is not page.main_frame
        ]
        assert len(child_frames) == 1
        child = child_frames[0]
        assert await child.evaluate("document.title") == "Frame child"
        assert await child.query_selector("#child") is not None


async def test_firefox_bidi_installs_temporary_extension() -> None:
    extension = Path(__file__).parents[1] / "fixtures" / "firefox_extension"
    async with launch("firefox", headless=True) as browser:
        extension_id = await browser.install_extension(str(extension))
        assert extension_id == "mokr-bidi-integration@example.test"


async def test_firefox_bidi_resolves_authentication_challenges(
    local_site: str,
) -> None:
    async with launch("firefox", headless=True) as browser:
        page = await browser.first_page()
        assert page is not None
        await page.set_credentials("mokr", "bidi")
        await page.goto(f"{local_site}/auth")
        assert await page.title() == "Authenticated"
        assert "native BiDi credentials" in await page.content()
