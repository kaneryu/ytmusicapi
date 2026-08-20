import httpx
import pytest

from ytmusicapi import YTMusic
from ytmusicapi.exceptions import YTMusicUserError


async def test_ytmusic_context():
    async with YTMusic(requests_session=False) as yt:
        assert isinstance(yt, YTMusic)


def test_ytmusic_auth_error():
    with pytest.raises(YTMusicUserError, match="Invalid auth"):
        YTMusic(auth="def")


def test_ytmusic_session():
    test_session = httpx.AsyncClient(timeout=60)
    ytmusic = YTMusic(requests_session=test_session)
    assert ytmusic._session == test_session

    ytmusic = YTMusic()
    assert isinstance(ytmusic._session, httpx.AsyncClient)
    assert ytmusic._session != test_session


async def test_ytmusic_closes_only_its_own_session():
    """A caller-supplied client is the caller's to close; one we built is ours."""
    caller_session = httpx.AsyncClient()
    async with YTMusic(requests_session=caller_session) as yt:
        assert yt._owns_session is False
    assert caller_session.is_closed is False
    await caller_session.aclose()

    async with YTMusic() as yt:
        assert yt._owns_session is True
        own_session = yt._session
    assert own_session.is_closed is True


def test_ytmusic_proxies_become_mounts():
    """requests-style proxies dicts are translated into per-scheme httpx mounts."""
    ytmusic = YTMusic(proxies={"https": "http://localhost:8080"})
    patterns = {pattern.pattern for pattern in ytmusic._session._mounts}
    assert "https://" in patterns
