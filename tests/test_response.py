from __future__ import annotations

import inspect

import httpx

from mokr.constants import NETWORK_GET_RESPONSE_BODY
from mokr.cdp.network.response import CdpResponse
from mokr.core.http import HttpRequest, HttpResponse

from .conftest import FakeDevtoolsClient, FakeRequest


def make_response(client: FakeDevtoolsClient, **kwargs) -> CdpResponse:
    return CdpResponse(
        client=client,
        request=FakeRequest(),
        status=kwargs.pop("status", 200),
        headers=kwargs.pop("headers", {"Content-Type": "application/json"}),
        from_disk_cache=kwargs.pop("from_disk_cache", False),
        from_service_worker=kwargs.pop("from_service_worker", False),
        **kwargs,
    )


async def test_response_normalizes_metadata_and_decodes_json_body() -> None:
    client = FakeDevtoolsClient([{"body": '{"answer": 42}'}])
    response = make_response(
        client,
        status=201,
        headers={"X-Request-ID": "abc"},
        extra_info={
            "headers": {"X-From-Extra": "yes"},
            "headersText": "HTTP/1.1 201 Created\r\nX-From-Extra: yes\r\n",
        },
    )

    assert response.reason == "Created"
    assert response.extra_status_info == "Created"
    assert response.headers == {"x-from-extra": "yes"}
    assert await response.json() == {"answer": 42}
    assert client.calls == [
        (NETWORK_GET_RESPONSE_BODY, {"requestId": "request-1"})
    ]


async def test_response_decodes_base64_body() -> None:
    client = FakeDevtoolsClient([{"body": "aGVsbG8=", "base64Encoded": True}])
    response = make_response(client)

    assert await response.content() == "hello"


def test_only_http_response_exposes_the_underlying_httpx_response() -> None:
    request = httpx.Request("GET", "https://example.test")
    raw_response = httpx.Response(200, request=request)
    response = HttpResponse(raw_response, HttpRequest(request))

    assert "httpx_response" not in inspect.signature(CdpResponse).parameters
    assert not hasattr(CdpResponse, "httpx_response")
    assert response.httpx_response is raw_response
