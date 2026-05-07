"""pytest 공용 fixture."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    """임시 SQLite DB 경로."""
    return tmp_path / "test.db"
