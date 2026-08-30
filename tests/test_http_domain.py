from __future__ import annotations

import httpx

from mokr.core.http import HttpDomain, HttpRequest, HttpResponse


async def test_http_domain_builds_protocol_neutral_redirect_chain() -> None:
    redirect_request = httpx.Request("GET", "https://example.test/start")
    redirect = httpx.Response(
        302,
        headers={"Location": "https://example.test/final"},
        request=redirect_request,
    )
    final_request = httpx.Request("GET", "https://example.test/final")
    final = httpx.Response(
        200,
        headers={"X-Result": "yes"},
        content=b"finished",
        request=final_request,
        history=[redirect],
    )
    domain = object.__new__(HttpDomain)

    response = await domain._transform_http_objs(final)

    assert isinstance(response, HttpResponse)
    assert isinstance(response.request, HttpRequest)
    assert response.url == "https://example.test/final"
    assert response.headers == {"x-result": "yes", "content-length": "8"}
    assert await response.content() == "finished"
    assert [request.url for request in response.request.redirect_chain] == [
        "https://example.test/start",
        "https://example.test/final",
    ]
    assert response.request.redirect_chain[-1].response is response


async def test_http_request_rejects_browser_interception_operations() -> None:
    request = HttpRequest(httpx.Request("GET", "https://example.test"))

    try:
        await request.abort()
    except ValueError as error:
        assert "HttpDomain-based requests" in str(error)
    else:
        raise AssertionError("HttpRequest.abort() should reject interception")
