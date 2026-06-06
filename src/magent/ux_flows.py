"""Guided UX helpers for onboarding, project setup, and next actions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import tomli_w

from magent.config import load_global_config, save_global_config
from magent.config_ux import configure_memory, configure_subagents, set_default_provider

PROFILE_PRESETS: dict[str, dict[str, Any]] = {
    "coding-local": {
        "description": "Local-first coding with Ollama and cautious memory writes.",
        "provider": {"id": "ollama", "model": "qwen2.5-coder:32b", "access_mode": "local"},
        "memory": {"mode": "inbox-first", "semantic": True, "write_every": 5},
        "subagents": {"max_subagents": 2, "max_parallel": 1, "model_role": "coding"},
        "models": {"coding": "ollama/qwen2.5-coder:32b", "memory": "ollama/qwen2.5:7b"},
    },
    "coding-cloud": {
        "description": "Strong cloud model for coding and review.",
        "provider": {"id": "openai", "model": "gpt-5", "access_mode": "api", "api_key_env": "OPENAI_API_KEY"},
        "memory": {"mode": "inbox-first", "semantic": True, "write_every": 3},
        "subagents": {"max_subagents": 3, "max_parallel": 2, "model_role": "coding"},
        "models": {"coding": "openai/gpt-5", "review": "openai/gpt-5", "memory": "openai/gpt-5-mini"},
    },
    "codex-subscription": {
        "description": "OpenAI Codex subscription/client workflow for users signed in with ChatGPT.",
        "provider": {"id": "openai", "model": "gpt-5", "access_mode": "codex"},
        "memory": {"mode": "inbox-first", "semantic": True, "write_every": 3},
        "subagents": {"max_subagents": 2, "max_parallel": 1, "model_role": "coding"},
        "models": {"coding": "openai/gpt-5", "review": "openai/gpt-5"},
    },
    "low-cost": {
        "description": "Low-cost coding defaults with OpenCode Go subscription models.",
        "provider": {"id": "opencode-go", "model": "deepseek-v4-flash", "access_mode": "subscription", "api_key_env": "OPENCODE_GO_KEY"},
        "memory": {"mode": "inbox-first", "semantic": True, "write_every": 5},
        "subagents": {"max_subagents": 2, "max_parallel": 1, "model_role": "cheap"},
        "models": {"coding": "opencode-go/deepseek-v4-flash", "cheap": "opencode-go/deepseek-v4-flash"},
    },
    "review-heavy": {
        "description": "Bias model routing toward review and release checks.",
        "provider": {"id": "anthropic", "model": "claude-sonnet-4-5", "access_mode": "api", "api_key_env": "ANTHROPIC_API_KEY"},
        "memory": {"mode": "inbox-first", "semantic": True, "write_every": 3},
        "subagents": {"max_subagents": 3, "max_parallel": 2, "model_role": "review"},
        "models": {"coding": "anthropic/claude-sonnet-4-5", "review": "anthropic/claude-sonnet-4-5"},
    },
    "memory-first": {
        "description": "Favor explicit memory review and semantic recall.",
        "provider": {"id": "ollama", "model": "qwen2.5-coder:32b", "access_mode": "local"},
        "memory": {"mode": "inbox-first", "semantic": True, "write_every": 2},
        "subagents": {"max_subagents": 2, "max_parallel": 1, "model_role": "coding"},
        "models": {"memory": "ollama/qwen2.5:7b", "coding": "ollama/qwen2.5-coder:32b"},
    },
    "safe-enterprise": {
        "description": "Conservative permissions and manual memory writes.",
        "provider": {"id": "openai", "model": "gpt-5", "access_mode": "api", "api_key_env": "OPENAI_API_KEY"},
        "memory": {"mode": "manual", "semantic": True, "write_every": 5},
        "subagents": {"max_subagents": 1, "max_parallel": 1, "model_role": "coding"},
        "models": {"coding": "openai/gpt-5", "review": "openai/gpt-5"},
        "permissions": {"mode": "paranoid"},
    },
}


def list_profiles() -> dict[str, Any]:
    return {
        "ok": True,
        "profiles": [
            {"name": name, "description": profile["description"]}
            for name, profile in sorted(PROFILE_PRESETS.items())
        ],
    }


def apply_profile(name: str, username: str | None = None) -> dict[str, Any]:
    profile = PROFILE_PRESETS.get(name)
    if not profile:
        return {"ok": False, "error": f"Unknown profile: {name}", "known": sorted(PROFILE_PRESETS)}
    provider = profile["provider"]
    set_default_provider(
        provider["id"],
        provider.get("model"),
        api_key_env=provider.get("api_key_env", ""),
        access_mode=provider.get("access_mode", ""),
    )
    cfg = load_global_config()
    cfg.setdefault("models", {}).update(profile.get("models", {}))
    if "permissions" in profile:
        cfg.setdefault("defaults", {})["permission_mode"] = profile["permissions"].get("mode", "balanced")
    save_global_config(cfg)
    if username:
        memory = profile.get("memory", {})
        configure_memory(
            username,
            mode=memory.get("mode", ""),
            semantic=memory.get("semantic"),
            write_every=memory.get("write_every"),
        )
    configure_subagents(**profile.get("subagents", {}))
    return {"ok": True, "profile": name, "description": profile["description"]}


def init_project(root: str | Path = ".", *, force: bool = False) -> dict[str, Any]:
    root_path = Path(root).resolve()
    magent_dir = root_path / ".magent"
    magent_dir.mkdir(parents=True, exist_ok=True)
    from magent.playbook import playbook_path, playbook_template
    from magent.workbench import project_command_roles

    playbook = playbook_path(root_path)
    wrote_playbook = False
    if force or not playbook.exists():
        playbook.write_text(playbook_template(), encoding="utf-8")
        wrote_playbook = True

    config_path = magent_dir / "config.toml"
    roles = project_command_roles(root_path)
    wrote_config = False
    if force or not config_path.exists():
        payload = {
            "commands": roles,
            "review": {"rules": ["Source changes should include focused tests"]},
            "context": {"briefing_topics": ["architecture", "testing", "commands"]},
        }
        with config_path.open("wb") as f:
            tomli_w.dump(payload, f)
        wrote_config = True
    return {
        "ok": True,
        "root": str(root_path),
        "playbook": str(playbook),
        "config": str(config_path),
        "wrote_playbook": wrote_playbook,
        "wrote_config": wrote_config,
        "commands": roles,
    }


def next_actions(root: str | Path = ".", store: Any | None = None, username: str | None = None) -> dict[str, Any]:
    root_path = Path(root).resolve()
    actions: list[dict[str, str]] = []
    from magent.config_ux import doctor_actions
    from magent.memory_inbox import memory_inbox
    from magent.workbench import project_doctor

    doctor = doctor_actions(username)
    for item in doctor["actions"]:
        if not item["ok"] and item.get("command"):
            actions.append({"title": f"Fix {item['key']}", "command": item["command"], "reason": item["detail"]})

    project = project_doctor(root_path, store)
    if project.get("missing"):
        actions.append(
            {
                "title": "Bootstrap project commands",
                "command": f"magent project init --path {root_path}",
                "reason": f"Missing command roles: {', '.join(project['missing'][:4])}",
            }
        )

    if store is not None:
        candidates = memory_inbox(store, root_path, limit=20).get("candidates", [])
        if candidates:
            actions.append(
                {
                    "title": "Review memory inbox",
                    "command": f"magent memory inbox --project {root_path}",
                    "reason": f"{len(candidates)} candidate(s) can be accepted, edited, or rejected.",
                }
            )
    actions.append(
        {
            "title": "Refresh context map",
            "command": f"magent context map --project {root_path}",
            "reason": "See memory, project, workbench, and promotion context in one place.",
        }
    )
    return {"ok": True, "root": str(root_path), "actions": actions[:7]}
