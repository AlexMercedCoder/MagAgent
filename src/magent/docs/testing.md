# Testing And Reliability

MagAgent uses focused unit tests plus CLI smoke tests to keep local agent workflows reliable.

Recommended local checks:

```bash
python -m pytest -q
python -m ruff check src tests
python -m pytest --cov=src/magent --cov-report=term-missing -q
magent docs doctor
magent provider test-matrix
magent provider tool-smoke <provider> --model <cheap-model>
```

High-confidence coverage focuses on:

- agent loop tool dispatch and provider failure handling
- workbench plans, checkpoints, code/test intelligence, and reviews
- memory quality controls and semantic memory
- provider routing and config loading
- SQLite data tools and tool result shaping
- packaged docs coverage and local UI endpoints
- terminal UI rendering and streaming behavior
- context maps and explicit workbench-to-memory promotion
- non-interactive ask audits and provider tool-use smoke checks

Use `magent test explain <file>` when targeted test selection is surprising. Use
`magent plan-apply --dry-run <plan-id>` before executing buffered plan operations.

One-shot tasks are non-interactive by default. If a tool action needs a prompt,
the tool returns `permission_required` and the final response includes a task
audit warning. Use `magent ask --yes` only for trusted local tasks where
YOLO-style approval is acceptable.

Use `magent provider test-matrix` to verify lightweight provider pings, then
`magent provider tool-smoke` for the more realistic check that a configured
provider can perform a minimal tool call and create `smoke.txt`.

For release readiness, run `magent release check`. For scriptable reviews, use
`magent review --fail-on P1`.

Use `magent ui` for a live read-only view of workspace status, project doctor,
patches, checkpoints, memory quality, docs search, and release checks while
running local verification.
