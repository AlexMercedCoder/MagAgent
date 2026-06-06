# Configuration

Global config lives at:

`~/.config/magent/config.toml`

User profile config lives at:

`~/.config/magent/users/<user>/profile.toml`

Common settings:

- default provider and model
- permission mode
- memory write behavior
- semantic memory provider and model
- model routing roles for coding, review, memory, cheap, and fallback use
- context compaction budgets
- MCP server definitions
- gateway adapter settings
- per-tool output budgets
- project-local `.magent/config.toml` commands and preferences

Project-local config:

`<project>/.magent/config.toml`

Example:

```toml
[commands]
test = "pytest -q"
lint = "ruff check src tests"
build = ["python -m build"]
```

Provider role routing lets you keep a strong default model while steering specific work to
cheaper or more specialized models:

```toml
[models]
coding = "openai/gpt-4.1"
review = "anthropic/claude-sonnet-4"
memory = "ollama/qwen2.5:7b"
cheap = "opencode-go/deepseek-v4-flash"
fallback = ["ollama/qwen2.5-coder:32b", "openrouter/deepseek/deepseek-chat"]
```

Run `magent doctor` after changing config. It checks dependencies, providers, model
routing, MagGraph memory, semantic memory, MCP, gateway settings, and docs coverage.
