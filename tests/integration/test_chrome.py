from __future__ import annotations

import asyncio
import base64
import json
import socket
import subprocess
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.error import URLError
from urllib.request import urlopen

import pytest

from mokr import launch
from mokr.cdp.network import CdpResponse
from mokr.download import browser_binary, ensure_binary

pytestmark = pytest.mark.integration


class LocalSiteHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/json":
            body = json.dumps({"source": "local-test-server"}).encode()
            content_type = "application/json"
        elif self.path == "/headers":
            body = (
                "<title>Headers</title><body>"
                f"{self.headers.get('User-Agent', '')}|"
                f"{self.headers.get('X-Mokr-Test', '')}</body>"
            ).encode()
            content_type = "text/html; charset=utf-8"
        elif self.path == "/input":
            body = (
                b'<input autofocus><button onclick="document.title='
                b"'clicked'\" onpointerdown=\"document.body.dataset.pointerType="
                b'event.pointerType">click</button>'
            )
            content_type = "text/html; charset=utf-8"
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
            content_type = "text/html; charset=utf-8"
        elif self.path == "/frame":
            body = b"<iframe src='/frame-child'></iframe>"
            content_type = "text/html; charset=utf-8"
        elif self.path == "/frame-child":
            body = (
                b"<title>Frame child</title><button id='child'>child</button>"
            )
            content_type = "text/html; charset=utf-8"
        elif self.path == "/auth":
            if self.headers.get("Authorization") != "Basic bW9rcjpjZHA=":
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Basic realm="mokr"')
                self.end_headers()
                return
            body = b"<title>Authenticated</title>Chrome CDP credentials"
            content_type = "text/html; charset=utf-8"
        elif self.path in {"/http-set-cookie", "/http-echo-cookie"}:
            body = self.headers.get("Cookie", "").encode()
            content_type = "text/html; charset=utf-8"
        elif self.path == "/alert":
            body = b"<script>alert('Chrome CDP dialog')</script>"
            content_type = "text/html; charset=utf-8"
        else:
            body = (
                b"<html><head><title>Mokr integration</title></head>"
                b"<body><main id='content'>served locally</main></body></html>"
            )
            content_type = "text/html; charset=utf-8"
        self.send_response(200)
        if self.path == "/http-set-cookie":
            self.send_header("Set-Cookie", "from_http=client; Path=/")
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
def require_chrome() -> None:
    if not ensure_binary("chrome"):
        pytest.skip("Chrome for Testing is not installed; run `mokr install`.")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory() as profile_dir:
        process = subprocess.Popen(
            [
                str(browser_binary("chrome")),
                "--headless=new",
                "--no-first-run",
                f"--remote-debugging-port={port}",
                f"--user-data-dir={profile_dir}",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )
        endpoint = f"http://127.0.0.1:{port}/json/version"
        available = False
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                try:
                    with urlopen(endpoint, timeout=0.2):
                        available = True
                        break
                except URLError:
                    if process.poll() is not None:
                        break
                    time.sleep(0.1)
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
        if not available:
            pytest.skip("Chrome could not open a local DevTools endpoint.")


async def test_launch_navigate_and_read_page_content(local_site: str) -> None:
    async with launch(headless=True) as browser:
        page = await browser.first_page()

        assert browser.kind == "chrome"
        assert page is not None
        response = await page.goto(local_site)

        assert response is not None
        assert response.status == 200
        assert await page.title() == "Mokr integration"
        assert "served locally" in await page.content()


async def test_page_fetch_reads_a_same_origin_local_json_resource(
    local_site: str,
) -> None:
    async with launch(headless=True) as browser:
        page = await browser.first_page()
        assert page is not None
        await page.goto(local_site)

        response = await page.fetch(f"{local_site}/json")

        assert isinstance(response, CdpResponse)
        assert response.status == 200
        assert await response.json() == {"source": "local-test-server"}


async def test_request_interception_callbacks_stack_newest_first(
    local_site: str,
) -> None:
    async with launch(headless=True) as browser:
        page = await browser.first_page()
        assert page is not None
        await page.goto(local_site)
        callback_order = []
        intercepted_url = f"{local_site}/intercepted"

        async def first_registered(request):
            if request.url != intercepted_url:
                return request
            callback_order.append("first")
            await request.fulfill(
                headers={"Content-Type": "text/html; charset=utf-8"},
                body=(
                    "<html><head><title>Intercepted</title></head>"
                    "<body>fulfilled by the interception route</body></html>"
                ),
            )

        def second_registered(request):
            if request.url != intercepted_url:
                return request
            callback_order.append("second")
            return request

        page.on("request", first_registered)
        page.on("request", second_registered)
        await page.goto(intercepted_url)

        assert callback_order == ["second", "first"]
        assert await page.title() == "Intercepted"
        assert "fulfilled by the interception route" in await page.content()


async def test_response_events_expose_response_data(local_site: str) -> None:
    async with launch(headless=True) as browser:
        page = await browser.first_page()
        assert page is not None
        responses = []
        page.on("response", responses.append)
        await page.goto(local_site)

        response = next(
            item for item in responses if item.url == f"{local_site}/"
        )
        assert response.status == 200
        assert "served locally" in await response.content()


async def test_storage_and_network_overrides(local_site: str) -> None:
    async with launch(headless=True) as browser:
        page = await browser.first_page()
        assert page is not None
        await page.goto(local_site)

        await page.set_cookies(
            [{"name": "mokr", "value": "cdp", "url": local_site}]
        )
        cookies = await page.cookies()
        assert any(
            cookie["name"] == "mokr" and cookie["value"] == "cdp"
            for cookie in cookies
        )
        assert await page.evaluate("document.cookie") == "mokr=cdp"

        await page.set_extra_http_headers({"X-Mokr-Test": "cdp"})
        await page.set_user_agent("mokr-integration-agent")
        await page.goto(f"{local_site}/headers")
        assert "mokr-integration-agent|cdp" in await page.content()

        await page.delete_cookies([{"name": "mokr", "url": local_site}])
        assert not any(
            cookie["name"] == "mokr" for cookie in await page.cookies()
        )


async def test_http_domain_synchronizes_cookies(local_site: str) -> None:
    async with launch(headless=True) as browser:
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


async def test_preload_viewport_and_screenshot(local_site: str) -> None:
    async with launch(headless=True) as browser:
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
        assert image.startswith(b"\x89PNG\r\n\x1a\n")
        encoded = await page.screenshot(encoding="base64")
        assert isinstance(encoded, str)
        assert base64.b64decode(encoded).startswith(b"\x89PNG\r\n\x1a\n")


async def test_dialog_and_input(local_site: str) -> None:
    async with launch(headless=True) as browser:
        page = await browser.first_page()
        assert page is not None
        dialogs = []
        page.on("dialog", dialogs.append)

        alert = asyncio.create_task(page.goto(f"{local_site}/alert"))
        while not dialogs:
            await asyncio.sleep(0.01)
        dialog = dialogs[0]
        assert dialog.kind == "alert"
        assert dialog.message == "Chrome CDP dialog"
        await dialog.accept()
        await alert

        await page.goto(f"{local_site}/input")
        await page.evaluate("document.querySelector('input').focus()")
        await page.keyboard.type_text("cdp input")
        button_x = await page.evaluate(
            "Math.round(document.querySelector('button').getBoundingClientRect().x + 5)"
        )
        await page.mouse.click(button_x, 10)
        assert (
            await page.evaluate("document.querySelector('input').value")
            == "cdp input"
        )
        assert await page.title() == "clicked"


async def test_touchscreen_input(local_site: str) -> None:
    async with launch(headless=True) as browser:
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


async def test_page_locators_refresh_and_rendering(local_site: str) -> None:
    async with launch(headless=True) as browser:
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
        await page.click("#target", delay=0)
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
        assert clipped.startswith(b"\x89PNG\r\n\x1a\n")

        await page.goto(local_site)
        await page.refresh()
        assert await page.title() == "Mokr integration"

        pdf = await page.pdf()
        assert pdf.startswith(b"%PDF")


async def test_tracks_iframe_contexts(local_site: str) -> None:
    async with launch(headless=True) as browser:
        page = await browser.first_page()
        assert page is not None
        await page.goto(f"{local_site}/frame")

        child_frames = [
            frame for frame in page.frames if frame is not page.main_frame
        ]
        assert len(child_frames) == 1
        child = child_frames[0]
        child_button = await child.wait_for_selector("#child")
        assert child_button is not None
        assert "child" in await child_button.content()


async def test_resolves_authentication_challenges(local_site: str) -> None:
    async with launch(headless=True) as browser:
        page = await browser.first_page()
        assert page is not None
        await page.set_credentials({"username": "mokr", "password": "cdp"})
        await page.goto(f"{local_site}/auth")
        assert await page.title() == "Authenticated"
        assert "Chrome CDP credentials" in await page.content()
