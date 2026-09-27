"""Team (shared) MagGraph with review-gated merge.

A team graph is a Git repository of MagGraph Markdown nodes that several people
share: a hosted remote, or a bare repository on a shared or network drive
(`magent memory team init --create /shared/team-memory.git`). Nobody writes to
its ``main`` branch directly:

1. ``propose`` copies nodes from your personal graph onto a branch
   ``proposals/<user>/<id>`` and pushes it;
2. teammates see it in the review inbox (``magent memory team inbox`` or the Web
   UI) with a node-level diff and automatic checks (valid node front matter, no
   secrets, size limits);
3. a *different* person accepts it (merged with ``--no-ff`` into ``main``) or
   rejects it; both are recorded in ``REVIEWS.jsonl`` on ``main``.

Each member keeps a local clone under
``~/.config/magent/users/<user>/team/<name>/``. When ``memory.team.recall`` is
on, sessions also recall from that clone's ``main`` (reviewed nodes only), and
memory evidence labels those nodes ``source: team``.

Identity is the MagAgent user name written as the Git author. It is not
authentication: who may push, and so who may review, is governed by access to
the Git remote.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from magent.config import USERS_DIR

PROPOSAL_PREFIX = "proposals/"
REVIEWS_FILE = "REVIEWS.jsonl"
NODES_DIR = "nodes"
MAX_NODE_BYTES = 64 * 1024
MAX_NODES_PER_PROPOSAL = 50
GIT_TIMEOUT = 120
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,120}$")


class TeamMemoryError(RuntimeError):
    """A team-memory operation that cannot proceed; the message says what to do."""


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class TeamMemory:
    def __init__(self, username: str, *, name: str = "team", root: Path | None = None) -> None:
        if not _ID.match(name):
            raise TeamMemoryError("Team names use letters, digits, '.', '_' or '-'.")
        self.username = username
        self.name = name
        self.root = root or (USERS_DIR / username / "team" / name)

    # ----------------------------------------------------------------- git

    def _git(self, *args: str, cwd: Path | None = None, check: bool = True) -> str:
        command = [
            "git",
            "-c",
            f"user.name={self.username}",
            "-c",
            f"user.email={self.username}@users.magagent.invalid",
            "-c",
            "init.defaultBranch=main",
            "-c",
            "commit.gpgsign=false",
            *args,
        ]
        result = subprocess.run(  # noqa: S603 - fixed git argv
            command,
            cwd=cwd or self.root,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,
            check=False,
        )
        if check and result.returncode != 0:
            raise TeamMemoryError(
                f"git {' '.join(args[:2])} failed: {(result.stderr or result.stdout).strip()[:500]}"
            )
        return result.stdout

    @property
    def configured(self) -> bool:
        return (self.root / ".git").is_dir()

    def _require(self) -> None:
        if not self.configured:
            raise TeamMemoryError(
                "No team memory is set up. Run `magent memory team init <git-url-or-path>` "
                "(or `--create <path>` to start a shared repository)."
            )

    @property
    def nodes_dir(self) -> Path:
        return self.root / NODES_DIR

    # ---------------------------------------------------------------- setup

    def init(self, remote: str, *, create: bool = False) -> dict[str, Any]:
        """Clone the team repository (creating a bare one first with ``create``)."""

        if self.configured:
            raise TeamMemoryError(
                f"Team memory '{self.name}' already exists at {self.root}. "
                "Use `magent memory team status`."
            )
        if create:
            target = Path(remote).expanduser()
            if target.exists() and any(target.iterdir()):
                raise TeamMemoryError(f"{target} is not empty; choose a new path for --create.")
            target.mkdir(parents=True, exist_ok=True)
            self._git("init", "--bare", "--initial-branch=main", str(target), cwd=target.parent)
            remote = str(target.resolve())
        self.root.parent.mkdir(parents=True, exist_ok=True)
        self._git("clone", remote, str(self.root), cwd=self.root.parent)
        if not self._git("branch", "-r", check=False).strip():
            # An empty repository: seed main so proposals have a base.
            self.nodes_dir.mkdir(parents=True, exist_ok=True)
            (self.nodes_dir / ".gitkeep").write_text("", encoding="utf-8")
            (self.root / "maggraph.toml").write_text(
                '[storage]\nmode = "local"\nroot_path = "nodes"\n', encoding="utf-8"
            )
            (self.root / "README.md").write_text(
                "# Team memory\n\nShared MagGraph nodes. Changes arrive as reviewed proposals "
                "(`magent memory team inbox`); do not commit to main directly.\n",
                encoding="utf-8",
            )
            (self.root / REVIEWS_FILE).write_text("", encoding="utf-8")
            self._git("checkout", "-B", "main")
            self._git("add", "-A")
            self._git("commit", "-m", "Start team memory")
            self._git("push", "-u", "origin", "main")
        return self.status()

    def status(self) -> dict[str, Any]:
        self._require()
        remote = self._git("remote", "get-url", "origin").strip()
        return {
            "ok": True,
            "name": self.name,
            "remote": remote,
            "clone": str(self.root),
            "nodes": len(self._node_files(self.nodes_dir)),
            "pending_proposals": len(self._proposal_branches(fetch=False)),
        }

    def sync(self) -> dict[str, Any]:
        """Fast-forward the local clone's main to the team's reviewed main."""

        self._require()
        self._git("fetch", "--prune", "origin")
        self._git("checkout", "main")
        self._git("merge", "--ff-only", "origin/main")
        return self.status()

    # ------------------------------------------------------------ proposals

    @staticmethod
    def _node_files(directory: Path) -> list[Path]:
        if not directory.is_dir():
            return []
        return sorted(path for path in directory.rglob("*.md") if path.is_file())

    def validate_node(self, text: str, *, filename: str) -> list[str]:
        """Problems that block a node from the team graph (empty list = fine)."""

        from magent.secret_scrub import scrub_secrets

        problems: list[str] = []
        if len(text.encode("utf-8")) > MAX_NODE_BYTES:
            problems.append(f"{filename}: larger than {MAX_NODE_BYTES // 1024} KiB")
        match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
        if not match:
            problems.append(f"{filename}: missing MagGraph front matter")
        else:
            header = match.group(1)
            if not re.search(r"^id:\s*\S", header, re.MULTILINE):
                problems.append(f"{filename}: front matter has no id")
            if not re.search(r"^type:\s*\S", header, re.MULTILINE):
                problems.append(f"{filename}: front matter has no type")
        if scrub_secrets(text) != text:
            problems.append(f"{filename}: looks like it contains a secret; remove it first")
        return problems

    def propose(
        self,
        node_ids: list[str],
        *,
        personal_dir: Path,
        message: str = "",
    ) -> dict[str, Any]:
        """Push selected personal nodes as a proposal branch."""

        self._require()
        if not node_ids:
            raise TeamMemoryError("Name at least one memory node to propose.")
        if len(node_ids) > MAX_NODES_PER_PROPOSAL:
            raise TeamMemoryError(f"Propose at most {MAX_NODES_PER_PROPOSAL} nodes at once.")
        index = {path.stem: path for path in self._node_files(personal_dir)}
        missing = [node for node in node_ids if node not in index]
        if missing:
            raise TeamMemoryError(
                "Not in your memory graph: " + ", ".join(missing) + ". "
                "Find ids with `magent memory search`."
            )
        problems: list[str] = []
        texts = {}
        for node in node_ids:
            text = index[node].read_text(encoding="utf-8")
            problems.extend(self.validate_node(text, filename=f"{node}.md"))
            texts[node] = text
        if problems:
            raise TeamMemoryError("Cannot propose: " + "; ".join(problems))
        proposal_id = uuid.uuid4().hex[:10]
        branch = f"{PROPOSAL_PREFIX}{self.username}/{proposal_id}"
        self._git("fetch", "origin")
        self._git("checkout", "-B", branch, "origin/main")
        try:
            self.nodes_dir.mkdir(parents=True, exist_ok=True)
            for node, text in texts.items():
                (self.nodes_dir / f"{node}.md").write_text(text, encoding="utf-8")
            self._git("add", NODES_DIR)
            summary = message.strip() or f"Propose {len(node_ids)} memory node(s)"
            body = (
                f"{summary}\n\nMagent-Proposal: {proposal_id}\nMagent-Author: {self.username}\n"
                f"Magent-Nodes: {','.join(node_ids)}\n"
            )
            if not self._git("status", "--porcelain").strip():
                raise TeamMemoryError("The team graph already has these nodes unchanged.")
            self._git("commit", "-m", body)
            self._git("push", "-u", "origin", branch)
        finally:
            self._git("checkout", "main", check=False)
        return {"ok": True, "id": proposal_id, "branch": branch, "nodes": node_ids}

    def _proposal_branches(self, *, fetch: bool = True) -> list[str]:
        if fetch:
            self._git("fetch", "--prune", "origin")
        refs = self._git(
            "for-each-ref", "--format=%(refname:short)", f"refs/remotes/origin/{PROPOSAL_PREFIX}"
        )
        return [ref.removeprefix("origin/") for ref in refs.split() if ref.strip()]

    def _trailers(self, ref: str) -> dict[str, str]:
        body = self._git("log", "-1", "--format=%B", ref)
        return dict(re.findall(r"^Magent-([A-Za-z]+):\s*(.+)$", body, re.MULTILINE))

    def _find(self, proposal_id: str) -> str:
        for branch in self._proposal_branches():
            if branch.rsplit("/", 1)[-1] == proposal_id:
                return branch
        raise TeamMemoryError(f"No open proposal {proposal_id!r}. See `magent memory team inbox`.")

    def inbox(self) -> dict[str, Any]:
        self._require()
        items = []
        for branch in self._proposal_branches():
            ref = f"origin/{branch}"
            trailers = self._trailers(ref)
            changes = self._git("diff", "--name-status", f"origin/main...{ref}").splitlines()
            items.append(
                {
                    "id": trailers.get("Proposal", branch.rsplit("/", 1)[-1]),
                    "branch": branch,
                    "author": trailers.get("Author", ""),
                    "title": self._git("log", "-1", "--format=%s", ref).strip(),
                    "created_at": self._git("log", "-1", "--format=%cI", ref).strip(),
                    "changes": [
                        {"status": line.split("\t", 1)[0], "path": line.split("\t", 1)[-1]}
                        for line in changes
                        if line.strip()
                    ],
                }
            )
        return {"ok": True, "team": self.name, "proposals": items}

    def show(self, proposal_id: str) -> dict[str, Any]:
        self._require()
        branch = self._find(proposal_id)
        ref = f"origin/{branch}"
        trailers = self._trailers(ref)
        diff = self._git("diff", f"origin/main...{ref}", "--", NODES_DIR)
        problems: list[str] = []
        for line in self._git("diff", "--name-only", f"origin/main...{ref}").splitlines():
            if not line.startswith(f"{NODES_DIR}/") or not line.endswith(".md"):
                problems.append(f"{line}: proposals may only add or change nodes/*.md")
                continue
            text = self._git("show", f"{ref}:{line}", check=False)
            if text:
                problems.extend(self.validate_node(text, filename=line))
        return {
            "ok": True,
            "id": proposal_id,
            "branch": branch,
            "author": trailers.get("Author", ""),
            "title": self._git("log", "-1", "--format=%s", ref).strip(),
            "diff": diff,
            "checks": {"ok": not problems, "problems": problems},
        }

    def _record_review(self, record: dict[str, Any]) -> None:
        path = self.root / REVIEWS_FILE
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
        self._git("add", REVIEWS_FILE)
        self._git("commit", "-m", f"Review {record['proposal']}: {record['decision']}")

    def decide(
        self,
        proposal_id: str,
        *,
        decision: str,
        reason: str = "",
        allow_self_review: bool = False,
    ) -> dict[str, Any]:
        """Accept (merge into main) or reject a proposal; both are recorded."""

        if decision not in {"accept", "reject"}:
            raise TeamMemoryError("decision must be accept or reject")
        details = self.show(proposal_id)
        author = details["author"]
        if decision == "accept":
            if author == self.username and not allow_self_review:
                raise TeamMemoryError(
                    "You wrote this proposal, so a teammate has to accept it "
                    "(or pass --allow-self-review for a one-person team)."
                )
            if not details["checks"]["ok"]:
                raise TeamMemoryError(
                    "The proposal fails its checks: " + "; ".join(details["checks"]["problems"])
                )
        branch = details["branch"]
        self._git("fetch", "origin")
        self._git("checkout", "-B", "main", "origin/main")
        try:
            if decision == "accept":
                self._git(
                    "merge",
                    "--no-ff",
                    f"origin/{branch}",
                    "-m",
                    f"Accept proposal {proposal_id} from {author} (reviewed by {self.username})",
                )
            self._record_review(
                {
                    "proposal": proposal_id,
                    "decision": decision,
                    "author": author,
                    "reviewer": self.username,
                    "reason": reason,
                    "at": _now(),
                }
            )
            self._git("push", "origin", "main")
        except TeamMemoryError:
            self._git("reset", "--hard", "origin/main", check=False)
            raise
        self._git("push", "origin", "--delete", branch, check=False)
        self._git("fetch", "--prune", "origin", check=False)
        return {"ok": True, "id": proposal_id, "decision": decision, "reviewer": self.username}

    def reviews(self, limit: int = 50) -> list[dict[str, Any]]:
        self._require()
        path = self.root / REVIEWS_FILE
        if not path.exists():
            return []
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return [json.loads(line) for line in lines[-limit:]]

    def remove(self) -> None:
        """Delete the local clone (the shared repository is not touched)."""

        if self.root.exists():
            shutil.rmtree(self.root)


def team_settings(config: Any) -> dict[str, Any]:
    raw = config.get("memory", "team", default={}) if config is not None else {}
    return raw if isinstance(raw, dict) else {}
