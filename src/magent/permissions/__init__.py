"""Risk-tier permission model for MagAgent.

Tiers:
  0 — Silent  : auto-execute, no notification
  1 — Auto    : execute + show in audit trail
  2 — Confirm : show proposed action, press Enter to confirm
  3 — Block   : typed confirmation required

Modes:
  silent   — tiers 0-2 auto; only tier 3 prompts
  balanced — tier 0-1 auto; tier 2 confirms; tier 3 blocks/prompts  (default)
  paranoid — tier 0 auto; all others prompt
  yolo     — everything auto (tier 3 shown but one-key confirm)
"""

from __future__ import annotations

import fnmatch
import re
from enum import IntEnum
from typing import NamedTuple

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

console = Console()


class RiskTier(IntEnum):
    SILENT = 0
    AUTO = 1
    CONFIRM = 2
    BLOCK = 3


TIER_LABELS = {
    RiskTier.SILENT: "[dim]silent[/dim]",
    RiskTier.AUTO: "[green]auto[/green]",
    RiskTier.CONFIRM: "[yellow]confirm[/yellow]",
    RiskTier.BLOCK: "[red]block[/red]",
}

# ─────────────────────────────────────────────
# Shell command classifier
# ─────────────────────────────────────────────

# Patterns that are always tier 0 (silent reads)
_SILENT_PATTERNS: list[str] = [
    "git status", "git log*", "git diff*", "git show*", "git branch*",
    "ls*", "cat *", "head *", "tail *", "wc *", "find * -name*",
    "echo *", "pwd", "whoami", "which *", "type *",
    "rg *", "grep *", "fd *", "bat *",
]

# Patterns that are tier 1 (auto with audit)
_AUTO_PATTERNS: list[str] = [
    "git add*", "git commit*", "git stash*", "git checkout*", "git switch*",
    "git restore*", "git reset --soft*", "git reset --mixed*",
    "npm install*", "npm run*", "npm test*", "npm ci*",
    "yarn *", "pnpm *",
    "pip install*", "pip uninstall*", "uv *",
    "cargo build*", "cargo test*", "cargo run*", "cargo check*", "cargo fmt*",
    "cargo clippy*",
    "pytest*", "python -m pytest*",
    "make *",
    "docker build*", "docker run*", "docker compose up*", "docker compose down*",
    "go build*", "go test*", "go run*",
]

# Patterns that are tier 2 (require confirm)
_CONFIRM_PATTERNS: list[str] = [
    "git push*", "git pull*", "git fetch*", "git merge*", "git rebase*",
    "git reset --hard*", "git clean*",
    "curl *", "wget *", "httpie *",
    "ssh *", "scp *",
    "docker push*", "docker pull*",
    "npm publish*", "pip install --upgrade*",
    "chmod *", "chown *",
]

# Anything matching these is always tier 3
_BLOCK_PATTERNS: list[str] = [
    "rm -rf*", "rm -r*", "rmdir*",
    "sudo *", "su *",
    "mkfs*", "fdisk*", "parted*",
    "dd if=*", "shred *",
    "> /etc/*", ">> /etc/*",
    "systemctl*", "service *",
    "iptables*", "ufw *",
    "passwd *", "useradd*", "userdel*",
    "crontab*",
    "kill -9*", "killall*",
    "nc -l*", "ncat*",
]


def _matches_any(cmd: str, patterns: list[str]) -> bool:
    cmd_lower = cmd.strip().lower()
    return any(fnmatch.fnmatch(cmd_lower, p.lower()) for p in patterns)


def classify_shell_command(
    cmd: str,
    allowlist: list[str] | None = None,
) -> RiskTier:
    """Return the risk tier for a shell command string."""
    # User allowlist trumps everything (tier 1 at most for auditing)
    if allowlist and _matches_any(cmd, allowlist):
        return RiskTier.AUTO

    if _matches_any(cmd, _BLOCK_PATTERNS):
        return RiskTier.BLOCK
    if _matches_any(cmd, _CONFIRM_PATTERNS):
        return RiskTier.CONFIRM
    if _matches_any(cmd, _AUTO_PATTERNS):
        return RiskTier.AUTO
    if _matches_any(cmd, _SILENT_PATTERNS):
        return RiskTier.SILENT
    # Unknown commands default to CONFIRM
    return RiskTier.CONFIRM


# ─────────────────────────────────────────────
# File operation tiers
# ─────────────────────────────────────────────

def classify_file_op(op: str, path: str, cwd: str) -> RiskTier:
    """Classify a file operation by type and path."""
    import os
    abs_path = os.path.abspath(os.path.join(cwd, path))
    in_cwd = abs_path.startswith(os.path.abspath(cwd))

    if op == "read":
        return RiskTier.SILENT
    if op in ("write", "edit", "create"):
        return RiskTier.AUTO if in_cwd else RiskTier.CONFIRM
    if op == "delete":
        return RiskTier.CONFIRM if in_cwd else RiskTier.BLOCK
    return RiskTier.CONFIRM


# ─────────────────────────────────────────────
# Permission gate
# ─────────────────────────────────────────────

class PermissionResult(NamedTuple):
    approved: bool
    tier: RiskTier
    reason: str


def check_permission(
    action_description: str,
    tier: RiskTier,
    mode: str = "balanced",
) -> PermissionResult:
    """
    Evaluate whether an action should proceed based on its tier and the active mode.

    Returns PermissionResult(approved, tier, reason).
    """
    # Determine effective approval threshold by mode
    auto_threshold = {
        "silent": RiskTier.BLOCK,    # 0-2 auto, only 3 prompts
        "balanced": RiskTier.CONFIRM, # 0-1 auto, 2 confirms, 3 blocks
        "paranoid": RiskTier.AUTO,    # 0 auto, 1+ prompts
        "yolo": RiskTier.BLOCK + 1,  # everything auto
    }.get(mode, RiskTier.CONFIRM)

    # YOLO: always approve
    if mode == "yolo":
        if tier == RiskTier.BLOCK:
            # Still show the action but use a one-key confirm
            console.print(
                Panel(
                    f"[bold red]⚠ HIGH RISK ACTION[/bold red]\n{action_description}",
                    border_style="red",
                )
            )
            ans = Prompt.ask("[red]YOLO mode — proceed?[/red] [y/N]", default="y")
            return PermissionResult(ans.lower() in ("y", "yes"), tier, "yolo-prompt")
        return PermissionResult(True, tier, "yolo-auto")

    # Auto-approve below threshold
    if tier < auto_threshold:
        return PermissionResult(True, tier, "auto")

    # CONFIRM tier — show action, press Enter
    if tier == RiskTier.CONFIRM:
        console.print(
            Panel(
                f"[bold yellow]⚡ Action requires confirmation[/bold yellow]\n\n"
                f"[white]{action_description}[/white]",
                border_style="yellow",
                title="[yellow]Permission[/yellow]",
            )
        )
        approved = Confirm.ask("[yellow]Proceed?[/yellow]", default=True)
        return PermissionResult(approved, tier, "user-confirmed" if approved else "user-denied")

    # BLOCK tier — require typed confirmation
    if tier == RiskTier.BLOCK:
        console.print(
            Panel(
                f"[bold red]🛑 HIGH RISK ACTION — requires explicit confirmation[/bold red]\n\n"
                f"[white]{action_description}[/white]",
                border_style="red",
                title="[red]⚠ Permission Required[/red]",
            )
        )
        ans = Prompt.ask(
            '[red]Type "yes" to confirm, anything else to cancel[/red]',
            default="no",
        )
        approved = ans.strip().lower() == "yes"
        return PermissionResult(approved, tier, "user-confirmed" if approved else "user-denied")

    return PermissionResult(True, tier, "auto")
