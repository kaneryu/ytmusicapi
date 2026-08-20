"""Offline tests for the async request path, driven by an httpx MockTransport.

These cover the pieces that changed shape in the sync->async port: the lazy visitor-id
bootstrap (upstream does it inside a cached_property, which cannot await) and the
error handling around httpx's response API.
"""

import json

import httpx
import pytest

from ytmusicapi import YTMusic
from ytmusicapi.exceptions import YTMusicServerError

VISITOR_PAGE = 'ytcfg.set({"VISITOR_DATA": "TESTVISITOR"});'


def make_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)


async def test_send_request_attaches_visitor_id_and_cookies():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "GET":
            return httpx.Response(200, text=VISITOR_PAGE)
        return httpx.Response(200, json={"contents": {"ok": True}})

    client = make_client(handler)
    async with YTMusic(requests_session=client) as yt:
        result = await yt._send_request("browse", {"browseId": "FEmusic_home"})

    assert result == {"contents": {"ok": True}}

    post = next(r for r in seen if r.method == "POST")
    assert post.headers["x-goog-visitor-id"] == "TESTVISITOR"
    assert "SOCS=CAI" in post.headers["cookie"]

    body = json.loads(post.content)
    assert body["browseId"] == "FEmusic_home"
    assert "context" in body  # context is merged into every request body

    await client.aclose()


async def test_visitor_id_is_fetched_only_once():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "GET":
            return httpx.Response(200, text=VISITOR_PAGE)
        return httpx.Response(200, json={})

    client = make_client(handler)
    async with YTMusic(requests_session=client) as yt:
        await yt._send_request("browse", {"browseId": "X"})
        await yt._send_request("browse", {"browseId": "Y"})

    assert len([r for r in seen if r.method == "GET"]) == 1
    await client.aclose()


async def test_send_request_raises_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, text=VISITOR_PAGE)
        return httpx.Response(403, json={"error": {"message": "denied"}})

    client = make_client(handler)
    async with YTMusic(requests_session=client) as yt:
        with pytest.raises(YTMusicServerError, match="denied"):
            await yt._send_request("browse", {"browseId": "X"})

    await client.aclose()


async def test_send_get_request_uses_base_headers_without_recursing():
    """The visitor-id bootstrap itself must not trigger another bootstrap."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text=VISITOR_PAGE)

    client = make_client(handler)
    async with YTMusic(requests_session=client) as yt:
        await yt._send_get_request("https://music.youtube.com/", use_base_headers=True)

    assert len(seen) == 1
    await client.aclose()


async def test_as_mobile_raises():
    """as_mobile is deliberately disabled: it mutated shared context in place."""
    async with YTMusic() as yt:
        with pytest.raises(NotImplementedError, match="not supported in the async port"):
            with yt.as_mobile():
                pass  # pragma: no cover


async def test_mobile_flag_is_per_request():
    """The Android client override must apply to one request and not leak into the next."""
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, text=VISITOR_PAGE)
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={})

    client = make_client(handler)
    async with YTMusic(requests_session=client) as yt:
        await yt._send_request("browse", {"browseId": "X"}, mobile=True)
        await yt._send_request("browse", {"browseId": "Y"})

    assert bodies[0]["context"]["client"]["clientName"] == "ANDROID_MUSIC"
    assert bodies[1]["context"]["client"]["clientName"] == "WEB_REMIX"
    # the shared context must be untouched
    assert yt.context["context"]["client"]["clientName"] == "WEB_REMIX"

    await client.aclose()
