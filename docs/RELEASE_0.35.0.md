# MagAgent 0.35.0 Release Record

**Status:** Released on 2026-08-10.

## Scope

- Agentic Graph Specification 1.0 conformance level 3 runtime and portable run records.
- Strict validation, deterministic plan review, typed AGX expressions, branching, gates,
  retries, budgets, loops, maps, subgraphs, compensation, and digest-guarded resume.
- Project-aware graph generation, graph catalog, plan/recipe/plugin export, bundled schemas,
  examples, authoring skill, and offline documentation.
- Unified graph execution through orchestrated goals, daemon jobs, gateways, desktop APIs,
  task records, permission ceilings, and isolated workspaces.
- Safe Pi package compatibility for portable skills, prompts, context, and MCP configuration,
  with runtime-specific extensions quarantined behind an explicitly granted Pi bridge.

## Local Release Gates

```bash
ruff check src tests
pytest -q
pytest --cov=magent --cov-report= --cov-fail-under=63 -q
magent docs generate-reference --check
magent docs doctor
python -m build --no-isolation
python -m twine check dist/*
```

The AGS-focused suite additionally validates upstream invalid fixtures, strictly validates every
packaged example, and structurally executes every packaged YAML graph without provider calls or
side effects.

## Publication

- Clean wheel installation and `magent graph validate/plan` smoke checks completed.
- Final diff and credential-pattern checks completed.
- Published as Git tag and GitHub release `v0.35.0` and PyPI package `mag-agent==0.35.0`.
- Mag Command Center `0.3.0` can use this release for its graph workbench integration.

## Validation Evidence

Validated locally on Linux with Python 3.14.5 on 2026-08-10:

- Ruff passed.
- 478 tests passed with 65.82% coverage against the 63% release floor, including the Pi
  compatibility importer, path boundary, integrity, permission, and bridge diagnostics.
- Strict type checking passed for MCP, session messaging, and messaging tools.
- The standalone Pi compatibility adapter passed strict focused type checking.
- Built `mag_agent-0.35.0.tar.gz` and `mag_agent-0.35.0-py3-none-any.whl`.
- Twine accepted both distributions.
- A clean wheel install reported `MagAgent 0.35.0` and successfully ran strict graph validation
  and deterministic graph planning against the canonical minimal example. A subsequent isolated
  wheel smoke test exposed the Pi import/bridge commands and passed packaged documentation doctor.
- Built-in documentation doctor reported no missing topics or commands and a current generated
  command reference.
