"""Configuration loader and manager for MagAgent."""

from __future__ import annotations

import os
import tomllib  # type: ignore[no-redef]
from pathlib import Path
from typing import Any

import tomli_w

# ─────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────

CONFIG_DIR = Path.home() / ".config" / "magent"
GLOBAL_CONFIG = CONFIG_DIR / "config.toml"
USERS_DIR = CONFIG_DIR / "users"
SKILLS_DIR = CONFIG_DIR / "skills"
LOGS_DIR = CONFIG_DIR / "logs" / "sessions"
SKILLS_LOCK = CONFIG_DIR / "skills.lock"

CURRENT_USER_FILE = USERS_DIR / "current"

# ─────────────────────────────────────────────
# Defaults
# ─────────────────────────────────────────────

DEFAULT_GLOBAL_CONFIG: dict[str, Any] = {
    "agent": {
        "name": "MagAgent",
        "version": "0.19.0",
        "selective_tools": True,
        "max_subagents": 3,
    },
    "defaults": {
        "provider": "ollama",
        "model": "qwen2.5-coder:32b",
        "permission_mode": "balanced",
        "context_window_tokens": 32000,
        "memory_budget_tokens": 4000,
        "repo_map_budget_tokens": 1200,
        "skill_budget_tokens": 2000,
    },
    "memory": {
        "auto_write": True,
        "auto_commit": False,
        "write_every_n_turns": 5,
        "extraction_provider": "ollama",
        "extraction_model": "qwen2.5:7b",
        "encrypt": False,
        "recall_body_tokens": 220,
        "semantic_enabled": True,
        "semantic_provider": "ollama",
        "semantic_model": "nomic-embed-text",
        "semantic_top_k": 8,
    },
    "context": {
        "compact_every_n_turns": 10,
        "keep_recent_turns": 6,
        "max_history_tokens": 6000,
        "prune_stale_tool_results": True,
        "prompt_caching": True,
    },
    "tool_budgets": {
        "default": 8000,
        "read_file": 16000,
        "read_file_range": 12000,
        "web_fetch": 12000,
        "run_shell": 10000,
        "run_python": 10000,
        "search_codebase": 9000,
        "db_query": 8000,
    },
    "skills": {
        "lockfile": str(SKILLS_LOCK),
    },
    "ui": {
        "theme": "dark",
        "stream_output": True,
        "show_tool_calls": True,
        "show_memory_writes": False,
    },
    "providers": {},
    "models": {
        "coding": "",
        "review": "",
        "memory": "",
        "cheap": "",
        "fallback": [],
    },
    "subagents": {
        "max_subagents": 3,
        "max_parallel_subagents": 2,
        "model_role": "coding",
        "sandbox_mode": "",
    },
    "mcp": {},
}

DEFAULT_USER_PROFILE: dict[str, Any] = {
    "preferences": {
        "default_provider": "",
        "default_model": "",
        "theme": "dark",
        "memory_budget_tokens": 4000,
    },
    "permissions": {
        "mode": "balanced",
        "auto_commit_memory": False,
        "allowed_shell_patterns": [
            "git *",
            "npm *",
            "cargo *",
            "pytest *",
            "python *",
            "pip *",
        ],
    },
    "memory": {
        "auto_write": True,
        "write_every_n_turns": 5,
        "max_nodes": 10000,
        "encrypt": False,
    },
}

MAGGRAPH_TOML_TEMPLATE = """\
[storage]
mode = "local"
root_path = "."
"""


# ─────────────────────────────────────────────
# Config class
# ─────────────────────────────────────────────


class Config:
    """Merged view of global config + active user profile."""

    def __init__(self, global_cfg: dict[str, Any], user_cfg: dict[str, Any] | None = None):
        self._global = global_cfg
        self._user = user_cfg or {}
        self._raw = _deep_merge(global_cfg, self._user)

    def get(self, *keys: str, default: Any = None) -> Any:
        """Dot-path lookup, user profile overrides global."""
        for root in (self._user, self._global):
            node = root
            for k in keys:
                if not isinstance(node, dict):
                    break
                node = node.get(k)
            if node is not None:
                return node
        return default

    # Convenience properties

    @property
    def default_provider(self) -> str:
        user_pref = self._user.get("preferences", {}).get("default_provider") or ""
        return user_pref or self._global.get("defaults", {}).get("provider", "ollama")

    @property
    def default_model(self) -> str:
        user_pref = self._user.get("preferences", {}).get("default_model") or ""
        return user_pref or self._global.get("defaults", {}).get("model", "qwen2.5-coder:32b")

    @property
    def permission_mode(self) -> str:
        return self._user.get("permissions", {}).get("mode") or self._global.get(
            "defaults", {}
        ).get("permission_mode", "balanced")

    @property
    def allowed_shell_patterns(self) -> list[str]:
        return self._user.get("permissions", {}).get("allowed_shell_patterns", [])

    @property
    def memory_budget_tokens(self) -> int:
        return int(
            self._user.get("preferences", {}).get("memory_budget_tokens")
            or self._global.get("defaults", {}).get("memory_budget_tokens", 4000)
        )

    @property
    def repo_map_budget_tokens(self) -> int:
        return int(self._global.get("defaults", {}).get("repo_map_budget_tokens", 1200))

    @property
    def skill_budget_tokens(self) -> int:
        return int(self._global.get("defaults", {}).get("skill_budget_tokens", 2000))

    @property
    def context_window_tokens(self) -> int:
        return int(self._global.get("defaults", {}).get("context_window_tokens", 32000))

    @property
    def compact_every_n_turns(self) -> int:
        return int(self._global.get("context", {}).get("compact_every_n_turns", 10))

    @property
    def keep_recent_turns(self) -> int:
        return int(self._global.get("context", {}).get("keep_recent_turns", 6))

    @property
    def max_history_tokens(self) -> int:
        return int(self._global.get("context", {}).get("max_history_tokens", 6000))

    @property
    def prune_stale_tool_results(self) -> bool:
        return bool(self._global.get("context", {}).get("prune_stale_tool_results", True))

    @property
    def prompt_caching(self) -> bool:
        return bool(self._global.get("context", {}).get("prompt_caching", True))

    @property
    def recall_body_tokens(self) -> int:
        return int(self._global.get("memory", {}).get("recall_body_tokens", 220))

    @property
    def semantic_memory_enabled(self) -> bool:
        user_memory = self._user.get("memory", {})
        if user_memory.get("semantic_enabled") is not None:
            return bool(user_memory.get("semantic_enabled"))
        return bool(self._global.get("memory", {}).get("semantic_enabled", True))

    @property
    def semantic_memory_provider(self) -> str:
        return self._user.get("memory", {}).get("semantic_provider") or self._global.get(
            "memory", {}
        ).get("semantic_provider", "ollama")

    @property
    def semantic_memory_model(self) -> str:
        return self._user.get("memory", {}).get("semantic_model") or self._global.get(
            "memory", {}
        ).get("semantic_model", "nomic-embed-text")

    @property
    def selective_tools(self) -> bool:
        return bool(self._global.get("agent", {}).get("selective_tools", True))

    @property
    def max_subagents(self) -> int:
        return int(
            self._global.get("subagents", {}).get(
                "max_subagents",
                self._global.get("agent", {}).get("max_subagents", 3),
            )
        )

    @property
    def max_parallel_subagents(self) -> int:
        return int(self._global.get("subagents", {}).get("max_parallel_subagents", 2))

    @property
    def subagent_model_role(self) -> str:
        return self._global.get("subagents", {}).get("model_role", "coding")

    @property
    def subagent_sandbox_mode(self) -> str:
        return self._global.get("subagents", {}).get("sandbox_mode", "")

    @property
    def write_every_n_turns(self) -> int:
        return int(
            self._user.get("memory", {}).get("write_every_n_turns")
            or self._global.get("memory", {}).get("write_every_n_turns", 5)
        )

    @property
    def extraction_provider(self) -> str:
        return self._user.get("memory", {}).get("extraction_provider") or self._global.get(
            "memory", {}
        ).get("extraction_provider", "ollama")

    @property
    def extraction_model(self) -> str:
        return self._user.get("memory", {}).get("extraction_model") or self._global.get(
            "memory", {}
        ).get("extraction_model", "qwen2.5:7b")

    @property
    def auto_write(self) -> bool:
        return bool(
            self._user.get("memory", {}).get("auto_write")
            if self._user.get("memory", {}).get("auto_write") is not None
            else self._global.get("memory", {}).get("auto_write", True)
        )

    @property
    def encrypt_memory(self) -> bool:
        return bool(
            self._user.get("memory", {}).get("encrypt")
            or self._global.get("memory", {}).get("encrypt", False)
        )

    @property
    def providers(self) -> dict[str, Any]:
        return self._global.get("providers", {})

    @property
    def mcp_servers(self) -> dict[str, Any]:
        return self._global.get("mcp", {})

    @property
    def model_roles(self) -> dict[str, Any]:
        return self._global.get("models", {})

    def provider_config(self, provider_id: str) -> dict[str, Any]:
        return self.providers.get(provider_id, {})

    def resolve_api_key(self, provider_id: str) -> str | None:
        cfg = self.provider_config(provider_id)
        env_var = cfg.get("api_key_env")
        if env_var:
            return os.environ.get(env_var)
        return cfg.get("api_key")

    def as_dict(self) -> dict[str, Any]:
        """Return the merged config as a plain dictionary."""
        return self._raw.copy()


# ─────────────────────────────────────────────
# Loaders
# ─────────────────────────────────────────────


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base."""
    result = base.copy()
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load_global_config() -> dict[str, Any]:
    if not GLOBAL_CONFIG.exists():
        return DEFAULT_GLOBAL_CONFIG.copy()
    with GLOBAL_CONFIG.open("rb") as f:
        raw = tomllib.load(f)
    return _deep_merge(DEFAULT_GLOBAL_CONFIG, raw)


def load_user_profile(username: str) -> dict[str, Any]:
    profile_path = USERS_DIR / username / "profile.toml"
    if not profile_path.exists():
        return DEFAULT_USER_PROFILE.copy()
    with profile_path.open("rb") as f:
        raw = tomllib.load(f)
    return _deep_merge(DEFAULT_USER_PROFILE, raw)


def load_config(username: str | None = None) -> Config:
    global_cfg = load_global_config()
    user_cfg = load_user_profile(username) if username else {}
    return Config(global_cfg, user_cfg)


# ─────────────────────────────────────────────
# User management helpers
# ─────────────────────────────────────────────


def get_current_user() -> str | None:
    if CURRENT_USER_FILE.exists():
        name = CURRENT_USER_FILE.read_text().strip()
        return name if name else None
    return None


def set_current_user(username: str) -> None:
    USERS_DIR.mkdir(parents=True, exist_ok=True)
    CURRENT_USER_FILE.write_text(username)


def list_users() -> list[str]:
    if not USERS_DIR.exists():
        return []
    return sorted(d.name for d in USERS_DIR.iterdir() if d.is_dir() and not d.name.startswith("."))


def user_exists(username: str) -> bool:
    return (USERS_DIR / username).exists()


def user_memory_dir(username: str) -> Path:
    return USERS_DIR / username / "memory"


def create_user(username: str) -> None:
    """Create directory structure and default profile for a new user."""
    user_dir = USERS_DIR / username
    memory_dir = user_dir / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)

    profile_path = user_dir / "profile.toml"
    if not profile_path.exists():
        with profile_path.open("wb") as f:
            tomli_w.dump(DEFAULT_USER_PROFILE, f)

    # Bootstrap maggraph.toml inside memory dir
    maggraph_toml = memory_dir / "maggraph.toml"
    if not maggraph_toml.exists():
        maggraph_toml.write_text(MAGGRAPH_TOML_TEMPLATE)


def delete_user(username: str) -> None:
    """Remove user directory entirely."""
    import shutil

    user_dir = USERS_DIR / username
    if user_dir.exists():
        shutil.rmtree(user_dir)
    # If this was the active user, clear current
    if get_current_user() == username:
        CURRENT_USER_FILE.write_text("")


def save_global_config(cfg: dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with GLOBAL_CONFIG.open("wb") as f:
        tomli_w.dump(cfg, f)


def save_user_profile(username: str, profile: dict[str, Any]) -> None:
    profile_path = USERS_DIR / username / "profile.toml"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    with profile_path.open("wb") as f:
        tomli_w.dump(profile, f)
