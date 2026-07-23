# Background Worker

MagAgent has a durable local queue for work that should survive process exits.

## Commands

- `magent daemon enqueue ask "summarize this repo"`
- `magent daemon enqueue recipe release-prep`
- `magent daemon enqueue orchestrated_goal plan_0001`
- `magent daemon enqueue shell "pytest -q"`
- `magent daemon list`
- `magent daemon run-once`
- `magent daemon start`

The queue is stored in the local workbench under `daemon_queue`.

## Task Kinds

- `ask`: run a MagAgent one-shot task.
- `recipe`: run a named recipe.
- `orchestrated_goal`: resume a saved staged plan with `magent goal-run`.
- `plan`: resume or apply a saved plan.
- `shell`: run a local shell command without invoking an LLM.

Each task records status, attempts, output, and errors. Scheduled tasks use ISO timestamps through `--run-at`.

## Followups And Gateways

Due followups can be converted into queue tasks. Gateway messages can also opt into background mode so Slack, Discord, Telegram, or other gateway traffic becomes durable work instead of an in-process request.

## Operating Model

`magent daemon run-once` is useful for cron and tests. `magent daemon start` performs a foreground worker pass. A system service or scheduler can call either command depending on how persistent the local setup should be.
