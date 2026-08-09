# Execution Runtime

MagAgent's durable execution runtime is the shared lifecycle contract for interactive
sessions, one-shot asks, goals, recipes, subagents, gateways, daemon jobs, and desktop
work. It is intentionally separate from the older personal task list exposed by
`magent task`.

## Task schema

Task snapshots use schema version `magent.task.v1` and live in the current user's
`workbench/task_runtime.sqlite3` database. Every task records:

- a stable task ID, kind, title, state, project ID/path, and optional session ID;
- an optional parent task ID for subagents and staged work;
- planning/execution model roles and permission policy;
- creation, update, start, and finish timestamps plus the current attempt;
- token/cost usage, changed files, checkpoints, final audit, and extensible metadata.

States are `queued`, `planning`, `running`, `waiting`, `blocked`, `validating`,
`completed`, `failed`, and `cancelled`. Invalid transitions are rejected before
storage. Retrying a terminal or blocked task returns it to `queued` and increments
its attempt.

## Event schema

Events use schema version `magent.task-event.v1`. They are append-only, have a
strictly increasing sequence within a task, and are written in the same SQLite
transaction as lifecycle changes. Consumers can reconnect with an event cursor:

```bash
magent execution events TASK_ID --after 12 --jsonl
```

Each JSONL line contains `event_id`, `task_id`, `sequence`, `schema_version`,
`type`, `ts`, `state`, and `detail`. Renderers should tolerate unknown event types
and detail fields so compatible additions do not require a schema-version change.

## Commands

```bash
magent execution create "Fix the failing tests" --kind ask --project .
magent execution list --state running
magent execution show TASK_ID
magent execution events TASK_ID --jsonl
magent execution pause TASK_ID
magent execution resume TASK_ID
magent execution cancel TASK_ID
magent execution retry TASK_ID
```

All commands return JSON except `events --jsonl`. The corresponding desktop API
helpers are `execution_tasks`, `execution_task`, and `execution_task_action`.

## Current integrations

- Daemon queue entries receive an execution task ID and atomically record running,
  completion/failure, return-code audit, and legacy queue identity. Running workers
  poll durable control state and terminate a child command promptly when cancelled;
  pausing returns the queue item to pending so it can resume as a new attempt.
- Orchestrated goals create one parent execution task. Every staged subagent step is
  a child task with ordered start/finish events and a final audit.
- `magent ask` records live session logger events, token/cost totals, changed files,
  commands, permission failures, and completion-audit evidence. JSON output includes
  `execution_task_id` so clients can reconnect to the durable stream.
- Interactive sessions use the same event bridge and retain one task ID until the
  session ends. Direct subagents inherit the parent task ID; orchestrated steps attach
  their child session to the step task that the master plan already created.
- Materialized recipes expose a waiting execution task alongside the legacy plan.
  Foreground gateway messages create per-message tasks, while background gateway
  receipts include both queue and execution IDs.
- Command Center can list, reconnect to, pause, resume, cancel, and retry tasks
  without parsing terminal output.

Existing workbench JSON records remain readable as compatibility projections. Pause
and resume are cooperative boundaries: daemon commands stop and restart as a new
attempt, while an in-flight provider request cannot be suspended mid-request.
