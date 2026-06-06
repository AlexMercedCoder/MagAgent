# Testing And Reliability

MagAgent uses focused unit tests plus CLI smoke tests to keep local agent workflows reliable.

Recommended local checks:

```bash
python -m pytest -q
python -m ruff check src tests
python -m pytest --cov=src/magent --cov-report=term-missing -q
magent docs doctor
```

High-confidence coverage focuses on:

- agent loop tool dispatch and provider failure handling
- workbench plans, checkpoints, code/test intelligence, and reviews
- memory quality controls and semantic memory
- provider routing and config loading
- SQLite data tools and tool result shaping
- packaged docs coverage

Use `magent test explain <file>` when targeted test selection is surprising. Use
`magent plan-apply --dry-run <plan-id>` before executing buffered plan operations.
