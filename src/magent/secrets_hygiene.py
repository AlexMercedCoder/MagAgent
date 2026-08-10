"""Secrets hygiene checks for `magent doctor`.

The audit turned up several findings that a user can only fix themselves:
plaintext API keys sitting in config, config files readable by other accounts,
and a gateway that admits everyone because its allowlist is empty. These are
exactly the sort of thing a doctor command should surface, so they are checks
rather than prose in a changelog.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any

__all__ = ["secrets_hygiene_report"]


def _world_or_group_readable(path: Path) -> bool:
    if os.name != "posix":
        return False
    try:
        mode = path.stat().st_mode
    except OSError:
        return False
    return bool(mode & (stat.S_IRGRP | stat.S_IROTH | stat.S_IWGRP | stat.S_IWOTH))


def _plaintext_key_providers(config: dict[str, Any]) -> list[str]:
    """Providers whose key is stored inline rather than in env or a keyring."""
    providers = config.get("providers") or {}
    if not isinstance(providers, dict):
        return []
    return sorted(
        name
        for name, entry in providers.items()
        if isinstance(entry, dict) and str(entry.get("api_key") or "").strip()
    )


def secrets_hygiene_report(username: str | None = None) -> dict[str, Any]:  # noqa: ARG001
    """Report credential-handling problems, each with the command that fixes it."""
    from magent.config import CONFIG_DIR, GLOBAL_CONFIG, load_global_config

    findings: list[dict[str, Any]] = []

    def add(key: str, ok: bool, detail: str, command: str = "", severity: str = "warning") -> None:
        findings.append(
            {
                "key": key,
                "ok": ok,
                "severity": "info" if ok else severity,
                "detail": detail,
                "command": command,
            }
        )

    try:
        config = load_global_config()
    except Exception as error:
        return {"ok": False, "error": f"Could not read the global config: {error}", "findings": []}

    # 1. Plaintext keys in config.
    plaintext = _plaintext_key_providers(config)
    add(
        "plaintext_api_keys",
        not plaintext,
        (
            f"API keys are stored in plaintext for: {', '.join(plaintext)}."
            if plaintext
            else "No plaintext API keys in the global config."
        ),
        f"magent auth add {plaintext[0]}" if plaintext else "",
        severity="high",
    )

    # 2. Config files other accounts can read.
    exposed = []
    for path in [GLOBAL_CONFIG, *sorted(Path(CONFIG_DIR).glob("users/*.toml"))]:
        if path.exists() and _world_or_group_readable(path):
            exposed.append(str(path))
    add(
        "config_permissions",
        not exposed,
        (
            f"Config files are readable by other accounts: {', '.join(exposed)}."
            if exposed
            else "Config files are owner-only."
        ),
        f"chmod 600 {exposed[0]}" if exposed else "",
        severity="high",
    )

    # 3. A gateway that admits everyone.
    gateway = config.get("gateway") or {}
    if isinstance(gateway, dict) and gateway:
        allowlist = gateway.get("allowed_user_ids") or []
        allow_anyone = bool(gateway.get("allow_anyone"))
        add(
            "gateway_allowlist",
            bool(allowlist) or not allow_anyone,
            (
                "gateway.allow_anyone is set with an empty allowlist: anyone who can "
                "reach the bot gets a headless agent on this machine."
                if allow_anyone and not allowlist
                else "Gateway access is restricted."
            ),
            "magent gateway configure --allow-user <id>",
            severity="high",
        )
        add(
            "gateway_persistent_approvals",
            not gateway.get("allow_persistent_approvals"),
            (
                "gateway.allow_persistent_approvals lets chat users write trusted shell "
                "patterns that also apply to local CLI sessions."
                if gateway.get("allow_persistent_approvals")
                else "Chat users cannot persist shell approvals."
            ),
            "",
        )

    return {
        "ok": all(item["ok"] for item in findings),
        "findings": findings,
        "problems": [item for item in findings if not item["ok"]],
    }
