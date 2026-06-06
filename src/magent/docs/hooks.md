# Hooks

Hooks let a project run local automation around agent activity.

## Setup

```bash
magent hook init
magent hook list
```

This creates `.magent/hooks.toml`.

## Events

Supported events:

- `pre_tool`
- `post_tool`
- `post_edit`
- `command_failure`
- `memory_candidate`
- `release_check`

## Configuration

```toml
[hooks]
pre_tool = "python scripts/check_tool.py"
post_edit = ["ruff format .", "ruff check . --fix"]
command_failure = "python scripts/record_failure.py"
release_check = "python scripts/release_gate.py"
```

Hook commands receive:

- `MAGENT_HOOK_EVENT`
- `MAGENT_HOOK_PAYLOAD`

Hooks run from the project root with a timeout. Failures are captured and returned to callers instead of crashing the agent.

## CLI

- `magent hook list`
- `magent hook run pre_tool --payload '{"tool":"read_file"}'`

Use hooks for lightweight local checks, notifications, memory filtering, and release gates. Keep expensive work behind explicit commands or daemon tasks.
