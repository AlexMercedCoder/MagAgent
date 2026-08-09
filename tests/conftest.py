from __future__ import annotations

from pathlib import Path

import pytest

import magent
from magent.tools.db import close_database_connections

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"


def pytest_sessionstart(session: pytest.Session) -> None:
    """Refuse to report success when pytest imported an installed MagAgent copy."""
    imported_from = Path(magent.__file__).resolve()
    if not imported_from.is_relative_to(SOURCE_ROOT):
        raise pytest.UsageError(
            f"Tests imported MagAgent from {imported_from}; expected checkout under {SOURCE_ROOT}"
        )


@pytest.fixture(autouse=True)
def close_test_database_connections():
    """Keep cached SQLite handles from leaking across test isolation boundaries."""
    yield
    close_database_connections()
