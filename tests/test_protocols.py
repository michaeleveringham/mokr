from __future__ import annotations

import asyncio
import ast
import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from mokr import (
    Browser,
    BrowserContext,
    Connection,
    Element,
    Frame,
    Page,
    Request as RequestProtocol,
    Response,
    launch,
)
from mokr.bidi.connection import BidiSession
from mokr.bidi.execution import BidiElementHandle
from mokr.bidi.frame import BidiFrame
from mokr.bidi.firefox import FirefoxPage
from mokr.bidi.network import BidiFetchDomain, BidiRequest, BidiResponse
from mokr.cdp.browser import CdpBrowser
from mokr.cdp.browser.browser import CdpBrowser as InternalCdpBrowser
from mokr.cdp.execution import CdpElementHandle
from mokr.cdp.network import CdpFetchDomain, CdpRequest, CdpResponse
from mokr.core.routes import RouteStack


class Request:
    def __init__(self) -> None:
        self.is_handled = False
        self.calls: list[str] = []

    async def release(self) -> None:
        self.calls.append("release")
        self.is_handled = True


async def test_route_stack_runs_newest_first_then_releases() -> None:
    request = Request()
    routes = RouteStack(lambda item: item.release())
    routes.add(lambda item: item.calls.append("old") or item)
    routes.add(lambda item: item.calls.append("new") or item)

    await routes.dispatch(request)

    assert request.calls == ["new", "old", "release"]


async def test_route_stack_stops_after_a_handler_resolves_request() -> None:
    request = Request()
    routes = RouteStack(lambda item: item.release())

    async def resolve(item: Request) -> None:
        item.calls.append("resolve")
        item.is_handled = True

    routes.add(lambda item: item.calls.append("old") or item)
    routes.add(resolve)

    await routes.dispatch(request)

    assert request.calls == ["resolve"]


def test_public_cdp_facade_reexports_the_internal_implementation() -> None:
    assert CdpBrowser is InternalCdpBrowser
    assert "protocol" not in inspect.signature(launch).parameters


def test_top_level_exports_the_shared_protocols() -> None:
    from mokr.protocols import (
        Browser as ProtocolBrowser,
        BrowserContext as ProtocolBrowserContext,
        Connection as ProtocolConnection,
        Element as ProtocolElement,
        Frame as ProtocolFrame,
        Page as ProtocolPage,
        Request as ProtocolRequest,
        Response as ProtocolResponse,
    )

    assert (
        Browser,
        BrowserContext,
        Connection,
        Element,
        Frame,
        Page,
        RequestProtocol,
        Response,
    ) == (
        ProtocolBrowser,
        ProtocolBrowserContext,
        ProtocolConnection,
        ProtocolElement,
        ProtocolFrame,
        ProtocolPage,
        ProtocolRequest,
        ProtocolResponse,
    )


def test_bidi_serializes_json_like_function_arguments() -> None:
    assert BidiSession.serialize_remote_value({"name": [1, True, None]}) == {
        "type": "object",
        "value": [
            [
                "name",
                {
                    "type": "array",
                    "value": [
                        {"type": "number", "value": 1},
                        {"type": "boolean", "value": True},
                        {"type": "null"},
                    ],
                },
            ]
        ],
    }
    with pytest.raises(TypeError, match="JSON-like"):
        BidiSession.serialize_remote_value(asyncio.Event())


def test_backend_packages_export_explicit_concrete_types() -> None:
    from mokr.bidi import (
        BidiElementHandle as RootBidiElementHandle,
        BidiFetchDomain as RootBidiFetchDomain,
        BidiRequest as RootBidiRequest,
        BidiResponse as RootBidiResponse,
    )
    from mokr.cdp import (
        CdpElementHandle as RootCdpElementHandle,
        CdpFetchDomain as RootCdpFetchDomain,
        CdpRequest as RootCdpRequest,
        CdpResponse as RootCdpResponse,
    )

    assert (
        RootBidiElementHandle,
        RootBidiFetchDomain,
        RootBidiRequest,
        RootBidiResponse,
    ) == (BidiElementHandle, BidiFetchDomain, BidiRequest, BidiResponse)
    assert (
        RootCdpElementHandle,
        RootCdpFetchDomain,
        RootCdpRequest,
        RootCdpResponse,
    ) == (CdpElementHandle, CdpFetchDomain, CdpRequest, CdpResponse)


def test_every_cdp_class_has_an_explicit_backend_prefix() -> None:
    cdp_root = Path(__file__).parents[1] / "src" / "mokr" / "cdp"
    class_names = {
        node.name
        for path in cdp_root.rglob("*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.ClassDef)
    }

    assert class_names
    assert {name for name in class_names if not name.startswith("Cdp")} == set()


def test_firefox_page_uses_generic_bidi_frame_and_element_types() -> None:
    browser = SimpleNamespace(
        _session=SimpleNamespace(connection=object()),
        _ignore_https_errors=False,
        _proxy_credentials={},
    )
    page = FirefoxPage(browser, "context-1")
    element = BidiElementHandle(page.main_frame, {"sharedId": "node-1"})

    assert isinstance(page.main_frame, BidiFrame)
    assert isinstance(element, BidiElementHandle)


def test_paired_backend_surfaces_have_public_docstrings() -> None:
    from mokr.bidi.browser import (
        BidiBrowser,
        BidiBrowserContext,
        BidiPage,
    )
    from mokr.bidi.connection import BidiConnection
    from mokr.bidi.firefox import (
        FirefoxBrowser,
        FirefoxBrowserContext,
        FirefoxPage,
    )
    from mokr.bidi.input import (
        BidiDialog,
        BidiKeyboard,
        BidiMouse,
        BidiTouchscreen,
    )
    from mokr.cdp.browser import CdpBrowserContext, CdpPage
    from mokr.cdp.connection import CdpConnection, CdpSession
    from mokr.cdp.frame import CdpFrame
    from mokr.cdp.input import (
        CdpDialog,
        CdpKeyboard,
        CdpMouse,
        CdpTouchscreen,
    )

    pairs = [
        (CdpBrowser, BidiBrowser),
        (CdpBrowser, FirefoxBrowser),
        (CdpBrowserContext, BidiBrowserContext),
        (CdpBrowserContext, FirefoxBrowserContext),
        (CdpPage, BidiPage),
        (CdpPage, FirefoxPage),
        (CdpConnection, BidiConnection),
        (CdpSession, BidiSession),
        (CdpDialog, BidiDialog),
        (CdpKeyboard, BidiKeyboard),
        (CdpMouse, BidiMouse),
        (CdpTouchscreen, BidiTouchscreen),
        (CdpFetchDomain, BidiFetchDomain),
        (CdpRequest, BidiRequest),
        (CdpResponse, BidiResponse),
        (CdpFrame, BidiFrame),
        (CdpElementHandle, BidiElementHandle),
    ]

    for cdp_class, bidi_class in pairs:
        assert inspect.getdoc(cdp_class), cdp_class.__name__
        assert inspect.getdoc(bidi_class), bidi_class.__name__
        shared_names = cdp_class.__dict__.keys() & bidi_class.__dict__.keys()
        for name in shared_names:
            if name.startswith("_"):
                continue
            cdp_member = inspect.getattr_static(cdp_class, name)
            bidi_member = inspect.getattr_static(bidi_class, name)
            if isinstance(cdp_member, property):
                cdp_member = cdp_member.fget
            if isinstance(bidi_member, property):
                bidi_member = bidi_member.fget
            if callable(cdp_member) and callable(bidi_member):
                assert inspect.getdoc(
                    cdp_member
                ), f"{cdp_class.__name__}.{name}"
                assert inspect.getdoc(
                    bidi_member
                ), f"{bidi_class.__name__}.{name}"
