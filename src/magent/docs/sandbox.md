# Sandboxed Execution

MagAgent can run saved plans and workflow recipes away from the active working tree.

Commands:

- `magent plan-sandbox <plan-id>`
- `magent plan-sandbox <plan-id> --mode copy`
- `magent plan-sandbox <plan-id> --mode container --image python:3.12`
- `magent plan-apply <plan-id> --sandbox worktree --run-checks`
- `magent recipe sandbox release-prep`

Modes:

- `worktree`: use `git worktree` when available, with a copied workspace fallback.
- `copy`: copy the project into a temporary directory and run plan operations there.
- `container`: copy the project, mount the copy into Docker, and run shell/check commands in the selected image.

Plan operations and checks pass through MagAgent's shared command policy before execution. String commands preserve shell behavior for compatibility; structured command specs such as `{"argv": ["python", "-m", "pytest", "-q"]}` run without a shell. Container mode preflights every planned command with the same policy before building the Docker shell script.

Use `--dry-run` to preview operations and `--keep` or `--keep-sandbox` when you want to inspect the temporary workspace after execution.
