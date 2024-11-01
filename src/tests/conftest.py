from __future__ import annotations

import shutil
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


@pytest.fixture
def cache_directory(tmp_path_factory: pytest.TempPathFactory):
    base = tmp_path_factory.getbasetemp()
    path = base / uuid.uuid4().hex
    try:
        yield path
    finally:
        shutil.rmtree(path)


@pytest.fixture
def fanoutcache_directory(tmp_path_factory: pytest.TempPathFactory):
    base = tmp_path_factory.getbasetemp()
    return base / uuid.uuid4().hex


@pytest.fixture
def cache(tmp_path_factory: pytest.TempPathFactory):
    base = tmp_path_factory.getbasetemp()
    cache = td.Cache(directory=base / uuid.uuid4().hex)
    try:
        yield cache
    finally:
        cache.close()
        shutil.rmtree(cache.directory)


@pytest.fixture
def fanout_cache(tmp_path_factory: pytest.TempPathFactory):
    base = tmp_path_factory.getbasetemp()
    cache = td.FanoutCache(directory=base / uuid.uuid4().hex)
    try:
        yield cache
    finally:
        cache.close()
        shutil.rmtree(cache.directory)


@pytest.fixture
def uid(worker_id) -> uuid.UUID:
    rand = uuid.uuid4().hex
    return uuid.uuid5(uuid.NAMESPACE_OID, f"{worker_id}:{rand}")
