# MagAgent 0.50.0 Release Record

**Status:** Released on 2026-08-10.

## Scope

This release turns reliability into a measured product surface. A versioned real-agent harness
creates isolated repositories, runs the same AgentSession and native tool loop used by users,
captures execution and usage evidence, and validates results independently. Release evidence,
documentation drift, severity, and known-limitations contracts make qualification inspectable.

## Baselines

- Offline AgentSession suite: 32/32 tasks and 20/20 artifact writes passed.
- Nous Portal / DeepSeek V4 Flash live suite: 5/5 tasks and 4/4 artifact writes passed.
- MCP integration fixtures: 3/3 passed with the MCP v2 extra installed.
- Unit suite: 731 unit tests collected after excluding the 3 MCP integration tests; bounded
  parallel halves completed without failures.
- Ruff and mypy pass across 164 source modules.
- Branch-aware package coverage is 64.9% against the 64% regression floor.

Machine-readable reports are committed at:

- `docs/reports/0.50.0-agent-evals.json`
- `docs/reports/0.50.0-nous-live-evals.json`
- `docs/reports/0.50.0-release-evidence.json`

## Known Exception

The roadmap proposed 72% overall branch coverage and a 70% CI floor for this milestone. That
target is not claimed. The measured result remains approximately 65%, dominated by the legacy
`cli/main.py` entrypoint. The existing 64% floor remains enforced; CLI extraction and focused
failure-path coverage move forward as the first 0.60 hardening item. No coverage files are
omitted merely to improve the reported number.

## Release Gates

```bash
python -m ruff check src tests
python -m mypy src/magent
python -m pytest tests/unit -q -n auto
python -m pytest tests/integration -q
magent eval run evals/reliability-offline.json --report-out agent-eval-report.json
magent docs generate-reference --check
magent docs doctor
python -m build
python -m twine check dist/*
```

## Compatibility

- Python 3.11 through 3.14 remain supported.
- MagGraph 0.4.x remains the supported memory family; `maggraph>=0.4.1` is required.
- Task, event, plugin, MCP, and desktop machine contracts are unchanged.
- Legacy command-only eval suites remain supported alongside `magent.agent-eval.v1`.

## Publication

- Git tag and GitHub release: `v0.50.0`
- PyPI package: `mag-agent==0.50.0`
- Published artifacts: source distribution and `py3-none-any` wheel
