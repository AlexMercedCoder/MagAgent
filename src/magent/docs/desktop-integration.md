# Desktop Integration

MagAgent exposes stable machine-readable CLI commands for desktop shells such as Mag Command Center. Desktop apps should call these commands instead of importing MagAgent internals.

## Core Commands

- `magent system info`
- `magent readiness --project <path>`
- `magent ask --json --events --project <path> "task"`
- `magent ask --json --events --project <path> --prompt-file <file>` for prompts too large for argv
- `printf '%s' "$KEY" | magent auth add <provider> --api-key-stdin [--storage keyring|config]`
- `magent ask "hello" --provider mock --json` for an offline first run (no key, no network)

`magent ask --json` writes machine output only to stdout: with `--approval-stdio`, AAIS 1.0
NDJSON envelopes, then one result document (a single line when stdout is not a terminal).
Status text goes to stderr. The result includes `response`, `audit`, `scratchpad`,
`session_id`, `execution_task_id` and `memory_evidence`; `--events` adds `events`, including
one `{"type": "memory_recalled", "evidence": {...}}` per turn.

`magent auth add ... --api-key-stdin` prints one JSON object and never the key:
`{"ok": true, "provider": "nous-portal", "storage": "keyring", "account": "provider:nous-portal", "source": "stdin"}`
(or `"storage": "config", "config_path": "..."`). Exit codes: 0 stored, 1 storage failed (for
example no OS keyring; the `hint` suggests `--storage config`), 2 usage error (unknown or local
provider, empty stdin, stdin is a terminal, conflicting options).
- `magent research "topic" --question "focus" --max-sources 8 --project <path> --agent <profile>`

## Remote runtime (experimental)

`magent serve --rpc` exposes the same commands to a remote client over JSON-RPC, with streamed
output, approvals and cancel. See the `rpc-gateway` topic for the `magent.rpc.v1` protocol.

## Open Agent Profiles

Use `magent.oap-profile.v1` for visual profile management:

- `magent agent schema --project <path>` returns the JSON Schema, installed tools, packs,
  skills, MCP servers, provider choices, profile templates, and editor guidance.
- `magent agent preview --input - --project <path>` reads a JSON document on stdin and
  returns validation, dependency diagnostics, inheritance, and effective authority.
- `magent agent apply` reads the document from `--input -` and accepts `--scope`,
  `--project`, and `--expected-digest` to create or conflict-safely update a document.
  Scope may be `user`, `project`, or `portable`.
- `magent agent revisions <name> --project <path>` and `restore-revision` expose guarded
  rollback history.
- `magent agent detail <name> --project <path>` combines the resolved document, effective
  authority, and checkpoints to reduce desktop process startup overhead.
- `clone`, `import`, `export`, and `delete` cover profile lifecycle operations.

Pass profile JSON through stdin. This keeps instructions and annotations out of process
arguments and desktop command history. A profile narrows agent authority; it does not replace
the MagAgent user, project, credential store, or filesystem sandbox. Pin both profile name and
`profile_digest` in a desktop chat session so revision drift is visible rather than silently
changing an existing conversation.

For live desktop asks, create the durable task first and attach the child process:

```bash
magent execution create "task" --kind ask --project <path> --session <session-id>
magent ask --json --events --project <path> --execution-task-id <task-id> "task"
```

`--execution-task-id` is a machine-client option. It lets the desktop poll task
events immediately instead of waiting for the final ask payload. The client remains
responsible for terminating its spawned process when a user requests immediate
cancellation, then recording the durable `execution cancel` transition.

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
- `magent memory batch --operations-json '[...]' --preview`
- `magent memory batch --operations-json '[...]'`

Python hosts can call `desktop_api.memory_recall(user, query, project=...)` for a
`magent.memory-recall.v2` packet containing ranked results, explanations, provenance,
backlinks, bounded Markdown context, and context token statistics. Node detail also
returns backlinks explicitly. Desktop clients should render this contract rather than
reimplementing graph ranking.

### Memory evidence per run

`magent memory evidence [TASK_ID|last] --json` (Python: `desktop_api.memory_evidence(user, task_id="last")`)
returns `magent.run-memory-evidence.v1` (beta):

```json
{
  "ok": true,
  "schema": "magent.run-memory-evidence.v1",
  "source": "task",
  "task_id": "task_...", "run_id": "", "session_id": "...",
  "title": "...", "state": "completed", "provider": "nous-portal", "model": "...",
  "updated_at": "2026-09-27T12:00:00+00:00",
  "turns": [
    {
      "schema": "magent.memory-evidence.v1",
      "turn": 1,
      "recorded_at": "...",
      "status": "used",
      "query_preview": "first 160 characters of the message",
      "nodes": [{"id": "prefers_pytest", "type": "preference", "score": 0.91, "matched": ["body"], "reason": "...", "source": "personal"}],
      "tokens": {"recalled": 812, "injected": 640, "budget": 4000, "profile_reserve": 1200},
      "truncated": false,
      "truncation": []
    }
  ],
  "summary": {"turns": 1, "turns_with_memory": 1, "unique_nodes": ["prefers_pytest"], "tokens_injected": 640, "truncated": false}
}
```

`status` is one of `used`, `no_match`, `unavailable` or `blocked_by_profile`; `truncation`
lists `recall_budget` and/or `profile_reserve`; `score` may be `null`. `last` picks the newest
task that recorded evidence. When nothing matches, the command exits 1 with
`{"ok": false, "schema": ..., "error": ..., "hint": ...}`. The same records are in the task's
`metadata.memory_evidence` (`magent execution show <task-id>`).

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

## Session Coordination

- `magent session peers --json`
- `magent session send <target> <message> --json`
- `magent session inbox <session-id> --json`
- `magent session inbox <session-id> --held --json`
- `magent session accept <session-id> <message-id>`
- `magent session refuse <session-id> <message-id>`
- `magent session receipts <sender-id> --json`
- `magent session doctor`

Python hosts can use `desktop_api.session_messaging_state`,
`desktop_api.session_message_send`, and `desktop_api.session_message_review`. These
facades never expose roster capabilities and keep desktop clients out of transport
internals.

`magent system contracts` publishes the task, event, memory recall, memory batch,
configuration, plugin, MCP, Open Agent Profile editor, and Agentic Graph compatibility levels
used by desktop clients.
