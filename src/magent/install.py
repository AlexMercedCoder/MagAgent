"""Install and update diagnostics."""

from __future__ import annotations

import os
import shutil
import sys
from typing import Any


def update_plan() -> dict[str, Any]:
    """Return the safest detected update command for this installation."""
    executable = sys.executable
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    pipx_home = os.environ.get("PIPX_HOME") or ""
    if shutil.which("pipx"):
        command = "pipx upgrade mag-agent"
        method = "pipx"
    elif in_venv:
        command = f"{executable} -m pip install --upgrade mag-agent"
        method = "venv-pip"
    else:
        py = "python3" if sys.platform == "darwin" and shutil.which("python3") else "python"
        command = f"{py} -m pip install --upgrade --user mag-agent"
        method = "user-pip"
    return {
        "ok": True,
        "method": method,
        "command": command,
        "python": executable,
        "in_venv": in_venv,
        "pipx_home": pipx_home,
    }
