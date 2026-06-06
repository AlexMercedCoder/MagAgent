# Recipes

## Fix failing CI

1. Run `magent ci --logs --repair-plan --save`.
2. Inspect the saved plan with `magent plan-show <id>`.
3. Run the reproduction command from the repair plan.
4. Patch the smallest failing path.
5. Run `magent review --json --save`.

## Use semantic memory

1. Run `magent memory index`.
2. Search with `magent memory search --semantic "topic"`.
3. Inspect a result with `magent memory show <node-id>`.

## Undo an agent edit

1. Run `magent checkpoint session-list`.
2. Inspect a run with `magent checkpoint session-diff <session-id>`.
3. Restore it with `magent checkpoint session-restore <session-id>`.
4. For the last file edit only, run `magent checkpoint restore-last`.

## Configure a project

1. Create `.magent/config.toml`.
2. Add a `[commands]` table with test, lint, and build commands.
3. Run `magent project commands`.
4. Run `magent diagnostics`.

## Review a change

1. Run `magent review --json`.
2. Save findings with `magent review --save`.
3. Inspect later with `magent review-show <id>`.

## Publish a release

1. Run `magent docs doctor`.
2. Run `magent diagnostics`.
3. Build and check artifacts.
4. Save release artifacts with `magent artifact add`.
5. Check artifact integrity with `magent artifact checksum <id>`.

