# Patch Workflow

MagAgent supports a patch-first workflow for safer multi-file changes.

```bash
magent patch save --name "auth refactor"
magent patch list
magent patch preview <patch-id>
magent patch explain <patch-id>
magent patch apply <patch-id> --yes
```

Use `magent workspace status` before applying patches to see git status, pending
plans, saved patches, checkpoint sessions, failed checks, and code index state.

For executable plans:

```bash
magent plan-exec "finish the change" --command "pytest -q"
magent plan-preview <plan-id>
magent plan-apply --dry-run <plan-id>
magent plan-apply --yes --run-checks <plan-id>
```

After a change, run `magent review --fail-on P1` to make severe findings fail
local scripts or CI jobs.
