from __future__ import annotations

import os
import tempfile
from pathlib import Path

# Tests must never read or write the developer's real ~/.config/magent. The
# config paths are module constants computed from Path.home() at import time,
# so HOME is pointed at a throwaway directory before magent is imported. Each
# xdist worker gets its own. Set MAGENT_TEST_REAL_HOME=1 to opt out.
if not os.environ.get("MAGENT_TEST_REAL_HOME"):
    _real_home = Path.home()
    os.environ.setdefault(
        "PLAYWRIGHT_BROWSERS_PATH", str(_real_home / ".cache" / "ms-playwright")
    )
    _test_home = Path(tempfile.mkdtemp(prefix="magent-test-home-"))
    (_test_home / ".gitconfig").write_text(
        "[user]\n\tname = MagAgent Tests\n\temail = tests@magagent.invalid\n"
        "[init]\n\tdefaultBranch = main\n",
        encoding="utf-8",
    )
    os.environ["HOME"] = str(_test_home)
    os.environ["USERPROFILE"] = str(_test_home)
    for _variable in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
        os.environ.pop(_variable, None)

import pytest  # noqa: E402

import magent  # noqa: E402
from magent.tools.db import close_database_connections  # noqa: E402

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
