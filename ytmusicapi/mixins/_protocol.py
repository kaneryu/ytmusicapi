"""protocol that defines the functions available to mixins"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Protocol

from aiohttp import ClientResponse
from requests.structures import CaseInsensitiveDict

from ytmusicapi.auth.types import AuthType
from ytmusicapi.parsers.i18n import Parser
from ytmusicapi.type_alias import JsonDict


class MixinProtocol(Protocol):
    """protocol that defines the functions available to mixins"""

    auth_type: AuthType

    parser: Parser

    proxies: dict[str, str] | None

    def _check_auth(self) -> None:
        """checks if self has authentication"""

    async def _send_request(self, endpoint: str, body: JsonDict, additionalParams: str = "") -> JsonDict:
        """for sending post requests to YouTube Music"""

    async def _send_get_request(self, url: str, params: JsonDict | None = None) -> ClientResponse:
        """for sending get requests to YouTube Music"""

    @contextmanager
    def as_mobile(self) -> Iterator[None]:
        """context-manager, that allows requests as the YouTube Music Mobile-App"""

    @property
    def headers(self) -> CaseInsensitiveDict[str]:
        """property for getting request headers"""
