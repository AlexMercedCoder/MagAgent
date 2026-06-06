# Changelog

## 0.21.0

- Added provider UX commands: `magent provider matrix`, `explain`, `env`, `recommend`, and `catalog-doctor`.
- Added generated provider reference docs with `magent docs generate-providers`.
- Added config safety commands: `magent config show`, `backup`, `list-backups`, `diff`, and `restore`.
- Improved project command inference for uv, Poetry, tox, nox, pnpm, bun, and Deno projects.
- Began CLI command extraction with focused provider and config command registration modules.
- Added provider catalog validation and tests to prevent provider metadata drift.

## 0.20.0

- Added first-class setup/UX support for LM Studio, AWS Bedrock, Mistral AI, DeepSeek, xAI, Perplexity, Cerebras, Together AI, Fireworks AI, and DeepInfra.
- Added a shared provider catalog so setup choices, default models, environment variables, access modes, display names, base URLs, and runtime prefixes stay in sync.
- Expanded LiteLLM runtime routing for `mistral`, `deepseek`, `xai`, `perplexity`, `cerebras`, `together_ai`, `fireworks_ai`, and `deepinfra`.
- Updated provider docs, PRD provider tables, and tests for the expanded provider surface.

## 0.19.0

- Added guided UX flows: `magent onboard`, `magent next`, `magent doctor --fix`, `magent doctor --json`, and profile presets.
- Added provider/model/memory/subagent wizard commands for interactive CLI-first setup.
- Added `magent project init` and `magent project wizard` to bootstrap `.magent/config.toml` and `.magent/playbook.toml`.
- Added explicit provider access modes so OpenAI API, OpenAI Codex via ChatGPT plan, OpenCode Zen pay-as-you-go, and OpenCode Go subscription are distinct in setup and diagnostics.
- Updated OpenCode Go defaults to use the Go subscription endpoint and environment variable.

## 0.18.0

- Added CLI-first configuration commands for providers, model roles, memory behavior, gateway tokens, and sub-agent caps.
- Added `magent configure` as a friendlier alias for the first-run setup wizard.
- Added provider/model/gateway/subagent doctor surfaces so users can inspect readiness without hand-editing TOML.
- Made sub-agent orchestration limits configurable and enforced by the sub-agent runner.
- Updated packaged and repository docs for provider, memory, gateway, model-role, and sub-agent setup flows.

## 0.16.0

- Added sandboxed plan and recipe execution with worktree, copy, and Docker container modes.
- Added local eval suite scaffolding and reports with `magent eval`.
- Added optional Playwright browser snapshot and screenshot commands plus agent tools.
- Added GitHub issue, PR, and checks commands backed by the authenticated `gh` CLI.
- Upgraded the local UI into a cockpit view with pending plans, memory inbox, recipes, sandbox runs, failed commands, and release checks.
- Added comparison docs, sandbox/eval/browser/GitHub docs, repo screenshot/demo assets, and recipe examples.
- Continued modularization with sandbox, eval, browser, GitHub, cockpit, and tool capability helper modules.

## 0.15.0

- Added workflow recipes with `magent recipe list/show/save/run`, including built-in release prep, bug triage, docs audit, dependency upgrade, and test repair routines.
- Added `.magent/playbook.toml` support plus `magent project playbook` for project-specific command routines, release checklists, review rules, and context defaults.
- Added `magent memory inbox` to review, accept, reject, and edit memory candidates before writing to MagGraph.
- Added tool capability packs with `magent tools list/explain/enable/disable` and runtime filtering for files, shell, web, data, db, and desktop tools.
- Added actionable local UI endpoints and controls for memory promotion, release checks, patch previews, and checkpoint diffs.
- Updated architecture documentation to explain recipes, playbooks, tool packs, memory inbox, and shared UI action handlers.

## 0.14.3

- Added `magent.cli.command_context` as the shared helper surface for future CLI command modules.
- Added workbench domain modules for plans, patches, checkpoints, project helpers, code/test intelligence, and release/workspace helpers.
- Added tool helper modules for shared tool result types, budgets, schema building, and archive extraction safety.
- Added typed record helpers for tasks, plans, and memory-promotion candidates.
- Updated context promotion to write through the typed promotion candidate record.
- Expanded architecture and compatibility tests for command context, workbench domains, tool helpers, and typed records.

## 0.14.2

- Extracted Typer app and command-group composition into `magent.cli.app` while preserving `magent.cli.main:app`.
- Added compatibility coverage for the shared CLI app object and registered command groups.
- Updated architecture documentation to reflect CLI app composition as a separate boundary.

## 0.14.1

- Moved the tool executor implementation into `magent.tools.executor` while preserving `from magent.tools import ToolExecutor`.
- Extracted JSON-backed workbench storage primitives into `magent.workbench_store` while preserving `from magent.workbench import WorkbenchStore`.
- Added packaged architecture documentation for memory, workbench, context, tools, CLI/TUI, and compatibility boundaries.
- Added compatibility tests for public tool and workbench imports.

## 0.14.0

- Added `magent context map` to show memory, workbench, project doctor, command-role, and promotion-candidate state together.
- Added `magent memory promote` to list or promote workbench facts into durable MagGraph memory.
- Added promotion candidates for project command profiles, open tasks, pending/failed plans, command failures, and review findings.
- Added packaged context-map documentation and tests for context aggregation, promotion, and CLI flows.

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
