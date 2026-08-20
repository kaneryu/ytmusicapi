from collections.abc import Awaitable, Callable
from typing import Any

JsonDict = dict[str, Any]
JsonList = list[JsonDict]

RequestFuncType = Callable[[str], Awaitable[JsonDict]]
RequestFuncBodyType = Callable[[JsonDict], Awaitable[JsonDict]]
ParseFuncType = Callable[[JsonList], JsonList]
ParseFuncDictType = Callable[[JsonDict], JsonDict]
