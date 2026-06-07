# Desktop Integration

MagAgent exposes stable machine-readable CLI commands for desktop shells such as Mag Command Center. Desktop apps should call these commands instead of importing MagAgent internals.

## Core Commands

- `magent system info`
- `magent readiness --project <path>`
- `magent ask --json --events --project <path> "task"`
- `magent research "topic" --question "focus" --max-sources 8`

## Config

- `magent config get`
- `magent config schema`
- `magent config set <dot.path> <json-or-string>`

`config schema` returns field metadata for guided controls: label, type, category, choices, scope, and current redacted value.

## Memory

- `magent memory graph --query "text" --limit 100`
- `magent memory node <id>`
- `magent memory update-node <id> --preview --body-file node.md`
- `magent memory update-node <id> --body-file node.md`
- `magent memory suppress <id> --reason "stale"`
- `magent memory unsuppress <id>`
- `magent memory merge <target> <source> --preview`
- `magent memory merge <target> <source>`
- `magent memory inbox --json`

`memory update-node --preview` returns old/new body hashes and char counts without writing. Use that before applying desktop edits.

## SQLite

- `magent data sqlite-list`
- `magent data sqlite-tables <db>`
- `magent data sqlite-schema <db> <table>`
- `magent data sqlite-query <db> "select ..."`

Queries are read-only through `sqlite-query`.

## Plugins

- `magent plugin list --json`
- `magent plugin enable <name>`
- `magent plugin disable <name>`
- `magent plugin install <path> --name <name>`
- `magent plugin import opencode <path> --name <name>`
- `magent plugin import claude <path> --name <name>`
- `magent plugin import codex-skill <path> --name <name>`
- `magent plugin mcp import <path> --name <name>`

Plugin action payloads include `ok`, `plugin`, `name`, `enabled` when applicable, and `error` on failure.
