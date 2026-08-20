import json
import locale
import re
import time
import unicodedata
from collections.abc import Awaitable, Callable
from hashlib import sha1
from http.cookies import SimpleCookie
from typing import Any

import httpx
from httpx import Response

from ytmusicapi._headers import CaseInsensitiveDict
from ytmusicapi.constants import *
from ytmusicapi.models.content.text_run import TextRun
from ytmusicapi.navigation import nav
from ytmusicapi.type_alias import JsonDict

#: default per-request timeout, matching the 30s upstream applies to its requests session
DEFAULT_TIMEOUT = 30.0


def build_async_client(
    proxies: dict[str, str] | None = None, timeout: float = DEFAULT_TIMEOUT
) -> httpx.AsyncClient:
    """Build an :class:`httpx.AsyncClient` configured to behave like the upstream requests session.

    ``follow_redirects`` is enabled explicitly because requests follows redirects by default
    while httpx does not. Proxies must be bound at construction time in httpx, so a
    requests-style ``{"http": ..., "https": ...}`` mapping is translated into per-scheme mounts.

    :param proxies: Optional. Proxy configuration in requests format.
    :param timeout: Optional. Per-request timeout in seconds.
    """
    mounts: dict[str, httpx.AsyncBaseTransport] | None = None
    if proxies:
        mounts = {f"{scheme}://": httpx.AsyncHTTPTransport(proxy=url) for scheme, url in proxies.items()}

    return httpx.AsyncClient(timeout=timeout, mounts=mounts, follow_redirects=True)


def initialize_headers() -> CaseInsensitiveDict[str]:
    return CaseInsensitiveDict(
        {
            "user-agent": USER_AGENT,
            "accept": "*/*",
            "accept-encoding": "gzip, deflate",
            "content-type": "application/json",
            "content-encoding": "gzip",
            "origin": YTM_DOMAIN,
        }
    )


def initialize_context() -> JsonDict:
    return {
        "context": {
            "client": {
                "clientName": "WEB_REMIX",
                "clientVersion": "1." + time.strftime("%Y%m%d", time.gmtime()) + ".01.00",
            },
            "user": {},
        }
    }


async def get_visitor_id(request_func: Callable[[str], Awaitable[Response]]) -> dict[str, str]:
    response = await request_func(YTM_DOMAIN)
    matches = re.findall(r"ytcfg\.set\s*\(\s*({.+?})\s*\)\s*;", response.text)
    visitor_id = ""
    if len(matches) > 0:
        ytcfg = json.loads(matches[0])
        visitor_id = ytcfg.get("VISITOR_DATA")
    return {"X-Goog-Visitor-Id": visitor_id}


def sapisid_from_cookie(raw_cookie: str) -> str:
    cookie = SimpleCookie()
    cookie.load(raw_cookie.replace('"', ""))
    return cookie["__Secure-3PAPISID"].value


# SAPISID Hash reverse engineered by
# https://stackoverflow.com/a/32065323/5726546
def get_authorization(auth: str) -> str:
    """Returns SAPISIDHASH value based on headers and current time

    :param auth: SAPISID and Origin value from headers concatenated with space
    """
    sha_1 = sha1()
    unix_timestamp = str(int(time.time()))
    sha_1.update((unix_timestamp + " " + auth).encode("utf-8"))
    return "SAPISIDHASH " + unix_timestamp + "_" + sha_1.hexdigest()


def to_int(string: str) -> int:
    """Attempts to cast a string to an integer using locale or Python int cast

    :param string: string that can be cast to an integer

    :return Integer if string is a valid integer

    :raise ValueError if string is not a valid integer
    """
    string = unicodedata.normalize("NFKD", string)
    number_string = re.sub(r"\D", "", string)
    try:
        int_value = locale.atoi(number_string)
    except ValueError:
        number_string = number_string.replace(",", "")
        int_value = int(number_string)
    return int_value


def sum_total_duration(item: JsonDict) -> int:
    if "tracks" not in item:
        return 0
    return sum(
        [
            track["duration_seconds"]
            if ("duration_seconds" in track and isinstance(track["duration_seconds"], int))
            else 0
            for track in item["tracks"]
        ]
    )


def parse_description_runs(descriptionRunsList: Any | None) -> tuple[str, list[TextRun]]:
    if not isinstance(descriptionRunsList, list):
        return "", []

    description_runs: list[TextRun] = []
    description = ""
    for run in descriptionRunsList:
        description += run["text"]

        # hashtag runs carry a searchEndpoint instead of an urlEndpoint - treat them as plain text
        link = nav(run, ["navigationEndpoint", "urlEndpoint", "url"], True)
        if link is not None:
            description_runs.append({"text": run["text"], "url": link})
        else:
            description_runs.append({"text": run["text"]})

    return description, description_runs
