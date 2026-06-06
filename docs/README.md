# MagAgent Documentation

This directory is the GitHub-facing documentation index for people browsing the repository.

MagAgent also ships a packaged offline docs bundle. Those source files live in [`src/magent/docs`](../src/magent/docs) and are available after install with:

```bash
magent docs list
magent docs show overview
magent docs search "memory inbox"
magent docs doctor
```

## Core Docs

- [Overview](../src/magent/docs/overview.md)
- [Tutorial](../src/magent/docs/tutorial.md)
- [Commands](../src/magent/docs/commands.md)
- [Generated Command Reference](../src/magent/docs/command-reference.md)
- [Generated Provider Reference](../src/magent/docs/providers.md)
- [Generated Config Reference](../src/magent/docs/config-reference.md)
- [Configuration](../src/magent/docs/configuration.md)
- [Troubleshooting](../src/magent/docs/troubleshooting.md)
- [Performance](../src/magent/docs/performance.md)
- [Agent Definitions](../src/magent/docs/agents.md)
- [Hooks](../src/magent/docs/hooks.md)
- [Code Intelligence](../src/magent/docs/lsp.md)
- [Background Worker](../src/magent/docs/daemon.md)
- [Plugins](../src/magent/docs/plugins.md)

Common setup tasks now have CLI-first flows:

```bash
magent provider set openai --model gpt-5 --api-key-env OPENAI_API_KEY
magent provider matrix
magent provider recommend --goal coding
magent provider test-matrix
magent provider set openai --model gpt-5 --access codex
magent model set-role review anthropic/claude-sonnet-4-5
magent model health
magent memory configure --mode inbox-first
magent permission status
magent config propose "use manual memory and paranoid permissions"
magent config proposals
magent gateway configure telegram --bot-token "$TELEGRAM_BOT_TOKEN"
magent subagent configure --max 3 --parallel 2
magent agent create review-helper
magent hook init
magent lsp diagnostics
magent daemon enqueue shell "pytest -q"
magent plugin list
magent plugin mcp import ./mcp.toml --name filesystem
magent plugin import codex-skill ./SKILL.md
magent project init
magent config backup
magent events list
magent next
```

## Architecture And Workflow

- [Architecture](../src/magent/docs/architecture.md)
- [Workbench](../src/magent/docs/workbench.md)
- [Context Map](../src/magent/docs/context.md)
- [Project Playbooks](../src/magent/docs/playbooks.md)
- [Recipes](../src/magent/docs/recipes.md)
- [Sandboxed Execution](../src/magent/docs/sandbox.md)
- [Evals](../src/magent/docs/evals.md)
- [Patch Workflow](../src/magent/docs/patch-workflow.md)
- [Checkpoints](../src/magent/docs/checkpoints.md)
- [Testing And Reliability](../src/magent/docs/testing.md)

## Memory And Tools

- [Memory](../src/magent/docs/memory.md)
- [Semantic Memory](../src/magent/docs/semantic-memory.md)
- [Tool Capability Packs](../src/magent/docs/tool-packs.md)
- [Browser Automation](../src/magent/docs/browser.md)
- [GitHub Workflows](../src/magent/docs/github.md)
- [Comparisons](../src/magent/docs/comparisons.md)

## Interfaces

- [Terminal UI](../src/magent/docs/tui.md)
- [Local UI](../src/magent/docs/ui.md)

## Gateway Setup

- [Slack Gateway](gateway/setup-slack.md)
- [Discord Gateway](gateway/setup-discord.md)
- [Telegram Gateway](gateway/setup-telegram.md)

## Skill Docs

MagAgent includes repo-level skill documentation under [`docs/skills`](skills). These files describe task-specific patterns for document generation, spreadsheets, PDFs, images, video/audio, data analysis, REST APIs, SQLite, desktop automation, and Git workflows.

## Screenshots, Demos, And Examples

- [Cockpit screenshot mockup](assets/magent-cockpit.svg)
- [Cockpit demo GIF](assets/magent-cockpit-demo.gif)
- [Release prep recipe example](examples/release-prep-recipe.json)

## Keeping Docs Current

Before pushing documentation or command changes, run:

```bash
magent docs doctor
```

The docs doctor checks that the packaged docs contain required topics and mention the live Typer command tree.
