# Changelog

## 0.13.0

- Polished the Rich terminal UI with a compact adaptive startup banner and shared `TuiTheme` styles.
- Added reusable status and error line renderers for checkpoint, memory, command, and agent events.
- Updated response rendering to display non-streamed answers in a `MagAgent` Markdown panel.
- Changed streaming output to avoid duplicating the final answer by default while retaining an opt-in final Markdown render.
- Added packaged terminal UI documentation and capture-based TUI tests.

## 0.12.0

- Added `magent ui`, a live local operations dashboard served on `127.0.0.1`.
- Added read-only UI endpoints for workspace state, docs search/topic reads, release checks, and release notes.
- Added packaged `ui` documentation and updated command docs, tutorial, workbench docs, and README references.
- Added unit coverage for UI state aggregation, rendered HTML, local HTTP serving, and CLI startup behavior.

## 0.11.0

- Added patch-first workflow commands: `magent patch preview` and `magent patch explain`.
- Added project command roles and `magent project doctor`.
- Added `magent workspace status` and `magent workspace clean-report`.
- Added `magent release check` and `magent release notes`.
- Added `magent review --fail-on <priority>` for scriptable review gates.
- Added packaged patch workflow documentation.
- Improved review summaries with scriptable failure thresholds.

## 0.10.0

- Added reliability-focused test coverage for the agent loop, CLI smokes, config, providers, DB tools, logging, memory quality controls, and tool behavior.
- Improved `magent plan-apply` with `--dry-run`, saved stdout/stderr excerpts, and failed status reporting when operations or checks fail.
- Expanded test intelligence to cover `*_test.py`, JS/TS `.test.*`, Go `_test.go`, and Rust `_test.rs` patterns.
- Added `magent test explain <file>` to show why related tests were selected.
- Added project-local `{tests}` command template support for targeted test runs.
- Added `magent memory merge --preview` and `magent memory unsuppress`.
- Fixed related-code/test lookups for absolute paths inside the project.
- Fixed SQLite table listing so user tables are no longer hidden by SQL wildcard behavior.

## 0.9.0

- Added code intelligence index commands.
- Added test mapping and related-test commands.
- Added memory quality controls.
- Added provider role config and built-in tutorial documentation.
