# Tutorial

Start here when you install MagAgent on a new machine or open a new project. The goal is
to teach MagAgent enough about the environment that it can spend fewer tokens guessing and
more tokens doing useful work.

1. Run `magent setup`.
2. Run `magent doctor`.
3. Open a project and run `magent project commands`.
4. Build code intelligence with `magent code index`.
5. Search code with `magent code symbols <query>`.
6. Map tests with `magent test map`.
7. Run targeted tests with `magent test run-related <file>`.
8. Check memory health with `magent memory quality`.
9. Open the local operations dashboard with `magent ui`.
10. Use `magent docs search <query>` whenever you forget a command.

For larger changes, run `magent plan-exec`, inspect with `magent plan-preview`, then apply with `magent plan-apply`.
For patch-first work, save diffs with `magent patch save`, inspect them with
`magent patch preview` and `magent patch explain`, then check the whole
workspace with `magent workspace status`.

Run `magent ui` during a larger session when you want a browser view of plans,
patches, checkpoints, memory quality, command history, docs search, and release
checks.

## First Project Pass

Run these from the repository root:

```bash
magent project commands
magent code index
magent code symbols main
magent test map
```

If `magent project commands` misses something important, add project-local config:

```toml
[commands]
test = "pytest -q"
lint = "ruff check src tests"
build = "python -m build"
```

Then run `magent diagnostics` so the workbench can remember command outcomes.

## Daily Loop

Use `magent ask "task"` for direct one-shot work, or run `magent` for a persistent session.
Before accepting a larger change, run:

```bash
magent review --json --save
magent test related src/package/module.py
magent test explain src/package/module.py
magent test run-related src/package/module.py
```

If an agent edit needs to be undone, inspect the checkpoint session:

```bash
magent checkpoint session-list
magent checkpoint session-diff <session-id>
magent checkpoint session-restore <session-id>
```

## Memory Hygiene

When recall starts feeling noisy, run:

```bash
magent memory quality
magent memory merge <target-id> <source-id> --preview
magent memory merge <target-id> <source-id>
magent memory suppress <node-id> --reason "stale preference"
magent memory unsuppress <node-id>
```

Run `magent memory index` after larger memory changes to refresh semantic search.
