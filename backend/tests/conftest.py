"""Shared pytest fixtures.

Tests run against the real code paths: a temporary SQLite store and the live
Agent Server when it is reachable. No LLM or agent behaviour is mocked.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from level5.config import get_settings  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _data_dir(tmp_path_factory):
    """Point the platform at a temporary data directory for the whole run."""
    data_dir = tmp_path_factory.mktemp("level5-data")
    os.environ["LEVEL5_DATA_DIR"] = str(data_dir)
    get_settings.cache_clear()
    yield data_dir
    get_settings.cache_clear()


@pytest.fixture
def settings(_data_dir):
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture
def store(tmp_path):
    from level5.storage.store import ProjectStore

    return ProjectStore(db_path=tmp_path / "test.db")
