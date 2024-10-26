from __future__ import annotations

import uuid
from typing import Any

import pytest

import typed_diskcache as td


@pytest.fixture(
    params=[
        pytest.param(("asyncio", {"use_uvloop": False}), id="asyncio"),
        pytest.param(("asyncio", {"use_uvloop": True}), id="asyncio-uvloop"),
    ],
    scope="session",
)
def anyio_backend(request: pytest.FixtureRequest) -> tuple[str, dict[str, Any]]:
    return request.param


@pytest.fixture(scope="session")
def cache(tmp_path_factory: pytest.TempPathFactory):
    base = tmp_path_factory.getbasetemp()
    directory = base / uuid.uuid4().hex
    return td.Cache(directory=directory)


@pytest.fixture(scope="session")
def fanout_cache(tmp_path_factory: pytest.TempPathFactory):
    base = tmp_path_factory.getbasetemp()
    directory = base / uuid.uuid4().hex
    return td.FanoutCache(directory=directory)
