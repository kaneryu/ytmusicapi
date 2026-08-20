"""Test fixtures to make life easier."""

import json
from pathlib import Path
from typing import Any

import pytest


def load_json_fixture(path: Path) -> Any:
    """Read a JSON fixture from disk.

    Kept as a plain sync function so async tests can call it without tripping ruff's
    ASYNC rules about blocking I/O inside coroutines.
    """
    return json.loads(path.read_text(encoding="utf8"))


@pytest.fixture(name="repo_path")
def fixture_repo_path(request: pytest.FixtureRequest) -> Path:
    return request.config.rootpath


@pytest.fixture(name="tests_base_path")
def fixture_tests_base_path(request: pytest.FixtureRequest) -> Path:
    return request.config.rootpath / "tests"


@pytest.fixture(name="data_path")
def fixture_data_path(tests_base_path: Path) -> Path:
    return tests_base_path / "data"
