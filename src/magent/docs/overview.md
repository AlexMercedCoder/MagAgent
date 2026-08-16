# Overview

MagAgent is a terminal-native coding and productivity agent with local-first memory.

Machine clients should inspect `magent system contracts` and the built-in
`support-policy` documentation before using versioned task, event, plugin,
configuration, memory, or MCP surfaces.
The 1.0 release candidate can be audited with `magent system compatibility`. Persistent
state upgrades are backup-first through `magent system migrate`; an older MagAgent refuses
state created by a newer schema instead of guessing.
Maintainers can run `magent system ecosystem-report --root <workspace>` to generate a
credential-free `mag.ecosystem-readiness.v1` artifact. Its local `ok` result never
implies that signing, live-provider, cross-platform, or upstream MCP gates passed.

Core ideas:

- `magent get-started` gives new users a short, accessible path through setup, permissions, profiles, research, and larger workflows.
- `magent ask "..."` runs a one-shot task.
- `magent` starts an interactive Rich terminal session with a compact banner, Markdown response panels, and quiet streaming.
- `magent docs list` shows built-in documentation topics.
- `magent docs show architecture` explains the major code boundaries.
- `magent doctor` checks your local setup.
- `magent tools doctor` checks optional document, media, desktop, browser, gateway, MCP, and LSP capabilities.
- `magent lsp ...` uses installed language servers for code intelligence with bounded local fallbacks.
- `magent memory ...` inspects and manages the MagGraph memory graph.
- `magent graph validate`, `plan`, `generate`, and `run` manage portable Agentic Graph workflows.
- `magent context map` shows memory, workbench, and project state together.
- `magent task`, `magent artifact`, `magent plan`, `magent patch`, `magent dashboard`, and `magent ui` manage local productivity state.

MagAgent stores per-user state under `~/.config/magent/users/<user>/`. Memory lives as Markdown files in MagGraph. Workbench data lives as JSON and SQLite sidecars.
