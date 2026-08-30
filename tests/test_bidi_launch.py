from io import StringIO

from mokr.utils.launch import get_bidi_ws_endpoint


class FakeFirefoxProcess:
    def __init__(self, output: str) -> None:
        self.stdout = StringIO(output)

    def poll(self):
        return None


def test_firefox_bidi_endpoint_is_read_from_remote_agent_output() -> None:
    process = FakeFirefoxProcess(
        "WebDriver BiDi listening on ws://127.0.0.1:9222\n"
    )
    assert get_bidi_ws_endpoint(process) == "ws://127.0.0.1:9222/session"
