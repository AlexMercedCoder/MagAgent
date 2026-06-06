# Commands

Important command paths:

- `magent ask "task"`: run a non-interactive task.
- `magent --task "task"`: alternate one-shot task form.
- `magent setup`: run first-time setup.
- `magent doctor`: run install, provider, memory, docs, and integration checks.
- `magent docs list`: list built-in documentation topics.
- `magent docs show <topic>`: render a built-in documentation topic.
- `magent docs search <query>`: search packaged docs.
- `magent docs doctor`: verify built-in docs coverage.
- `magent memory stats`: show memory graph stats.
- `magent memory index`: build semantic memory index.
- `magent memory search <query>`: search memory.
- `magent checkpoint list`: list file checkpoints.
- `magent checkpoint restore <id>`: restore a checkpoint.
- `magent plan --save "goal"`: save a draft plan.
- `magent patch save`: save the current git diff.
- `magent patch apply <id>`: apply a saved patch.
- `magent ci --logs`: inspect recent GitHub Actions failures.
- `magent diagnostics`: run local project diagnostics.
- `magent dashboard --serve`: serve the local dashboard.

Use `magent <command> --help` for command-specific Typer help.

