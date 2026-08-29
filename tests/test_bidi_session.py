from __future__ import annotations

from mokr.bidi.connection import BidiSession


class RecordingConnection:
    def __init__(self, responses) -> None:
        self.responses = iter(responses)
        self.calls = []

    async def send(self, method, params=None):
        self.calls.append((method, params))
        return next(self.responses)


async def test_bidi_session_uses_context_and_navigation_commands() -> None:
    connection = RecordingConnection(
        [
            {"userContext": "user-1"},
            {"context": "tab-1"},
            {"navigation": "nav-1", "url": "https://example.test/"},
        ]
    )
    session = BidiSession(connection)

    user_context = await session.create_user_context()
    page = await session.create_page(user_context)
    result = await session.navigate(page, "https://example.test/")

    assert user_context == "user-1"
    assert page == "tab-1"
    assert result["navigation"] == "nav-1"
    assert connection.calls == [
        ("browser.createUserContext", None),
        ("browsingContext.create", {"type": "tab", "userContext": "user-1"}),
        (
            "browsingContext.navigate",
            {
                "context": "tab-1",
                "url": "https://example.test/",
                "wait": "complete",
            },
        ),
    ]


async def test_bidi_session_evaluates_and_deserializes_primitive_values() -> (
    None
):
    connection = RecordingConnection(
        [{"type": "success", "result": {"type": "string", "value": "Mokr"}}]
    )
    session = BidiSession(connection)

    assert await session.evaluate("tab-1", "document.title") == "Mokr"
    assert connection.calls == [
        (
            "script.evaluate",
            {
                "expression": "document.title",
                "awaitPromise": True,
                "target": {"context": "tab-1"},
                "resultOwnership": "none",
            },
        )
    ]
