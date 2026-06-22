# Changelog

## 0.32.5

- Added bounded artifact recovery for providers that repeatedly call `write_file` with `path` but no `content`: MagAgent now asks once for the raw artifact body with tools disabled, then writes it through the native file tool.
- Rejected filename-only recovered artifacts so a failed HTML generation cannot create a file containing only `cheese.html` or `oranges.html`.
- Reduced duplicate terminal noise when the loop guard stops a turn: the inline `stop` diagnostic stays short while the full verifier details are returned once.

## 0.32.4

- Fixed file mutation verification so a later successful absolute-path write clears an earlier relative-path failure for the same file.
- Suppressed noisy LiteLLM remote cost-map network warnings in interactive sessions.
- Tightened missing-`content` recovery guidance for `write_file` so artifact recovery avoids unnecessary research/read loops.

## 0.32.3

- Added Hermes/OpenCode-inspired model-specific tool-use enforcement for tool-sensitive model families such as DeepSeek, Qwen, Gemini, GPT/Codex, Grok, and GLM.
- Added configurable agent loop controls for max model rounds, max tool calls, repeated identical tool calls, same-tool failures, doom-loop policy, and file mutation verification.
- Added targeted corrective steering for failed tool calls, including `write_file` calls missing the required `content` argument.
- Added turn-end file mutation verification so unresolved failed writes are surfaced in the final response instead of being accidentally summarized as complete.
- Improved failed tool timing labels so interactive output includes the failure reason inline.

## 0.32.2

- Added interactive timing markers for model rounds and tool completions so slow research/file-writing turns are easier to diagnose from the terminal.
- Added JSONL timing events for model calls, tool calls, and stopped tool loops.
- Added a repeated-tool guard that stops identical tool requests after three attempts instead of rewriting the same file path indefinitely.
- Added a `write_file` content guard that rejects obvious placeholder payloads such as writing `cheese.html` into `cheese.html`.

## 0.32.1

- Fixed OpenCode Go / DeepSeek-style DSML pseudo tool calls being printed as assistant text instead of executed as real MagAgent tool calls.
- Added retry handling for truncated DSML tool markup so interactive sessions do not dump partial generated files into the terminal.
- Added regression coverage for streamed and non-streamed pseudo `write_file` tool calls.

## 0.32.0

- Added `magent goal` and `/goal` for measurable implement/verify/review goal loops with durable plan records and optional daemon queueing.
- Added `magent jobs`, `/jobs`, `magent statusline`, and `/statusline` for daily-driver background task and statusline UX.
- Added `magent context audit`, `/context`, and `magent config ux`/`/config` control-center summaries for context hygiene and CLI-first configuration.
- Added built-in `verify-and-review` and `context-hygiene` recipes.
- Added Gemini CLI-style plugin import support with `magent plugin import gemini <path>`.
- Updated README and built-in docs for goal loops, context hygiene, statusline, jobs, and Gemini migration.

## 0.31.2

- Refused shell-based file writes such as heredocs, redirection, `tee`, `touch`, and Python write snippets with clear guidance to use `write_file`/`edit_file`.
- Strengthened agent and tool descriptions so generated files are written through native file tools instead of permission-heavy shell workarounds.
- Added periodic `Still running <tool>...` feedback for long-running tool calls in interactive sessions.
- Allowed harmless `python3 -c 'print(...)'` probes without prompting while keeping arbitrary Python execution gated.

## 0.31.1

- Auto-approved read-only `curl`/`wget` inspection pipelines while keeping uploads, downloads, and mutating HTTP methods confirmation-gated.
- Made shell approval prompts visibly acknowledge approved commands and report completion for confirmed shell actions.
- Added macOS shell normalization so ambiguous `pip ...` and `python ...` commands run as `python3 -m pip ...` and `python3 ...`.
- Documented the Python interpreter mismatch behind `pip install --upgrade mag-agent` failures on Macs.

## 0.31.0

- Added provider-aware prompt caching support with stable prompt prefixes, cache request hints, cache telemetry normalization, and `magent cache doctor/status`.
- Added reliable multiline prompt composition with `/compose` plus prompt-toolkit support for newline bindings when terminals support them.
- Improved tool-call robustness by normalizing common argument aliases such as `file_path`/`contents`, preventing raw `KeyError('path')` failures.
- Removed the extra finalizing model call that could emit pseudo tool-call markup without actually writing files.
- Improved shell permission UX with scoped approvals, read-only shell pipeline classification, trusted exact-command patterns, and stop-after-denial behavior.
- Made `magent ask` show progress in human-readable mode while keeping `--json` clean for scripts.
- Made `magent research` render readable terminal output by default, with `--json` for scripts and `--write/--out` for Markdown reports.
- Made `magent plan` project-aware, less generic, and directly saveable into draft or executable plan workflows.
- Organized `magent --help` into useful Rich help panels with prominent Start Here commands.
- Made `magent context map` render a readable terminal briefing by default, with `--json` for the full structured payload, and filtered low-value draft plans from memory promotion candidates.
- Updated README, built-in docs, and regression coverage for the new CLI UX.

## 0.30.2

- Fixed `magent configure` provider smoke tests on Python 3.14 by using `asyncio.run()` instead of looking up a non-existent default event loop.
- Updated web search to prefer the modern `ddgs` package, suppress the old `duckduckgo_search` rename warning when falling back, and filter low-relevance search results before the agent fetches pages.
- Made interactive Ctrl-C shutdown avoid re-entering an already-running event loop.

## 0.30.1

- Raised the MagGraph dependency floor to `maggraph>=0.2.5`, which ships Python 3.14-compatible PyO3 bindings, abi3 wheels, and a fixed Intel macOS wheel publish path.
- Added Python 3.13 and 3.14 package classifiers so supported interpreter versions are clearer on PyPI.

## 0.29.0

- Added desktop integration APIs for Mag Command Center and other local app wrappers.
- Added `magent system info` for machine-readable installation, platform, config path, executable, and user status.
- Added `magent ask --json` with response, session ID, audit, files touched, commands run, and permission failures.
- Added `magent config get` and `magent config set` for redacted machine-readable config inspection and safe dot-path updates.
- Added `magent memory graph` and `magent memory node` for compact JSON memory graph browsing.
- Added `magent data sqlite-list`, `sqlite-tables`, `sqlite-schema`, and `sqlite-query` for safe SQLite database exploration.
- Added tests for desktop API helpers and CLI integration command payloads.

## 0.28.0

- Added provider model discovery and caching with `magent provider models <provider> --refresh` for OpenAI-compatible `/models` endpoints.
- Added model recommendations from live health observations and catalog hints with `magent provider recommend-model` and `magent model recommend`.
- Added durable model health records for provider/model/task outcomes, including latency and tool-use smoke results.
- Extracted provider tool smokes into reusable domain logic and added `magent provider smoke-all`.
- Added explicit provider smoke timeouts so slow or stuck model/tool loops fail cleanly.
- Added `magent readiness` for one concise setup, docs, project, provider, and model readiness report, with optional live smoke.
- Added `magent ask --repair-attempts` and `--strict-audit` so one-shot runs can retry obvious incomplete file tasks and fail CI when audits remain bad.
- Expanded the local UI with readiness, model health, and provider smoke action endpoints.
- Updated tests and docs for provider discovery, model health, readiness, ask repair, and UI cockpit actions.

## 0.27.0

- Made one-shot `magent ask` runs permission-safe by returning structured `permission_required` tool results instead of prompting in non-interactive contexts.
- Added per-run `magent ask --permission-mode` and `magent ask --yes` overrides without persisting config changes.
- Added lightweight one-shot task audits that flag missing requested files and permission-required tool calls after a run.
- Added `magent provider tool-smoke` to run a tiny live provider tool-use smoke test against `write_file`.
- Updated the Nous Portal default model to `deepseek/deepseek-v4-flash` after live smokes showed Hermes aliases need explicit model selection and are less suitable for cheap tool-use checks.
- Added regression coverage for ask audits, non-interactive permission denials, and provider tool-smoke CLI plumbing.
- Updated reliability docs for provider pings, tool smokes, and one-shot audit warnings.

## 0.26.1

- Fixed strict OpenAI-compatible provider loops by stripping SDK/provider-only message fields before sending conversation history back to LiteLLM.
- Added regression coverage for tool-call history sanitization after OpenCode Go rejected `provider_specific_fields`.
- Improved provider readiness diagnostics so inline API keys count as configured without printing secret values.
- Fixed OpenCode Go doctor readiness to reflect subscription credentials instead of reporting a false action item.
- Redacted API keys, tokens, secrets, and passwords from `magent config show` and provider setup return payloads.

## 0.26.0

- Bumped the MagGraph dependency to `maggraph>=0.2.0`.
- Replaced MagAgent's keyword memory scans with MagGraph's native structured search API while keeping the optional semantic sidecar for semantic and hybrid modes.
- Switched memory recall context to MagGraph recall bundles with compact excerpts, links, backlinks, and explicit relevance reasons.
- Routed new memory writes through MagGraph memory-node helpers for consistent `preference`, `project_fact`, `decision`, `task`, `session_summary`, `bookmark`, and `tool_failure` schemas.
- Routed memory merge, suppress, and unsuppress operations through MagGraph's durable quality primitives.
- Added single-file index refresh and change-feed use after memory writes, inbox acceptance, and promotion.
- Updated memory docs and tests for graph-native search, recall provenance, backlinks, and change tracking.

## 0.25.0

- Added MCP-first plugin imports with `magent plugin mcp import` and safe config application through `magent plugin mcp apply`.
- Added compatibility importers for OpenCode, Claude, and Codex-style `SKILL.md` packs.
- Added manifest adapters for native MagAgent manifests, `plugin.json`, `package.json`, `AGENTS.md`, `CLAUDE.md`, `SKILL.md`, and MCP config files.
- Added normalized plugin registry metadata including source URL, compatibility tags, capabilities, permissions, and trust.
- Enabled plugin MCP servers to contribute to runtime config at load time with collision-safe names.
- Updated plugin compatibility docs, generated references, and release coverage.

## 0.24.0

- Added Markdown agent definitions from `.magent/agents/*.md`, user config agents, built-ins, and enabled plugin agent packs.
- Added manual agent invocation with `@review`, `@explore`, `@docs`, and custom agent names.
- Added project hook automation for pre/post tool calls, post-edit events, command failures, memory candidates, and release checks.
- Added LSP-aware code intelligence commands for status, symbols, diagnostics, definitions, and references, with bounded local fallbacks.
- Added a durable local background queue with `magent daemon` for asks, recipes, plans, shell tasks, followups, and gateway background work.
- Added local plugin packaging commands for installable packs containing agents, recipes, skills, tools, and MCP configuration.
- Updated packaged docs, repo docs, architecture docs, generated references, and release tests for the new extension systems.

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
