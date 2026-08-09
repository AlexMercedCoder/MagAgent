# Testing And Reliability

MagAgent uses focused unit tests plus CLI smoke tests to keep local agent workflows reliable.
The CI coverage gate is ratcheted to the measured unit-suite floor so it catches
regressions without overstating the current full-package percentage.

Recommended local checks:

```bash
python -m pytest -q
python -m ruff check src tests
python -m pytest tests/unit --cov=magent --cov-report=term-missing:skip-covered
magent docs doctor
magent readiness
magent provider test-matrix
magent provider tool-smoke <provider> --model <cheap-model>
```

Pytest is configured with `src/` first on its import path, and the suite refuses to
start if it resolves `magent` from a globally installed package instead of the current
checkout. This keeps local coverage and release validation tied to the code under
review without requiring developers to alter their global MagAgent installation.

Resource warnings and pytest unraisable-exception warnings are errors. Cached user
database connections are closed after every test, while production processes register
the same cleanup for shutdown. Semantic-memory SQLite operations use short-lived,
transactional connections that always release their file handles.

The current baseline is 410 passing tests and 64.57% branch coverage. The configured
63% floor is a regression gate, not the end target; new extracted runtime modules
should aim for at least 85% behavioral coverage.

High-confidence coverage focuses on:

- agent loop tool dispatch and provider failure handling
- workbench plans, checkpoints, code/test intelligence, and reviews
- memory quality controls and semantic memory
- provider routing and config loading
- SQLite data tools and tool result shaping
- system, clipboard, notification, image-inspection, and archive safety contracts
- packaged docs coverage and local UI endpoints
- terminal UI rendering and streaming behavior
- context maps and explicit workbench-to-memory promotion
- non-interactive ask audits and provider tool-use smoke checks
- opt-in orchestrated goal plan creation, dry-run preview, retry/resume, background queueing, model-role diagnostics, and sub-agent step packet contracts

Use `magent test explain <file>` when targeted test selection is surprising. Use
`magent plan-apply --dry-run <plan-id>` before executing buffered plan operations.

One-shot tasks are non-interactive by default. If a tool action needs a prompt,
the tool returns `permission_required` and the final response includes a task
audit warning. Use `magent ask --yes` only for trusted local tasks where
YOLO-style approval is acceptable.

Use `magent provider test-matrix` to verify lightweight provider pings, then
`magent provider tool-smoke` for the more realistic check that a configured
provider can perform a minimal tool call and create `smoke.txt`.
Use `magent provider models <provider> --refresh` when a provider changes model
IDs, and `magent model health` to review recent smoke outcomes.

For release readiness, run `magent release check`. For scriptable reviews, use
`magent review --fail-on P1`.

Use `magent ui` for a live read-only view of workspace status, project doctor,
patches, checkpoints, memory quality, docs search, and release checks while
running local verification.
