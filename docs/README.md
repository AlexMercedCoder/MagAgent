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
- [Configuration](../src/magent/docs/configuration.md)
- [Troubleshooting](../src/magent/docs/troubleshooting.md)

## Architecture And Workflow

- [Architecture](../src/magent/docs/architecture.md)
- [Workbench](../src/magent/docs/workbench.md)
- [Context Map](../src/magent/docs/context.md)
- [Project Playbooks](../src/magent/docs/playbooks.md)
- [Recipes](../src/magent/docs/recipes.md)
- [Patch Workflow](../src/magent/docs/patch-workflow.md)
- [Checkpoints](../src/magent/docs/checkpoints.md)
- [Testing And Reliability](../src/magent/docs/testing.md)

## Memory And Tools

- [Memory](../src/magent/docs/memory.md)
- [Semantic Memory](../src/magent/docs/semantic-memory.md)
- [Tool Capability Packs](../src/magent/docs/tool-packs.md)

## Interfaces

- [Terminal UI](../src/magent/docs/tui.md)
- [Local UI](../src/magent/docs/ui.md)

## Gateway Setup

- [Slack Gateway](gateway/setup-slack.md)
- [Discord Gateway](gateway/setup-discord.md)
- [Telegram Gateway](gateway/setup-telegram.md)

## Skill Docs

MagAgent includes repo-level skill documentation under [`docs/skills`](skills). These files describe task-specific patterns for document generation, spreadsheets, PDFs, images, video/audio, data analysis, REST APIs, SQLite, desktop automation, and Git workflows.

## Keeping Docs Current

Before pushing documentation or command changes, run:

```bash
magent docs doctor
```

The docs doctor checks that the packaged docs contain required topics and mention the live Typer command tree.
