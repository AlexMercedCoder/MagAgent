# Local UI

`magent ui` starts a local-only operations dashboard for the current MagAgent user and project. It is designed for quick situational awareness and small local actions while an agent session is running, not as a hosted service or replacement for the CLI.

## Start the UI

```bash
magent ui
magent ui --project /path/to/project --port 7830
magent ui --open
```

The server binds to `127.0.0.1` and prints the local URL. Press `Ctrl+C` to stop it.

## What It Shows

The UI combines the same local data used by the CLI:

- workspace status and clean-worktree report
- active tasks, plans, patch queue, reviews, and checkpoints
- project doctor output
- memory quality report for the current user
- recent command history and approximate usage stats
- built-in documentation topics and search results
- release readiness checks and release notes endpoints
- memory inbox candidates with a promote action
- saved patch previews and checkpoint diffs
- cockpit state for pending plans, recipes, sandbox runs, failed commands, and release checks

## API Endpoints

The dashboard exposes local JSON endpoints for tooling:

- `/api/state`
- `/api/docs/search?q=memory`
- `/api/docs/topic?slug=overview`
- `/api/release/check`
- `/api/release/notes`
- `/api/cockpit`
- `/api/memory/inbox`
- `/api/memory/promote?id=<candidate-id>`
- `/api/patch/preview?id=<patch-id>`
- `/api/checkpoint/diff?id=<checkpoint-id>`

These endpoints intentionally reuse MagAgent's existing workbench, docs, memory, and release helpers so the browser view stays aligned with CLI behavior.

## Relationship To `magent dashboard`

`magent dashboard` exports a static HTML workbench snapshot. `magent dashboard --serve` serves that snapshot on localhost.

`magent ui` is the interactive local operations view. Use it when you want a live dashboard that can refresh state, run release checks, inspect saved patches, inspect checkpoint diffs, and promote reviewed memory candidates without regenerating a file.
