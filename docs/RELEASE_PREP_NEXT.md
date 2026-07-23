# MagAgent 0.32.13 Release Prep

## Scope

- Resumable orchestrated goals with `magent goal-run <plan-id>`.
- Dry-run packet preview with `magent goal-run <plan-id> --dry-run`.
- Failed-step retry with `magent goal-run <plan-id> --retry-step N`.
- Background staged plans through `magent goal --orchestrated --background` and daemon task kind `orchestrated_goal`.
- Planning/execution model-role readiness with `magent model orchestration-doctor`.
- Updated CLI, packaged docs, README, daemon docs, architecture notes, and test coverage.

## Validation Before Release

```bash
PYTHONPATH=src python -m ruff check src tests
PYTHONPATH=src python -m pytest tests/unit -q
PYTHONPATH=src python -m pytest tests/unit --cov=magent --cov-report= --cov-fail-under=63 -q
PYTHONPATH=src python -m magent.cli.main docs generate-reference --check
PYTHONPATH=src python -m magent.cli.main docs doctor --json
python -m build --outdir /tmp/magent-dist-next
```

## Manual Smoke

```bash
magent goal "Ship a small staged task" --orchestrated --orchestrated-steps 2
magent goal-run plan_0001 --dry-run
magent model orchestration-doctor
```

Run a live `magent goal-run plan_0001` smoke only when provider quota is acceptable.
