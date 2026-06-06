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

Run `magent doctor` after changing config. It checks dependencies, providers, MagGraph memory, semantic memory, MCP, gateway settings, and docs coverage.
