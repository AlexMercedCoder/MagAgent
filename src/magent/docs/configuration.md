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

Run `magent doctor` after changing config. It checks dependencies, providers, MagGraph memory, semantic memory, MCP, gateway settings, and docs coverage.

