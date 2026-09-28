# Releasing MagAgent

The package version in `pyproject.toml` stays at the last release until the release commit.
Work in progress collects under `## Unreleased` in [CHANGELOG.md](../CHANGELOG.md).

## 1. Prerequisites

- Every package MagAgent requires must be on PyPI at a version the pins accept. For 1.4.0 that
  means `agent-approval-interchange` 0.2.0 (`>=0.2.0,<0.3`) must be published first; until then
  a clean install, and CI, cannot resolve MagAgent.
- CI is green on the release commit, including the slow-test job and the packaged-acceptance
  matrix on Ubuntu, macOS and Windows.

## 2. Version bump (one release-preparation commit)

1. `pyproject.toml` `version` and `src/magent/__init__.py` `__version__`.
2. `webui/package.json` `version`, and `version` plus `packages[""].version` in
   `webui/package-lock.json`.
3. `implementation_version` in `docs/ags-conformance.json` and `docs/oap-conformance.json`,
   after the conformance tests pass against the pinned fixtures.
4. `CHANGELOG.md`: replace `## Unreleased` and its `Target:` and prerequisite lines with
   `## X.Y.Z (YYYY-MM-DD)`.
5. Add `docs/RELEASE_NOTES_X.Y.Z.md` and point the README `Current release: **X.Y.Z**` line at
   it.

Then check, as CI will on the tag:

```bash
GITHUB_REF=refs/tags/vX.Y.Z python scripts/check_release_metadata.py --strict
python -m ruff check src tests scripts
python -m mypy src/magent
python -m pytest -q
python -m pytest -q -m slow
```

The 1.4.0 bump was rehearsed in a scratch worktree on 2026-09-27. The strict check passed. The
default suite at 1.4.0 had two failures, both since fixed: a test that hard-coded the 1.3.0
changelog heading, and a LiteLLM logging drain that could hang.

## 3. Build and verify

```bash
rm -rf dist build
python -m build
python -m twine check dist/*
python -m venv /tmp/magent-release-smoke
/tmp/magent-release-smoke/bin/python -m pip install dist/mag_agent-*.whl
/tmp/magent-release-smoke/bin/magent --version
/tmp/magent-release-smoke/bin/magent doctor
```

## 4. Tag and publish

- Create an annotated tag `vX.Y.Z` on the release commit and push the commit and tag. The CI
  workflow runs on `v*` tags and fails on any release-metadata drift.
- Publish the built files with `python -m twine upload dist/*` (a scoped PyPI token or trusted
  publishing). No workflow in this repository uploads to PyPI.
- Create the GitHub release from the changelog section.
- Install from PyPI in a clean environment and repeat the smoke commands above.
