"""Safe conversion helpers for Pi packages."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any


def import_pi(src: Path, target: Path, converted: dict[str, list[str]]) -> None:
    """Convert portable resources and quarantine Pi runtime-specific assets."""
    manifest = pi_manifest(src)
    skill_sources = _resource_paths(src, manifest, "skills", ["skills", ".pi/skills", ".agents/skills"])
    prompt_sources = _resource_paths(src, manifest, "prompts", ["prompts", ".pi/prompts"])
    theme_sources = _resource_paths(src, manifest, "themes", ["themes", ".pi/themes"])
    extension_sources = _resource_paths(src, manifest, "extensions", ["extensions", ".pi/extensions"])

    for skill_source in skill_sources:
        _copy_skills(skill_source, target / "skills", converted["skills"])
    for prompt_source in prompt_sources:
        _copy_markdown(prompt_source, target / "recipes", converted["recipes"])
    for context_name in ("AGENTS.md", "CLAUDE.md", "SYSTEM.md", "APPEND_SYSTEM.md"):
        for candidate in (src / context_name, src / ".pi" / context_name):
            if candidate.is_file():
                _write_agent(
                    candidate,
                    target / "agents" / f"pi-{candidate.stem.lower().replace('_', '-')}.md",
                    converted["agents"],
                )

    compatibility_root = target / "compatibility" / "pi"
    preserved_extensions = _preserve(src, extension_sources, compatibility_root / "package")
    preserved_themes = _preserve(src, theme_sources, compatibility_root / "package")
    package_json = src / "package.json"
    if package_json.is_file():
        compatibility_root.mkdir(parents=True, exist_ok=True)
        shutil.copy2(package_json, compatibility_root / "package.json")
    report = {
        "schema": "magent.pi-compatibility.v1",
        "source": str(src),
        "portable": {
            "agents": list(converted["agents"]),
            "skills": list(converted["skills"]),
            "recipes": list(converted["recipes"]),
            "mcp": [],
        },
        "preserved": {"extensions": preserved_extensions, "themes": preserved_themes},
        "runtime": {
            "native_extension_execution": False,
            "bridge_available": bool(preserved_extensions),
            "reason": "Pi TypeScript/JavaScript extensions require Pi's runtime and may execute arbitrary code.",
        },
    }
    compatibility_root.mkdir(parents=True, exist_ok=True)
    (compatibility_root / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def pi_manifest(path: Path) -> dict[str, Any]:
    package_json = path / "package.json"
    if not package_json.is_file():
        return {}
    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
        return dict(data.get("pi", {})) if isinstance(data.get("pi"), dict) else {}
    except Exception:
        return {}


def is_pi_package(path: Path) -> bool:
    package_json = path / "package.json"
    if not package_json.is_file():
        return False
    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
    except Exception:
        return False
    keywords = _as_list(data.get("keywords"))
    return isinstance(data.get("pi"), dict) or "pi-package" in keywords


def _resource_paths(src: Path, manifest: dict[str, Any], key: str, defaults: list[str]) -> list[Path]:
    configured = _as_list(manifest.get(key))
    values = configured if configured else defaults
    paths: list[Path] = []
    for value in values:
        candidate = (src / value).resolve(strict=False)
        try:
            candidate.relative_to(src)
        except ValueError:
            continue
        if candidate.exists() and candidate not in paths:
            paths.append(candidate)
    return paths


def _copy_skills(src: Path, dest: Path, converted: list[str]) -> None:
    candidates = [src] if src.is_file() else sorted(src.rglob("SKILL.md"))
    for skill_file in candidates:
        if not skill_file.is_file() or skill_file.name != "SKILL.md":
            continue
        target = dest / _safe_name(skill_file.parent.name) / "SKILL.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(skill_file, target)
        converted.append(str(target.relative_to(dest.parent)))


def _copy_markdown(src: Path, dest: Path, converted: list[str]) -> None:
    candidates = [src] if src.is_file() else sorted(src.rglob("*.md"))
    for prompt in candidates:
        if not prompt.is_file() or prompt.suffix.lower() != ".md":
            continue
        target = dest / f"pi-{_safe_name(prompt.stem)}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(prompt, target)
        converted.append(str(target.relative_to(dest.parent)))


def _write_agent(src: Path, dest: Path, converted: list[str]) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    body = src.read_text(encoding="utf-8", errors="replace")
    dest.write_text(
        f"---\ndescription: Imported from {src.name}\nmode: subagent\n---\n\n{body}",
        encoding="utf-8",
    )
    converted.append(str(dest.relative_to(dest.parent.parent)))


def _preserve(src: Path, resources: list[Path], dest: Path) -> list[str]:
    preserved: list[str] = []
    for resource in resources:
        relative = resource.relative_to(src)
        target = dest / relative
        if resource.is_dir():
            shutil.copytree(resource, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns("node_modules", ".git"))
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(resource, target)
        preserved.append(relative.as_posix())
    return preserved


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list | tuple | set):
        return [str(item) for item in value]
    return [str(value)]


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value).strip("-") or "imported"
