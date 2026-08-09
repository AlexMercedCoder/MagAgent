# MagAgent 0.34.0 Release Prep

## Scope

- Unified durable task and event runtime across CLI, goals, daemon, gateway, and desktop execution.
- Cancellation, parent/child work, artifacts, checkpoints, recovery, and preattached desktop tasks.
- MagGraph 0.4 explainable hybrid memory, global/project recall, backlinks, provenance,
  and crash-safe reviewed batches.
- Deterministic ecosystem readiness reporting with external release gates separated
  from local checks.
- Updated GitHub and built-in roadmap, architecture, memory, configuration, testing,
  desktop integration, command, and TUI documentation.

## Validation Before Release

```bash
PYTHONPATH=src python -m ruff check src tests
PYTHONPATH=src python -m pytest -q
PYTHONPATH=src python -m pytest --cov=magent --cov-report= --cov-fail-under=63 -q
PYTHONPATH=src magent docs generate-reference --check
PYTHONPATH=src magent docs doctor --json
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
