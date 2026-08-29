from __future__ import annotations

import pytest

from mokr.cdp.browser.browser import CdpBrowser
from mokr.cdp.browser.target import CdpTarget
from mokr.constants import (
    BROWSER_GET_VERSION,
    TARGET_CHANGED,
    TARGET_CREATE_BROWSER_CONTEXT,
    TARGET_CREATED,
    TARGET_DESTROYED,
    TARGET_DISPOSE_BROWSER_CONTEXT,
    TARGET_SET_DISCOVER_TARGETS,
)
from mokr.exceptions import BrowserError

from .conftest import FakeConnection


def make_browser(connection: FakeConnection, **kwargs) -> CdpBrowser:
    return CdpBrowser(
        browser_type="chrome",
        connection=connection,
        context_ids=kwargs.pop("context_ids", []),
        ignore_https_errors=False,
        default_viewport=None,
        **kwargs,
    )


async def test_ready_loads_browser_metadata_and_enables_target_discovery() -> (
    None
):
    connection = FakeConnection(
        {BROWSER_GET_VERSION: {"product": "Chrome/123", "userAgent": "UA"}}
    )
    browser = make_browser(connection)

    assert await browser.ready() is browser
    assert browser.version == "Chrome/123"
    assert browser.user_agent == "UA"
    assert browser.ws_endpoint == "ws://browser.test/devtools"
    assert connection.calls == [
        (BROWSER_GET_VERSION, None),
        (TARGET_SET_DISCOVER_TARGETS, {"discover": True}),
    ]


async def test_incognito_context_lifecycle_and_default_context_protection() -> (
    None
):
    connection = FakeConnection(
        {TARGET_CREATE_BROWSER_CONTEXT: {"browserContextId": "incognito-1"}}
    )
    browser = make_browser(connection)

    context = await browser.create_incognito_browser_context()

    assert context.incognito
    assert context.browser is browser
    assert context in browser.browser_contexts
    await context.close()
    assert connection.calls[-1] == (
        TARGET_DISPOSE_BROWSER_CONTEXT,
        {"browserContextId": "incognito-1"},
    )
    assert context not in browser.browser_contexts

    with pytest.raises(BrowserError, match="Non-incognito"):
        await browser.browser_contexts[0].close()


async def test_target_events_assign_context_and_emit_create_change_destroy() -> (
    None
):
    connection = FakeConnection()
    browser = make_browser(connection, context_ids=["context-1"])
    context = browser.browser_contexts[1]
    browser_events = []
    context_events = []
    browser.on(
        TARGET_CREATED,
        lambda target: browser_events.append(("created", target.url)),
    )
    browser.on(
        TARGET_CHANGED,
        lambda target: browser_events.append(("changed", target.url)),
    )
    browser.on(
        TARGET_DESTROYED,
        lambda target: browser_events.append(("destroyed", target.url)),
    )
    context.on(
        TARGET_CREATED,
        lambda target: context_events.append(("created", target.url)),
    )
    context.on(
        TARGET_CHANGED,
        lambda target: context_events.append(("changed", target.url)),
    )
    context.on(
        TARGET_DESTROYED,
        lambda target: context_events.append(("destroyed", target.url)),
    )
    target_info = {
        "targetId": "page-1",
        "type": "page",
        "url": "https://example.test/first",
        "browserContextId": "context-1",
    }

    await browser._target_created({"targetInfo": target_info})
    target = browser.targets()[0]
    assert target.browser_context is context
    assert context.targets() == [target]

    await browser._target_info_changed(
        {"targetInfo": {**target_info, "url": "https://example.test/second"}}
    )
    await browser._target_destroyed({"targetId": "page-1"})

    assert browser.targets() == []
    assert browser_events == [
        ("created", "https://example.test/first"),
        ("changed", "https://example.test/second"),
        ("destroyed", "https://example.test/second"),
    ]
    assert context_events == browser_events


async def test_disconnect_disposes_connection_and_rejects_pending_targets() -> (
    None
):
    connection = FakeConnection()
    browser = make_browser(connection)
    target_info = {"targetId": "pending-page", "type": "page", "url": ""}
    target = CdpTarget(
        browser,
        target_info,
        browser.browser_contexts[0],
        lambda: None,
        False,
        None,
        [],
        connection._loop,
    )
    browser._targets["pending-page"] = target
    assert target._is_initialized is False

    await browser.disconnect()

    assert connection.disposed is True
    assert await target._initialized_promise is False
