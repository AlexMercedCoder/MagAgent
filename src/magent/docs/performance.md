# Performance

MagAgent is designed to stay usable on normal developer laptops. Heavy provider,
browser, gateway, and memory dependencies are loaded lazily where possible, and
repo-wide scans use bounded file iteration.

Useful commands:

```bash
magent performance doctor --json
magent workbench stats
magent workbench prune --dry-run
magent workbench compact
magent profile apply lightweight
```

`magent performance doctor` reports config load time, repo scan estimates,
workbench store sizes, semantic memory index size, and recommendations.

`magent workbench prune` targets high-volume local stores such as events, command
history, checkpoints, sandbox runs, and eval runs. Start with `--dry-run`.
Prune output includes `removed_total`, `changed_stores`, and a suggested next
command so cleanup can be surfaced cleanly in CLI and desktop UIs.

The `lightweight` profile lowers memory and repo-map budgets, disables semantic
memory by default for the active user, and limits sub-agent parallelism.

UI refreshes summarize cached/local state. Long-running actions such as release
checks, tests, and linters are only run through explicit commands or UI buttons.
