"""Deterministic OAP discovery with root-derived trust."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from magent.agent_profiles.composition import resolve_composition
from magent.agent_profiles.digest import digest_document, digest_spec
from magent.agent_profiles.documents import parse_document, validate_document
from magent.agent_profiles.errors import ProfileError
from magent.agent_profiles.legacy import convert_legacy
from magent.agent_profiles.models import ResolvedProfile
from magent.config import CONFIG_DIR

BUILTINS: dict[str, dict[str, Any]] = {
    "magagent": {
        "description": "General-purpose MagAgent coding and productivity profile.",
        "role": {
            "instructions": (
                "Act as a capable general-purpose coding and productivity agent. "
                "Inspect the available context, make concrete progress, verify consequential work, "
                "and communicate clearly about results and uncertainty."
            ),
            "persona": (
                "You are MagAgent: pragmatic, curious, attentive, and comfortable moving between "
                "software engineering, research, documentation, and practical project work."
            ),
            "objectives": [
                "Help the user complete useful work end to end.",
                "Use tools deliberately and leave verifiable artifacts when requested.",
                "Preserve project conventions, user intent, and safety boundaries.",
            ],
            "constraints": [
                "Do not claim work succeeded without checking the relevant result.",
                "Do not widen permissions or capabilities beyond harness policy.",
            ],
        },
    },
    "review": {
        "description": "Read-only code review focused on correctness, security, and tests.",
        "instructions": "You are MagAgent's review agent. Do not make edits unless explicitly asked. Prioritize bugs, regressions, security risks, and missing tests.",
        "tools": {"deny": ["write_file", "edit_file", "delete_file"]},
        "permissions": {"default": "paranoid"},
    },
    "explore": {
        "description": "Fast codebase exploration and context gathering.",
        "instructions": "You are MagAgent's explore agent. Gather relevant files, commands, and context, then summarize the shortest useful path forward.",
        "runtime": {"max_turns": 6},
    },
    "docs": {
        "description": "Documentation writing and docs audit agent.",
        "instructions": "You are MagAgent's documentation agent. Keep docs accurate, concise, and aligned with the live CLI and architecture.",
    },
}


def _builtin(name: str, value: dict[str, Any]) -> ResolvedProfile:
    role = value.get("role") or {"instructions": value["instructions"]}
    spec = {"role": role}
    for key in ("model", "tools", "permissions", "runtime", "memory", "context"):
        if key in value:
            spec[key] = value[key]
    document = {
        "oap": "1.0",
        "metadata": {"name": name, "description": value["description"], "revision": 1},
        "spec": spec,
        "state": [],
        "history": [],
        "proposals": [],
        "lifecycle": {"writeback": "off"},
    }
    return ResolvedProfile(document, None, "managed", digest_spec(document), digest_document(document), "yaml")


@dataclass(frozen=True)
class _Root:
    path: Path
    trust: str
    label: str
    precedence: int


class AgentProfileRegistry:
    def __init__(self, project: str | Path = ".", config: Any | None = None):
        self.project = Path(project).resolve()
        self.config = config

    def roots(self) -> list[_Root]:
        from magent.plugins import enabled_plugin_paths

        user_paths = self._setting("user_paths", [str(CONFIG_DIR / "agents")])
        project_paths = self._setting("project_paths", [".magent/agents", ".agents"])
        roots = [
            _Root(Path(str(path)).expanduser().resolve(), "user", "user", 500 - index)
            for index, path in enumerate(user_paths if isinstance(user_paths, list) else [user_paths])
        ]
        for index, path in enumerate(project_paths if isinstance(project_paths, list) else [project_paths]):
            raw = Path(str(path)).expanduser()
            resolved = (raw if raw.is_absolute() else self.project / raw).resolve()
            label = "project" if str(path).rstrip("/") == ".magent/agents" else "portable"
            roots.append(_Root(resolved, "project", label, 400 - index))
        roots.extend(_Root(path / "agents", "project", f"plugin:{path.name}", 200) for path in enabled_plugin_paths())
        return roots

    def load_path(self, path: Path, trust: str = "project") -> ResolvedProfile:
        raw, body, encoding = parse_document(path)
        legacy = "oap" not in raw
        document = convert_legacy(path, raw, body) if legacy else raw
        document.get("metadata", {}).pop("trust", None)
        validate_document(document)
        self._validate_workspace_paths(document)
        state_size = len(str(document.get("state", "")).encode("utf-8"))
        if state_size > int(self._setting("max_state_bytes", 200000)):
            raise ProfileError(f"profile state is {state_size} bytes and exceeds max_state_bytes")
        return ResolvedProfile(
            document=document,
            source_path=path.resolve(),
            trust=trust,
            spec_digest=digest_spec(document),
            profile_digest=digest_document(document),
            encoding=encoding,
            legacy=legacy,
        )

    def discover(self) -> tuple[dict[str, ResolvedProfile], list[str]]:
        selected = {name: _builtin(name, value) for name, value in BUILTINS.items()}
        source_rank = {name: 0 for name in selected}
        warnings: list[str] = []
        for root in sorted(self.roots(), key=lambda item: item.precedence):
            if not root.path.exists():
                continue
            within: dict[str, ResolvedProfile] = {}
            for path in sorted(root.path.iterdir()):
                if not path.is_file() or path.suffix.lower() not in {".md", ".yaml", ".yml", ".json"}:
                    continue
                profile = self.load_path(path, root.trust)
                if profile.name in within:
                    raise ProfileError(f"duplicate profile {profile.name!r} in {root.path}")
                within[profile.name] = profile
            for name, profile in within.items():
                if name in selected:
                    warnings.append(f"{root.label} profile {name!r} shadows {selected[name].trust} source")
                if root.precedence >= source_rank.get(name, -1):
                    selected[name] = profile
                    source_rank[name] = root.precedence
        maximum = int(self._setting("max_profiles", 200))
        if len(selected) > maximum:
            raise ProfileError(f"profile count {len(selected)} exceeds configured maximum {maximum}")
        return resolve_composition(selected), warnings

    def list(self) -> dict[str, Any]:
        profiles, warnings = self.discover()
        return {"ok": True, "profiles": [profiles[name].as_dict(include_document=False) for name in sorted(profiles)], "warnings": warnings}

    def get(self, name: str) -> ResolvedProfile | None:
        profiles, _ = self.discover()
        return profiles.get(name.strip().lstrip("@").lower())

    def _setting(self, key: str, default: Any) -> Any:
        return self.config.get("agent_profiles", key, default=default) if self.config else default

    def _validate_workspace_paths(self, document: dict[str, Any]) -> None:
        root = self.project.resolve()
        context = document.get("spec", {}).get("context", {})
        entries = context.get("files", []) if isinstance(context, dict) else []
        for entry in entries:
            raw = Path(str(entry.get("path", ""))).expanduser()
            resolved = (raw if raw.is_absolute() else root / raw).resolve(strict=False)
            if resolved != root and root not in resolved.parents:
                raise ProfileError(f"profile context path escapes workspace: {raw}")
