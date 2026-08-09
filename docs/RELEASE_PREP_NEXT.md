# MagAgent 0.33.0 Release Prep

## Scope

- Dual-era MCP SDK v2 negotiation and typed tools, prompts, resources, completion,
  caching, subscriptions, and consent-gated MRTR support.
- Authenticated local session coordination with policies, durable delivery, receipts,
  retry, CLI/agent tools, and a desktop-facing machine API.
- Completed `ToolExecutor` capability modularization while preserving its public facade.
- Test isolation, resource lifecycle, SQLite cleanup, archive safety, and shell-policy
  hardening.
- Updated GitHub and built-in MCP, messaging, architecture, configuration, testing,
  desktop integration, command, and TUI documentation.

## Validation Before Release

```bash
PYTHONPATH=src python -m ruff check src tests
PYTHONPATH=src python -m pytest -q
PYTHONPATH=src python -m pytest --cov=magent --cov-report= --cov-fail-under=63 -q
PYTHONPATH=src python -m magent.cli.main docs generate-reference --check
PYTHONPATH=src python -m magent.cli.main docs doctor --json
python -m mypy --strict --follow-imports=skip src/magent/mcp src/magent/session_messaging.py src/magent/tools/messaging.py
python -m build --outdir /tmp/magent-dist-next
python -m twine check /tmp/magent-dist-next/*
```

## Manual Smoke

```bash
magent mcp list
magent mcp test <configured-server>
magent session doctor
magent session peers
```

Run a real two-session delivery smoke and an MCP fixture smoke before publishing.
