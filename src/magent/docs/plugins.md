# Plugins

Plugins are installable local extension packs for MagAgent.

## Commands

- `magent plugin list`
- `magent plugin install ./my-pack`
- `magent plugin enable my-pack`
- `magent plugin disable my-pack`

Installed plugins live under `~/.config/magent/plugins`, and enabled state is recorded in `~/.config/magent/plugins.toml`.

## Pack Layout

```text
my-pack/
  magent-plugin.toml
  agents/
  recipes/
  skills/
  tools/
  mcp.toml
```

`magent-plugin.toml` can use either root fields or a `[plugin]` table:

```toml
[plugin]
name = "my-pack"
version = "1.0.0"
description = "Project workflow helpers"
```

## Current Integrations

Enabled plugin `agents/` directories are included in agent discovery. Plugin metadata also records whether the pack contains skills, recipes, tools, and MCP config so future loaders can enable those surfaces without changing the packaging format.

Use plugins for shareable team conventions, specialist agents, reusable recipes, and local MCP/tool configuration bundles.
