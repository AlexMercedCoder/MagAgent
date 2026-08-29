# MagAgent 1.0.0 — Release Record

Released on 2026-08-29.

MagAgent 1.0.0 closes the major local Web UI gaps identified against modern coding-agent harnesses
while preserving MagAgent's local-first, governed execution model.

## Delivered

- A secure workspace and artifact explorer with previews, browser uploads, and bounded message
  context references.
- Working/staged Git diffs, file staging/unstaging/discard, branch/worktree inspection and managed
  worktree creation/removal, with confirmations on destructive controls.
- A bounded command console that executes argument vectors without a shell.
- A consolidated run center for chat runs, graph history, durable execution tasks, lifecycle
  actions, governed graph schedules, and opt-in completion notifications.
- A discoverable extension inventory for built-in tool backends, Playwright browser readiness,
  plugins and their integrity status, skills, and MCP server names.
- Packaged React assets, API and lifecycle tests, and complete user/security documentation.
- Release-smoke coverage for the installed CLI startup path, including non-serializable live
  server and scheduler handles.

## Security Boundaries

The UI remains bound to loopback and every request requires the per-launch token. All mutations
require CSRF. Workspace paths and symlink targets are confined, MagAgent internal state is hidden
except for its attachment directory, requests/uploads/context/output are bounded, plugin enablement
uses the existing integrity verifier, and no MCP or provider credential is returned.

Schedules are project-scoped and run only while the local server is alive. They use the normal graph runner and do not
bypass validation, budgets, isolation, permissions, digests, or human gates. The UI is responsive,
but is not a remote synchronization service.

## Release Gate

Before tagging, run:

```bash
ruff format --check src tests
ruff check src tests
mypy src/magent
pytest -q
npm --prefix webui ci
npm --prefix webui test -- --run
npm --prefix webui run build
python -m build
python -m twine check dist/*
```

The committed files in `src/magent/webui/static/` must match a clean Vite build from `webui/`.
