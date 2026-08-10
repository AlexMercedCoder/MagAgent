# MagAgent 0.35.1 Release Record

**Status:** Prepared for release on 2026-08-10.

## Scope

This is a security, correctness, durability, and maintainability release built from the
August 2026 full-codebase audit. It preserves the public 0.35 graph and plugin interfaces while
hardening shell, network, gateway, plugin, local HTTP, subprocess, and persistent-state
boundaries.

The release also adds resumable session transcripts, spend limits, memory hygiene, provider
conformance, gateway administration, permission and secret diagnostics, shell sandbox profiles,
and reusable eval suites. CLI memory commands and renderers were extracted from `cli/main.py`,
the duplicated agent loops were consolidated, and the project type-check gate was restored.

## Compatibility

- Python 3.11 through 3.14 remain supported.
- Existing user profiles and project configuration continue to load.
- Gateways with an empty user allowlist now deny requests. Configure explicit user IDs or set
  `allow_anyone = true` intentionally.
- Mutating HTTP requests now require confirmation under balanced permissions.
- Saved shell approvals are matched structurally and may need to be approved again.

## Release Gates

```bash
make lint
pytest tests/unit -q
pytest tests/unit --cov=magent --cov-report=term-missing
magent docs generate-reference --check
magent docs doctor
python -m build
python -m twine check dist/*
```

## Validation Evidence

- Ruff and the project mypy baseline pass.
- 715 unit tests pass on Python 3.14.5 with 65.91% branch coverage against the 64% floor.
- The release includes dedicated permission-bypass, durability, CLI-surface, safe-name,
  gateway, plugin/session-hardening, and feature regression suites.
- CI runs tests on Python 3.11, 3.12, 3.13, and 3.14 and enforces typing and branch coverage.

Publication details are recorded after the Git tag, GitHub release, PyPI upload, and clean-wheel
smoke test complete.
