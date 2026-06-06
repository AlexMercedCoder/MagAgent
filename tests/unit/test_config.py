from __future__ import annotations

from pathlib import Path

from magent import config as magent_config
from magent.config import Config


def redirect_config(monkeypatch, root: Path) -> None:
    cfg_dir = root / ".config" / "magent"
    monkeypatch.setattr(magent_config, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(magent_config, "GLOBAL_CONFIG", cfg_dir / "config.toml")
    monkeypatch.setattr(magent_config, "USERS_DIR", cfg_dir / "users")
    monkeypatch.setattr(magent_config, "CURRENT_USER_FILE", cfg_dir / "users" / "current")


def test_config_properties_prefer_user_overrides(monkeypatch) -> None:
    monkeypatch.setenv("MAGENT_TEST_KEY", "secret")
    cfg = Config(
        {
            "defaults": {
                "provider": "ollama",
                "model": "local",
                "permission_mode": "balanced",
                "memory_budget_tokens": 100,
                "repo_map_budget_tokens": 200,
                "skill_budget_tokens": 300,
                "context_window_tokens": 400,
            },
            "memory": {
                "semantic_enabled": True,
                "semantic_provider": "ollama",
                "semantic_model": "embed",
                "write_every_n_turns": 5,
                "extraction_provider": "ollama",
                "extraction_model": "extract",
                "auto_write": True,
                "encrypt": False,
                "recall_body_tokens": 90,
            },
            "context": {
                "compact_every_n_turns": 10,
                "keep_recent_turns": 6,
                "max_history_tokens": 700,
            },
            "agent": {"selective_tools": True},
            "providers": {"custom": {"api_key_env": "MAGENT_TEST_KEY"}},
            "models": {"coding": "coder"},
            "mcp": {"servers": {}},
        },
        {
            "preferences": {
                "default_provider": "custom",
                "default_model": "cloud",
                "memory_budget_tokens": 123,
            },
            "permissions": {"mode": "silent", "allowed_shell_patterns": ["pytest *"]},
            "memory": {
                "semantic_enabled": False,
                "write_every_n_turns": 2,
                "extraction_provider": "cheap",
                "extraction_model": "tiny",
                "auto_write": False,
            },
        },
    )

    assert cfg.default_provider == "custom"
    assert cfg.default_model == "cloud"
    assert cfg.permission_mode == "silent"
    assert cfg.allowed_shell_patterns == ["pytest *"]
    assert cfg.memory_budget_tokens == 123
    assert cfg.semantic_memory_enabled is False
    assert cfg.write_every_n_turns == 2
    assert cfg.extraction_provider == "cheap"
    assert cfg.extraction_model == "tiny"
    assert cfg.auto_write is False
    assert cfg.resolve_api_key("custom") == "secret"
    assert cfg.model_roles == {"coding": "coder"}


def test_user_lifecycle_and_config_loading(tmp_path: Path, monkeypatch) -> None:
    redirect_config(monkeypatch, tmp_path)

    magent_config.save_global_config(
        {
            "defaults": {"provider": "custom", "model": "model-x"},
            "providers": {"custom": {"api_key": "inline"}},
        }
    )
    magent_config.create_user("alice")
    magent_config.set_current_user("alice")

    assert magent_config.get_current_user() == "alice"
    assert magent_config.user_exists("alice") is True
    assert magent_config.list_users() == ["alice"]
    assert (magent_config.user_memory_dir("alice") / "maggraph.toml").exists()

    cfg = magent_config.load_config("alice")

    assert cfg.default_provider == "custom"
    assert cfg.default_model == "model-x"
    assert cfg.resolve_api_key("custom") == "inline"

    magent_config.delete_user("alice")

    assert magent_config.user_exists("alice") is False
    assert magent_config.get_current_user() is None
