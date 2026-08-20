import json
import tempfile
import time
from pathlib import Path
from unittest import mock

import httpx
import pytest

from ytmusicapi.auth.oauth import OAuthToken, RefreshingToken
from ytmusicapi.auth.types import AuthType
from ytmusicapi.exceptions import YTMusicUserError
from ytmusicapi.setup import main
from ytmusicapi.type_alias import JsonDict
from ytmusicapi.ytmusic import OAuthCredentials, YTMusic


@pytest.fixture(name="blank_code")
def fixture_blank_code() -> JsonDict:
    return {
        "device_code": "",
        "user_code": "",
        "expires_in": 1800,
        "interval": 5,
        "verification_url": "https://www.google.com/device",
    }


@pytest.fixture(name="alt_oauth_credentials")
def fixture_alt_oauth_credentials(config) -> OAuthCredentials:
    return OAuthCredentials(config["auth"]["client_id"], config["auth"]["client_secret"])


@pytest.fixture(name="yt_alt_oauth")
def fixture_yt_alt_oauth(browser_filepath: str, alt_oauth_credentials: OAuthCredentials) -> YTMusic:
    return YTMusic(browser_filepath, oauth_credentials=alt_oauth_credentials)


class TestOAuth:
    @mock.patch("httpx.Response.json")
    @mock.patch("httpx.AsyncClient.post", new_callable=mock.AsyncMock)
    def test_setup_oauth(self, session_mock, json_mock, blank_code, config):
        session_mock.return_value = httpx.Response(200)
        token_code = json.loads(config["auth"]["oauth_token"])
        json_mock.side_effect = [blank_code, token_code]
        with tempfile.NamedTemporaryFile(delete=False) as f:
            oauth_filepath = f.name
        with (
            mock.patch("builtins.input", return_value="y"),
            mock.patch(
                "sys.argv",
                [
                    "ytmusicapi",
                    "oauth",
                    "--file",
                    oauth_filepath,
                    "--client-id",
                    "test_id",
                    "--client-secret",
                    "test_secret",
                ],
            ),
            mock.patch("webbrowser.open"),
        ):
            # main() stays synchronous - it drives the async flow via asyncio.run internally
            main()
            assert Path(oauth_filepath).exists()

        json_mock.side_effect = None
        with open(oauth_filepath, encoding="utf8") as oauth_file:
            oauth_token = json.loads(oauth_file.read())

        assert oauth_token["expires_at"] != 0
        assert OAuthToken.is_oauth(oauth_token)

        oauth_file.close()
        Path(oauth_file.name).unlink()

    async def test_setup_oauth_uses_refresh_token_expiration(self, blank_code):
        credentials = mock.AsyncMock()
        credentials.get_code.return_value = blank_code
        credentials.token_from_code.return_value = {
            "access_token": "test_access_token",
            "expires_in": 3600,
            "refresh_token": "test_refresh_token",
            "scope": "https://www.googleapis.com/auth/youtube",
            "token_type": "Bearer",
            "refresh_token_expires_in": 604799,
        }

        with (
            mock.patch("builtins.input", return_value=""),
            mock.patch("ytmusicapi.auth.oauth.token.time.time", return_value=1000),
        ):
            token = await RefreshingToken.prompt_for_token(credentials)
            assert token.access_token == "test_access_token"
            assert token.refresh_token == "test_refresh_token"
            assert token.expires_at == 4600
            assert token.expires_in == 604799
            assert not hasattr(token, "refresh_token_expires_in")

    async def test_refreshing_token_refreshes_when_expiring(self):
        """An expiring token is refreshed through the explicit async hook.

        Upstream refreshes lazily inside ``__getattribute__``, which cannot await a
        coroutine; ``refresh_if_expiring`` replaces it and is awaited by ``YTMusic``
        before every request.
        """
        credentials = mock.AsyncMock(spec=OAuthCredentials)
        credentials.refresh_token.return_value = {"access_token": "new_access", "expires_in": 3600}
        token = RefreshingToken(
            credentials=credentials,
            access_token="old_access",
            refresh_token="test_refresh_token",
            scope="https://www.googleapis.com/auth/youtube",
            token_type="Bearer",
            expires_at=int(time.time()),  # already expiring
        )

        assert token.is_expiring
        await token.refresh_if_expiring()

        credentials.refresh_token.assert_awaited_once_with("test_refresh_token")
        assert token.access_token == "new_access"
        assert token.expires_at > time.time() + 60
        assert not token.is_expiring

    async def test_refreshing_token_left_alone_when_fresh(self):
        credentials = mock.AsyncMock(spec=OAuthCredentials)
        token = RefreshingToken(
            credentials=credentials,
            access_token="still_good",
            refresh_token="test_refresh_token",
            scope="https://www.googleapis.com/auth/youtube",
            token_type="Bearer",
            expires_at=int(time.time()) + 3600,
        )

        await token.refresh_if_expiring()

        credentials.refresh_token.assert_not_awaited()
        assert token.access_token == "still_good"

    async def test_ytmusic_refreshes_token_before_request(self):
        """YTMusic must await the refresh hook so callers never see a stale token."""
        credentials = mock.AsyncMock(spec=OAuthCredentials)
        token_dict = {
            "scope": "https://www.googleapis.com/auth/youtube",
            "token_type": "Bearer",
            "access_token": "test_access_token",
            "refresh_token": "test_refresh_token",
            "expires_at": int(time.time()) + 3600,
            "expires_in": 3600,
        }
        yt = YTMusic(token_dict, oauth_credentials=credentials)
        yt._token = mock.AsyncMock(spec=RefreshingToken)

        await yt._ensure_token_fresh()

        yt._token.refresh_if_expiring.assert_awaited_once()

    def test_oauth_token_dict_ignores_unexpected_fields(self):
        """Regression for #887 / #921: a saved oauth.json may contain extra
        fields like ``refresh_token_expires_in`` (added to Google's device-flow
        response). Loading such a token via ``YTMusic`` must not crash on the
        strict Token dataclass.
        """
        credentials = mock.Mock(spec=OAuthCredentials)
        token_dict = {
            "scope": "https://www.googleapis.com/auth/youtube",
            "token_type": "Bearer",
            "access_token": "test_access_token",
            "refresh_token": "test_refresh_token",
            "expires_at": int(time.time()) + 3600,
            "expires_in": 3600,
            "refresh_token_expires_in": 604799,
        }

        yt = YTMusic(token_dict, oauth_credentials=credentials)

        assert yt.auth_type == AuthType.OAUTH_CUSTOM_CLIENT
        assert yt._token is not None
        assert yt._token.refresh_token == "test_refresh_token"
        assert not hasattr(yt._token, "refresh_token_expires_in")

    def test_from_json_missing_file_raises_filenotfound(self, tmp_path):
        """Regression for #954: loading a non-existent path should raise
        FileNotFoundError naming the path, not UnboundLocalError.
        """
        missing = tmp_path / "does-not-exist.json"
        with pytest.raises(FileNotFoundError):
            OAuthToken.from_json(missing)

    @pytest.mark.skip(reason="oauth is currently not working, see #813")
    async def test_oauth_tokens(self, oauth_filepath: str, yt_oauth: YTMusic):
        # ensure instance initialized token
        assert yt_oauth._token is not None

        # set reference file
        with open(oauth_filepath, encoding="utf-8") as f:  # noqa: ASYNC230 - skipped integration test
            first_json = json.load(f)

        # pull reference values from underlying token
        first_token = yt_oauth._token.access_token
        first_expire = yt_oauth._token.expires_at
        # make token expire
        yt_oauth._token.expires_at = int(time.time())
        # check
        assert yt_oauth._token.is_expiring
        # pull new values; refreshing is now explicit rather than on attribute access
        await yt_oauth._token.refresh_if_expiring()
        second_token = yt_oauth._token.access_token
        second_expire = yt_oauth._token.expires_at
        second_token_inner = yt_oauth._token.access_token
        # check it was refreshed
        assert first_token != second_token
        # check expiration timestamps to confirm
        assert second_expire != first_expire
        assert second_expire > time.time() + 60
        # check token is propagating properly
        assert second_token == second_token_inner

        with open(oauth_filepath, encoding="utf-8") as f2:  # noqa: ASYNC230 - skipped integration test
            second_json = json.load(f2)

        # ensure token is updating local file
        assert first_json != second_json

    def test_oauth_custom_client(
        self, alt_oauth_credentials: OAuthCredentials, oauth_filepath: str, yt_alt_oauth: YTMusic
    ):
        # ensure client works/ignores alt if browser credentials passed as auth
        assert yt_alt_oauth.auth_type != AuthType.OAUTH_CUSTOM_CLIENT
        with open(oauth_filepath, encoding="utf-8") as f:
            token_dict = json.load(f)

        # oauth token dict entry and alt
        yt_alt_oauth = YTMusic(token_dict, oauth_credentials=alt_oauth_credentials)
        assert yt_alt_oauth.auth_type == AuthType.OAUTH_CUSTOM_CLIENT

        # forgot to pass OAuth credentials - should raise
        with pytest.raises(YTMusicUserError):
            YTMusic(token_dict)

        # oauth custom full
        token_dict["authorization"] = "Bearer DKLEK23"
        yt_alt_oauth = YTMusic(token_dict, oauth_credentials=alt_oauth_credentials)
        assert yt_alt_oauth.auth_type == AuthType.OAUTH_CUSTOM_FULL

    async def test_alt_oauth_request(self, yt_alt_oauth: YTMusic, sample_video):
        await yt_alt_oauth.get_watch_playlist(sample_video)
