from __future__ import annotations

import gettext
import json
import locale
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from functools import cached_property, partial
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING

import httpx
from httpx import Response

from ytmusicapi._headers import CaseInsensitiveDict

if TYPE_CHECKING:
    from typing_extensions import Self

from ytmusicapi.helpers import (
    SUPPORTED_LANGUAGES,
    SUPPORTED_LOCATIONS,
    YTM_BASE_API,
    YTM_PARAMS,
    YTM_PARAMS_KEY,
    build_async_client,
    get_authorization,
    get_visitor_id,
    initialize_context,
    initialize_headers,
    sapisid_from_cookie,
)
from ytmusicapi.mixins.browsing import BrowsingMixin
from ytmusicapi.mixins.charts import ChartsMixin
from ytmusicapi.mixins.explore import ExploreMixin
from ytmusicapi.mixins.library import LibraryMixin
from ytmusicapi.mixins.playlists import PlaylistsMixin
from ytmusicapi.mixins.podcasts import PodcastsMixin
from ytmusicapi.mixins.search import SearchMixin
from ytmusicapi.mixins.uploads import UploadsMixin
from ytmusicapi.mixins.watch import WatchMixin
from ytmusicapi.parsers.i18n import Parser

from .auth.auth_parse import determine_auth_type, parse_auth_str
from .auth.oauth import OAuthCredentials, RefreshingToken
from .auth.oauth.token import Token
from .auth.types import AuthType
from .exceptions import YTMusicServerError, YTMusicUserError
from .type_alias import JsonDict

#: client override that makes the API answer as if it were the Android mobile app
MOBILE_CLIENT = {"clientName": "ANDROID_MUSIC", "clientVersion": "7.21.50"}


class YTMusicBase:
    def __init__(
        self,
        auth: str | JsonDict | None = None,
        user: str | None = None,
        requests_session: httpx.AsyncClient | None = None,
        proxies: dict[str, str] | None = None,
        language: str = "en",
        locale_dir: str | Path | None = None,
        location: str = "",
        oauth_credentials: OAuthCredentials | None = None,
    ):
        """
        Create a new instance to interact with YouTube Music.

        :param auth: Optional. Provide a string, path to file, or oauth token dict.
          Authentication credentials are needed to manage your library.
          See :py:func:`setup` for how to fill in the correct credentials.
          Default: A default header is used without authentication.
        :param user: Optional. Specify a user ID string to use in requests.
          This is needed if you want to send requests on behalf of a brand account.
          Otherwise the default account is used. You can retrieve the user ID
          by going to https://myaccount.google.com/brandaccounts and selecting your brand account.
          The user ID will be in the URL: https://myaccount.google.com/b/user_id/
        :param requests_session: An ``httpx.AsyncClient`` or None to create one.
          Default clients have a request timeout of 30s, which produces an httpx.ReadTimeout.
          The timeout can be changed by passing your own client::

            client = httpx.AsyncClient(timeout=3, follow_redirects=True)
            ytm = YTMusic(requests_session=client)

          A client passed in this way is not closed by ``YTMusic``; you own its lifetime.

        :param proxies: Optional. Proxy configuration in requests_ format_, for example
            ``{"https": "http://localhost:8080"}``. Translated into per-scheme httpx mounts.
            Ignored when ``requests_session`` is provided - configure proxies on that client instead.

            .. _requests: https://requests.readthedocs.io/
            .. _format: https://requests.readthedocs.io/en/master/user/advanced/#proxies

        :param language: Optional. Can be used to change the language of returned data.
            English will be used by default. Available languages can be checked in
            the ytmusicapi/locales directory.
        :param location: Optional. Can be used to change the location of the user.
            No location will be set by default. This means it is determined by the server.
            Available languages can be checked in the FAQ.
        :param locale_dir: Optional. Path to a directory of gettext translations to use
            instead of the ones bundled with ytmusicapi.
        :param oauth_credentials: Optional. Used to specify a different oauth client to be
            used for authentication flow.
        """
        #: whether the session is ours to close - a caller-supplied client is left alone
        self._owns_session = requests_session is None
        #: request session for connection pooling
        self._session = self._prepare_session(requests_session, proxies)
        self.proxies: dict[str, str] | None = proxies  #: params for session modification
        # see google cookie docs: https://policies.google.com/technologies/cookies
        # value from https://github.com/yt-dlp/yt-dlp/blob/2023.09.24/yt_dlp/extractor/youtube.py#L502
        self.cookies = {"SOCS": "CAI"}
        # httpx deprecates per-request cookies, so they live on the client jar instead.
        # This also applies to a caller-supplied client, which needs the cookie to work.
        self._session.cookies.update(self.cookies)

        self._auth_headers: CaseInsensitiveDict[str] = CaseInsensitiveDict[str]()
        self.auth_type = AuthType.UNAUTHORIZED
        if auth is not None:
            self._auth_headers, auth_path = parse_auth_str(auth)
            self.auth_type = determine_auth_type(self._auth_headers)

            self._token: Token
            if self.auth_type == AuthType.OAUTH_CUSTOM_CLIENT:
                if oauth_credentials is None:
                    raise YTMusicUserError(
                        "oauth JSON provided via auth argument, but oauth_credentials not provided."
                        "Please provide oauth_credentials as specified in the OAuth setup documentation."
                    )
                # Filter unknown keys (e.g. ``refresh_token_expires_in`` from Google's
                # device flow) so previously saved oauth.json files load cleanly. See #921.
                token_kwargs = {k: self._auth_headers[k] for k in Token.members() if k in self._auth_headers}
                #: OAuth credential handler
                self._token = RefreshingToken(
                    credentials=oauth_credentials,
                    _local_cache=auth_path,
                    **token_kwargs,  # type: ignore[arg-type]
                )

        # prepare context
        self.context = initialize_context()

        if location:
            if location not in SUPPORTED_LOCATIONS:
                raise YTMusicUserError("Location not supported. Check the FAQ for supported locations.")
            self.context["context"]["client"]["gl"] = location

        if language not in SUPPORTED_LANGUAGES:
            raise YTMusicUserError(
                "Language not supported. Supported languages are " + (", ".join(SUPPORTED_LANGUAGES)) + "."
            )
        self.context["context"]["client"]["hl"] = language
        self.language = language
        try:
            locale.setlocale(locale.LC_ALL, self.language)
        except locale.Error:
            with suppress(locale.Error):
                locale.setlocale(locale.LC_ALL, "en_US.UTF-8")

        locale_dir = (
            Path(locale_dir).resolve()
            if locale_dir is not None
            else Path(__file__).parent.resolve() / "locales"
        )
        self.lang = gettext.translation("base", localedir=locale_dir, languages=[language])
        self.parser = Parser(self.lang)

        if user:
            self.context["context"]["user"]["onBehalfOfUser"] = user

        # sapisid, origin, and params all set once during init
        self.params = YTM_PARAMS
        if self.auth_type == AuthType.BROWSER:
            self.params += YTM_PARAMS_KEY
            try:
                cookie = self.base_headers["cookie"]
                self.sapisid = sapisid_from_cookie(cookie)
                self.origin: str = self.base_headers.get("origin", str(self.base_headers.get("x-origin")))
            except KeyError:
                raise YTMusicUserError("Your cookie is missing the required value __Secure-3PAPISID")

    @cached_property
    def base_headers(self) -> CaseInsensitiveDict[str]:
        headers = (
            self._auth_headers
            if self.auth_type == AuthType.BROWSER or self.auth_type == AuthType.OAUTH_CUSTOM_FULL
            else initialize_headers()
        )

        # NOTE: unlike upstream, the visitor id is *not* fetched here - it needs a network
        # round trip, which cannot be awaited from a cached_property. `_ensure_visitor_id`
        # fills it in on first request instead.
        return headers

    @property
    def headers(self) -> CaseInsensitiveDict[str]:
        headers = self.base_headers.copy()

        # keys updated each use, custom oauth implementations left untouched
        if self.auth_type == AuthType.BROWSER:
            headers["authorization"] = get_authorization(self.sapisid + " " + self.origin)

        # Do not set custom headers when using OAUTH_CUSTOM_FULL
        # Full headers are provided by the downstream client in this scenario.
        elif self.auth_type == AuthType.OAUTH_CUSTOM_CLIENT:
            headers["authorization"] = self._token.as_auth()
            headers["X-Goog-Request-Time"] = str(int(time.time()))

        return headers

    async def _ensure_visitor_id(self) -> None:
        """Fetch and cache the ``X-Goog-Visitor-Id`` header on first use.

        Upstream does this from the ``base_headers`` cached_property, which is impossible
        here because the fetch is a coroutine. It runs once, before the first request.
        """
        if "X-Goog-Visitor-Id" in self.base_headers:
            return

        self.base_headers.update(
            await get_visitor_id(partial(self._send_get_request, use_base_headers=True))
        )

    async def _ensure_token_fresh(self) -> None:
        """Refresh an expiring OAuth access token before it is read by the ``headers`` property."""
        if self.auth_type == AuthType.OAUTH_CUSTOM_CLIENT:
            await self._token.refresh_if_expiring()

    @contextmanager
    def as_mobile(self) -> Iterator[None]:
        """
        Disabled in the async port - raises :class:`NotImplementedError`.
        ----------------------------------------------------------------

        Upstream implements this by mutating ``self.context`` in place for the duration of
        the ``with`` block. That was already documented as not thread-safe; under asyncio it
        is worse, because any concurrently running task that issues a request inside the
        block silently gets mobile results, and one that outlives the block silently does
        not. There is no correct in-place version of this on a shared client.

        To reinstate it, thread the client override through as a per-request argument
        (``_send_request(..., context=...)``) rather than mutating shared state, or use a
        dedicated ``YTMusic`` instance configured for mobile.

        Upstream behaviour, for reference: temporarily changes the `context` to enable
        different results from the API, meant for the Android mobile-app. All calls inside
        the `with`-statement emulate mobile behavior.

        Example::

            with yt.as_mobile():
                await yt._send_request(...)  # results as mobile-app

            await yt._send_request(...)  # back to normal, like web-app

        """
        raise NotImplementedError(
            "as_mobile() is not supported in the async port: it mutates the shared request "
            "context in place, so concurrent tasks would interfere with each other. Pass the "
            "mobile context per-request, or use a separate YTMusic instance."
        )
        yield None  # pragma: no cover - unreachable; keeps this function a generator

    def _prepare_session(
        self, requests_session: httpx.AsyncClient | None, proxies: dict[str, str] | None = None
    ) -> httpx.AsyncClient:
        """Prepare an httpx client or use the user-provided one"""
        if isinstance(requests_session, httpx.AsyncClient):
            return requests_session
        return build_async_client(proxies)

    async def _send_request(
        self, endpoint: str, body: JsonDict, additionalParams: str = "", *, mobile: bool = False
    ) -> JsonDict:
        """Send a request to the YouTube Music API.

        :param mobile: emulate the Android mobile app for this request only. The override is
            built per call rather than mutated onto ``self.context``, so concurrent tasks are
            unaffected. This replaces upstream's ``as_mobile`` context manager.
        """
        await self._ensure_visitor_id()
        await self._ensure_token_fresh()

        context = self.context
        if mobile:
            context = {
                "context": {
                    **self.context["context"],
                    "client": {**self.context["context"]["client"], **MOBILE_CLIENT},
                }
            }

        body.update(context)

        response = await self._session.post(
            YTM_BASE_API + endpoint + self.params + additionalParams,
            json=body,
            headers=dict(self.headers),
        )
        response_text: JsonDict = json.loads(response.text)
        if response.status_code >= 400:
            message = (
                "Server returned HTTP " + str(response.status_code) + ": " + response.reason_phrase + ".\n"
            )
            error = response_text.get("error", {}).get("message")
            raise YTMusicServerError(message + error)
        return response_text

    async def _send_get_request(
        self, url: str, params: JsonDict | None = None, use_base_headers: bool = False
    ) -> Response:
        if not use_base_headers:
            # guard against recursion: the visitor-id fetch itself uses base headers
            await self._ensure_visitor_id()
            await self._ensure_token_fresh()

        response = await self._session.get(
            url,
            params=params,
            # handle first-use x-goog-visitor-id fetching
            headers=dict(initialize_headers() if use_base_headers else self.headers),
        )
        return response

    def _check_auth(self) -> None:
        """
        Checks if the user has provided authorization credentials

        Raises:
            YTMusicUserError: if the user is not authorized
        """
        if self.auth_type == AuthType.UNAUTHORIZED:
            raise YTMusicUserError("Please provide authentication before using this function")

    async def close(self) -> None:
        """Close the underlying httpx client, unless it was supplied by the caller."""
        if self._owns_session:
            await self._session.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        await self.close()
        return None


class YTMusic(
    YTMusicBase,
    BrowsingMixin,
    SearchMixin,
    WatchMixin,
    ChartsMixin,
    ExploreMixin,
    LibraryMixin,
    PlaylistsMixin,
    PodcastsMixin,
    UploadsMixin,
):
    """
    Allows automated interactions with YouTube Music by emulating the YouTube web client's requests.
    Permits both authenticated and non-authenticated requests.
    Authentication header data must be provided on initialization.
    """
