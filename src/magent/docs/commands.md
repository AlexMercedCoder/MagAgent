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
- `magent tutorial`: show the built-in getting-started tutorial.
- `magent memory stats`: show memory graph stats.
- `magent memory index`: build semantic memory index.
- `magent memory search <query>`: search memory.
- `magent memory quality`: report duplicate-looking and suppressed memory nodes.
- `magent memory merge <target-id> <source-id>`: merge one memory node into another.
- `magent memory suppress <node-id>`: mark a memory node suppressed without deleting it.
- `magent checkpoint list`: list file checkpoints.
- `magent checkpoint restore <id>`: restore a checkpoint.
- `magent checkpoint diff <id>`: compare checkpoint contents with the current file.
- `magent checkpoint restore-last`: restore the most recent checkpoint.
- `magent project commands`: show discovered project test/lint/build commands.
- `magent project config`: show `.magent/config.toml` values.
- `magent code index`: build and save a lightweight Python symbol/import/test index.
- `magent code symbols <query>`: search indexed symbols.
- `magent code related <file>`: show related tests and import peers for a file.
- `magent test map`: map source files to likely test files.
- `magent test related <file>`: show likely tests for a file.
- `magent test run-related <file>`: run likely tests for a file.
- `magent plan-run "goal"`: create a pending plan with diff/review context.
- `magent plan-exec "goal"`: create an executable plan from current diff and optional commands.
- `magent plan-preview <id>`: preview executable plan operations.
- `magent plan-show <id>`: inspect a saved plan record.
- `magent plan-discard <id>`: discard a saved plan.
- `magent review --json`: emit structured review findings.
- `magent review --save`: save structured review findings.
- `magent review-show <id>`: inspect a saved review.
- `magent ci --repair-plan`: include a local CI repair plan.
- `magent ci --repair-plan --save`: save a CI repair plan to the plan ledger.
- `magent project command-history`: show learned command outcomes.
- `magent project command-promote <command>`: save a command into the project profile.
- `magent artifact show <id>`: show artifact metadata.
- `magent artifact checksum <id>`: calculate artifact checksum.
- `magent artifact open <id>`: show artifact path/open metadata.
- `magent checkpoint session-list`: list checkpoint sessions.
- `magent checkpoint session-diff <session-id>`: show combined session diff.
- `magent checkpoint session-restore <session-id>`: restore a session's checkpoints.
- `magent plan --save "goal"`: save a draft plan.
- `magent patch save`: save the current git diff.
- `magent patch apply <id>`: apply a saved patch.
- `magent ci --logs`: inspect recent GitHub Actions failures.
- `magent diagnostics`: run local project diagnostics.
- `magent dashboard --serve`: serve the local dashboard.

Use `magent <command> --help` for command-specific Typer help.
