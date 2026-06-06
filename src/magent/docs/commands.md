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
- `magent docs generate-reference`: generate command reference Markdown from the live CLI.
- `magent memory stats`: show memory graph stats.
- `magent memory index`: build semantic memory index.
- `magent memory search <query>`: search memory.
- `magent checkpoint list`: list file checkpoints.
- `magent checkpoint restore <id>`: restore a checkpoint.
- `magent checkpoint diff <id>`: compare checkpoint contents with the current file.
- `magent checkpoint restore-last`: restore the most recent checkpoint.
- `magent project commands`: show discovered project test/lint/build commands.
- `magent project config`: show `.magent/config.toml` values.
- `magent plan-run "goal"`: create a pending plan with diff/review context.
- `magent plan-show <id>`: inspect a saved plan record.
- `magent plan-discard <id>`: discard a saved plan.
- `magent review --json`: emit structured review findings.
- `magent ci --repair-plan`: include a local CI repair plan.
- `magent plan --save "goal"`: save a draft plan.
- `magent patch save`: save the current git diff.
- `magent patch apply <id>`: apply a saved patch.
- `magent ci --logs`: inspect recent GitHub Actions failures.
- `magent diagnostics`: run local project diagnostics.
- `magent dashboard --serve`: serve the local dashboard.

Use `magent <command> --help` for command-specific Typer help.
