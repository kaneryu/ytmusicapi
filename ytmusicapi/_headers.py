"""Case-insensitive mapping used for HTTP headers.

Vendored from ``requests.structures`` (Apache License 2.0, Kenneth Reitz) so
that the async package does not depend on ``requests`` purely for this type.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterator, Mapping, MutableMapping
from typing import Any, TypeVar

_VT = TypeVar("_VT")


class CaseInsensitiveDict(MutableMapping[str, _VT]):
    """A case-insensitive ``dict``-like object.

    Implements all methods and operations of ``MutableMapping`` as well as
    ``copy``. All keys are expected to be strings. Iteration yields the keys
    with their original casing, while lookups are case-insensitive::

        headers = CaseInsensitiveDict[str]()
        headers["Accept"] = "application/json"
        headers["aCCEPT"] == "application/json"  # True
        list(headers) == ["Accept"]              # True
    """

    def __init__(self, data: Mapping[str, _VT] | Any = None, **kwargs: _VT) -> None:
        self._store: OrderedDict[str, tuple[str, _VT]] = OrderedDict()
        if data is None:
            data = {}
        self.update(data, **kwargs)

    def __setitem__(self, key: str, value: _VT) -> None:
        # the original key is stored alongside the value so that the casing
        # the caller used is preserved for iteration and serialization
        self._store[key.lower()] = (key, value)

    def __getitem__(self, key: str) -> _VT:
        return self._store[key.lower()][1]

    def __delitem__(self, key: str) -> None:
        del self._store[key.lower()]

    def __iter__(self) -> Iterator[str]:
        return (cased_key for cased_key, _ in self._store.values())

    def __len__(self) -> int:
        return len(self._store)

    def lower_items(self) -> Iterator[tuple[str, _VT]]:
        """Iterate over ``(lowercased_key, value)`` pairs."""
        return ((lower_key, cased_pair[1]) for lower_key, cased_pair in self._store.items())

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Mapping):
            return NotImplemented
        return dict(self.lower_items()) == dict(CaseInsensitiveDict(other).lower_items())

    def copy(self) -> CaseInsensitiveDict[_VT]:
        return CaseInsensitiveDict(dict(self._store.values()))

    def __repr__(self) -> str:
        return str(dict(self.items()))
