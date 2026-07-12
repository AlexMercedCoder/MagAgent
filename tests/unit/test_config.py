from __future__ import annotations

from pathlib import Path

from magent import auth_store, config_safety, config_ux, workbench_store
from magent import config as magent_config
from magent.cli.command_context import (
    ProviderCredentialError,
    build_provider,
    build_provider_for_role,
)
from magent.config import Config
from magent.config_proposals import (
    apply_config_proposal,
    discard_config_proposal,
    propose_config_change,
)
from magent.events import list_events, show_event
from magent.permission_ux import permission_set, permission_status
from magent.workbench_store import WorkbenchStore


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
            "subagents": {
                "max_subagents": 4,
                "max_parallel_subagents": 2,
                "model_role": "coding",
                "sandbox_mode": "copy",
            },
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
    assert cfg.model_for_role("coding") == "coder"
    assert cfg.provider_and_model_for_role("coding") == ("custom", "coder")
    assert cfg.provider_and_model_for_role("image_maker") == ("custom", "cloud")
    assert cfg.max_subagents == 4
    assert cfg.max_parallel_subagents == 2
    assert cfg.subagent_model_role == "coding"
    assert cfg.subagent_sandbox_mode == "copy"


def test_model_role_resolution_supports_provider_prefixed_and_fallback_values() -> None:
    cfg = Config(
        {
            "defaults": {"provider": "ollama", "model": "qwen2.5-coder:32b"},
            "models": {
                "image_maker": "openai/gpt-image-1",
                "cheap": "openrouter/deepseek/deepseek-chat",
                "fallback": ["ollama/llama3.1:8b"],
            },
        }
    )

    assert cfg.model_for_role("image_maker") == "openai/gpt-image-1"
    assert cfg.provider_and_model_for_role("image_maker") == ("openai", "gpt-image-1")
    assert cfg.provider_and_model_for_role("cheap") == ("openrouter", "deepseek/deepseek-chat")
    assert cfg.provider_and_model_for_role("fallback") == ("ollama", "llama3.1:8b")
    assert cfg.provider_and_model_for_role("review") == ("ollama", "qwen2.5-coder:32b")


def test_config_resolves_keyring_and_instruction_sources(monkeypatch) -> None:
    monkeypatch.setattr(auth_store, "load_keyring_secret", lambda provider_id: "key-from-ring")
    cfg = Config(
        {
            "defaults": {"provider": "openai", "model": "gpt-5"},
            "providers": {"openai": {"api_key_keyring": "provider:openai"}},
            "context": {"instructions": ["CONTRIBUTING.md", "docs/*.md"]},
        }
    )

    assert cfg.resolve_api_key("openai") == "key-from-ring"
    assert cfg.instruction_sources == ["CONTRIBUTING.md", "docs/*.md"]


def test_config_validation_and_ambient_instructions(tmp_path: Path, monkeypatch) -> None:
    redirect_config(monkeypatch, tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    (project / "CONTRIBUTING.md").write_text("Run tests before final response.", encoding="utf-8")
    magent_config.save_global_config(
        {
            "defaults": {"provider": "ollama", "model": "qwen"},
            "providers": {"ollama": {"access_mode": "local"}},
            "models": {"image_maker": "openai/gpt-image-1"},
            "context": {"instructions": ["CONTRIBUTING.md"]},
        }
    )

    from magent.config_validation import load_ambient_instructions, validate_config

    cfg = magent_config.load_config(None)
    assert validate_config(None, project)["ok"] is True
    assert "Run tests" in load_ambient_instructions(cfg, project)


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


def test_config_ux_helpers_update_toml_without_manual_editing(tmp_path: Path, monkeypatch) -> None:
    redirect_config(monkeypatch, tmp_path)
    magent_config.create_user("alice")
    magent_config.set_current_user("alice")

    provider = config_ux.set_default_provider("openai", "gpt-5", api_key_env="OPENAI_API_KEY")
    codex = config_ux.set_default_provider("openai", "gpt-5", access_mode="codex")
    role = config_ux.set_model_role("review", "anthropic/claude-sonnet-4-5")
    image_role = config_ux.set_model_role("image_maker", "openai/gpt-image-1")
    memory = config_ux.configure_memory("alice", mode="inbox-first", semantic=False, write_every=3)
    subagents = config_ux.configure_subagents(max_subagents=5, max_parallel=2, model_role="cheap")
    gateway = config_ux.configure_gateway("telegram", bot_token="secret", allowed_user_ids=["123"])
    summary = config_ux.ux_doctor("alice")

    assert provider["provider"] == "openai"
    assert codex["access_mode"] == "codex"
    assert role["value"] == "anthropic/claude-sonnet-4-5"
    assert image_role["value"] == "openai/gpt-image-1"
    assert memory["memory"]["inbox_first"] is True
    assert subagents["subagents"]["max_subagents"] == 5
    assert gateway["gateway"]["telegram"]["bot_token"] == "***"
    assert summary["provider"]["provider"] == "openai"
    assert summary["provider"]["access_mode"] == "codex"
    assert summary["model_roles"]["review"] is True
    assert summary["model_roles"]["image_maker"] is True
    assert summary["gateways"]["telegram"] is True


def test_configure_provider_entry_does_not_change_default_provider(tmp_path: Path, monkeypatch) -> None:
    redirect_config(monkeypatch, tmp_path)
    config_ux.set_default_provider("ollama", "qwen2.5-coder:32b", access_mode="local")

    result = config_ux.configure_provider_entry(
        "openai",
        model="gpt-image-1",
        api_key_env="OPENAI_API_KEY",
        access_mode="api",
    )
    cfg = magent_config.load_global_config()

    assert result["ok"] is True
    assert cfg["defaults"]["provider"] == "ollama"
    assert cfg["defaults"]["model"] == "qwen2.5-coder:32b"
    assert cfg["providers"]["openai"]["default_model"] == "gpt-image-1"
    assert cfg["providers"]["openai"]["api_key_env"] == "OPENAI_API_KEY"


def test_config_ux_provider_access_modes_and_doctor_actions(tmp_path: Path, monkeypatch) -> None:
    redirect_config(monkeypatch, tmp_path)
    monkeypatch.setenv("OPENCODE_GO_KEY", "secret")
    magent_config.create_user("alice")
    magent_config.set_current_user("alice")

    result = config_ux.set_default_provider(
        "opencode-go",
        "deepseek-v4-flash",
        api_key_env="OPENCODE_GO_KEY",
        access_mode="subscription",
    )
    detected = {item["id"]: item for item in config_ux.detect_provider_environment()}
    doctor = config_ux.doctor_actions("alice")
    fixed = config_ux.fix_doctor_actions("alice")

    assert result["access_mode"] == "subscription"
    assert result["config"]["api_key_env"] == "***"
    assert detected["openai"]["access_modes"][1]["id"] == "codex"
    assert detected["opencode-go"]["api_key_env"] == "OPENCODE_GO_KEY"
    assert detected["mistral"]["api_key_env"] == "MISTRAL_API_KEY"
    assert detected["deepseek"]["default_model"] == "deepseek-chat"
    assert detected["xai"]["api_key_env"] == "XAI_API_KEY"
    assert detected["perplexity"]["api_key_env"] == "PERPLEXITYAI_API_KEY"
    assert detected["cerebras"]["api_key_env"] == "CEREBRAS_API_KEY"
    assert detected["together_ai"]["api_key_env"] == "TOGETHERAI_API_KEY"
    assert detected["fireworks_ai"]["api_key_env"] == "FIREWORKS_API_KEY"
    assert detected["deepinfra"]["api_key_env"] == "DEEPINFRA_API_KEY"
    assert detected["lmstudio"]["local"] is True
    assert detected["bedrock"]["recommended_access"] == "aws"
    assert any(item["key"] == "opencode_go" for item in doctor["actions"])
    assert next(item for item in doctor["actions"] if item["key"] == "opencode_go")["ok"] is True
    assert fixed["after"]["summary"]["subagents"]["max_subagents"] == 3


def test_provider_ux_matrix_recommend_env_and_explain(tmp_path: Path, monkeypatch) -> None:
    redirect_config(monkeypatch, tmp_path)
    monkeypatch.setenv("MISTRAL_API_KEY", "secret")
    config_ux.set_default_provider("mistral", "mistral-large-latest", api_key_env="MISTRAL_API_KEY")

    matrix = {item["id"]: item for item in config_ux.provider_matrix()["providers"]}
    env = {item["provider"]: item for item in config_ux.provider_env_status()["providers"]}
    explained = config_ux.provider_explain("mistral")
    recommended = config_ux.provider_recommend("coding")
    catalog = config_ux.provider_catalog_doctor()

    assert matrix["mistral"]["configured"] is True
    assert matrix["mistral"]["env_present"] is True
    assert matrix["mistral"]["ready"] is True
    assert env["mistral"]["present"] is True
    assert explained["commands"][0].startswith("magent provider set mistral")
    assert any(item["id"] == "mistral" for item in recommended["recommendations"])
    assert catalog["ok"] is True


def test_config_safety_backup_diff_and_restore(tmp_path: Path, monkeypatch) -> None:
    redirect_config(monkeypatch, tmp_path)
    monkeypatch.setattr(config_safety, "CONFIG_DIR", magent_config.CONFIG_DIR)
    monkeypatch.setattr(config_safety, "GLOBAL_CONFIG", magent_config.GLOBAL_CONFIG)
    monkeypatch.setattr(config_safety, "BACKUP_DIR", magent_config.CONFIG_DIR / "backups")
    magent_config.create_user("alice")
    magent_config.set_current_user("alice")
    magent_config.save_global_config(
        {
            "defaults": {"provider": "ollama", "model": "qwen"},
            "providers": {"opencode-go": {"api_key": "do-not-print"}},
        }
    )

    backup = config_safety.backup_config("alice")
    config_ux.set_default_provider("mistral", "mistral-large-latest", api_key_env="MISTRAL_API_KEY")
    diff = config_safety.diff_config(backup["backup_id"], "alice")
    restored = config_safety.restore_config(backup["backup_id"], "alice")
    shown = config_safety.show_config("alice")

    assert backup["ok"] is True
    assert "mistral" in diff["diffs"]["global"]
    assert restored["ok"] is True
    assert shown["files"]["global"]["exists"] is True
    assert "do-not-print" not in shown["files"]["global"]["text"]
    assert 'api_key = "***"' in shown["files"]["global"]["text"]
    assert config_safety.list_config_backups()["backups"]


def test_provider_readiness_accepts_inline_keys(tmp_path: Path, monkeypatch) -> None:
    redirect_config(monkeypatch, tmp_path)
    magent_config.create_user("alice")
    magent_config.set_current_user("alice")
    result = config_ux.set_default_provider(
        "opencode-go",
        "deepseek-v4-flash",
        api_key="inline-secret",
        access_mode="subscription",
    )

    matrix = {item["id"]: item for item in config_ux.provider_matrix()["providers"]}
    explained = config_ux.provider_explain("opencode-go")
    doctor = config_ux.doctor_actions("alice")

    assert result["config"]["api_key"] == "***"
    assert matrix["opencode-go"]["ready"] is True
    assert matrix["opencode-go"]["credential_configured"] is True
    assert explained["ready"] is True
    assert explained["credential_configured"] is True
    assert next(item for item in doctor["actions"] if item["key"] == "opencode_go")["ok"] is True


def test_cli_provider_builder_requires_missing_api_key() -> None:
    cfg = Config(
        {
            "defaults": {"provider": "opencode-zen", "model": "deepseek-v4-flash"},
            "providers": {"opencode-zen": {"api_key_env": "OPENCODE_ZEN_KEY"}},
        }
    )

    try:
        build_provider(cfg, None, None)
    except ProviderCredentialError as exc:
        assert exc.provider_id == "opencode-zen"
        assert exc.env_var == "OPENCODE_ZEN_KEY"
        assert "magent configure" in str(exc)
    else:
        raise AssertionError("expected missing credential error")


def test_cli_provider_builder_can_use_image_maker_role() -> None:
    cfg = Config(
        {
            "defaults": {"provider": "ollama", "model": "qwen2.5-coder:32b"},
            "models": {"image_maker": "openai/gpt-image-1"},
            "providers": {"openai": {"api_key": "inline-secret"}},
        }
    )

    provider = build_provider_for_role(cfg, "image_maker")

    assert provider.provider_id == "openai"
    assert provider.model == "gpt-image-1"


def test_config_proposals_events_permissions_and_model_health(tmp_path: Path, monkeypatch) -> None:
    redirect_config(monkeypatch, tmp_path)
    monkeypatch.setattr(config_safety, "CONFIG_DIR", magent_config.CONFIG_DIR)
    monkeypatch.setattr(config_safety, "GLOBAL_CONFIG", magent_config.GLOBAL_CONFIG)
    monkeypatch.setattr(config_safety, "BACKUP_DIR", magent_config.CONFIG_DIR / "backups")
    monkeypatch.setattr(workbench_store, "USERS_DIR", magent_config.USERS_DIR)
    monkeypatch.setenv("MISTRAL_API_KEY", "secret")
    magent_config.create_user("alice")
    magent_config.set_current_user("alice")
    store = WorkbenchStore("alice")

    proposal = propose_config_change(
        store,
        "make mistral the default provider, set review to mistral, use manual memory, cap 2 subagents, paranoid permissions",
        "alice",
    )
    applied = apply_config_proposal(store, proposal["proposal"]["id"], "alice")
    events = list_events(store)
    shown = show_event(store, events["events"][0]["id"])
    discarded = discard_config_proposal(store, proposal["proposal"]["id"])
    permission = permission_set("alice", "balanced")
    health = config_ux.model_role_health()

    assert proposal["ok"] is True
    assert "mistral" in proposal["proposal"]["diff"]["global"]
    assert applied["ok"] is True
    assert applied["backup"]["backup_id"]
    assert events["events"][0]["kind"] == "config.applied"
    assert shown["ok"] is True
    assert discarded["ok"] is True
    assert permission["mode"] == "balanced"
    assert permission_status("alice")["mode"] == "balanced"
    assert any(row["role"] == "review" and row["ok"] for row in health["roles"])
    assert any(row["role"] == "image_maker" for row in health["roles"])
