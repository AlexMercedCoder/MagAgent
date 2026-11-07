# MagAgent 1.4.2

Release notes, November 7, 2026.

A patch release that closes two gaps left after 1.4.1. The full list is in the
[CHANGELOG](../CHANGELOG.md#142-2026-11-07).

## Fixes

- **Command criteria run in your shell sandbox.** With `permissions.shell_sandbox` set to
  `bubblewrap` or `docker`, a node's agent ran its shell inside the sandbox while the node's
  command criteria ran outside it. Criteria now use the same profile, and
  `permissions.shell_sandbox_network`.
- **Stored graph runs validate as AGS run records.** Saved runs carried the workbench store's
  `id` and `created_at` keys, which the AGS run-record schema rejects. New runs are saved without
  them, and `magent graph resume`, `magent graph status` and the desktop graph catalog drop them
  from runs saved by earlier versions.

## Upgrading

```bash
python -m pip install --upgrade mag-agent
```
