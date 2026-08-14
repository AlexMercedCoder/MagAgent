# Architecture

## Agentic Graph Runtime

`magent.agraph` is the portable orchestration boundary. `document.py` and `validate.py` own untrusted graph input; `plan.py`, `schedule.py`, and `expressions.py` own deterministic graph semantics; `execute.py` adapts nodes to `AgentSession`, `TaskRuntime`, tool policy, sandbox workspaces, and `WorkbenchStore`; `criteria.py` owns harness-side validation; and `record.py` emits AGS run records. `goal_orchestrator.py` is a compatibility adapter over this engine, not an independent scheduler.

The tool-dispatch boundary consults a task-local graph policy before MagAgent's normal permission policy. This keeps concurrent graph nodes isolated while preserving the user's stricter policy as the final authority.

MagAgent is organized around four local layers. Keeping these layers distinct makes future feature work easier to reason about and keeps MagGraph focused on durable memory rather than operational bookkeeping.

## Layers

### CLI And TUI

`magent.cli.app` composes the Typer app and command groups. `magent.cli.main` remains the console compatibility facade and interactive-session entry point; focused registrations live under `magent.cli.commands.*`. `magent.tui` owns Rich rendering helpers such as the startup banner, response panels, status lines, and streaming output.

Future command modules should register command groups from `magent.cli.commands.*` while preserving `magent.cli.main:app` as the console entry point.

`magent.cli.command_context` owns reusable command helpers such as current-user lookup, store creation, provider construction, and command-tree introspection. New command modules should depend on this helper layer instead of copying setup code.

`magent.cli.commands.*` contains focused command registration modules. Provider UX,
config safety/proposals, permissions, and event-log commands use this pattern first;
future command groups should migrate there incrementally.

`magent.config_ux` owns CLI-first configuration mutations and readiness summaries for providers, model roles, memory behavior, gateway setup, and sub-agent caps. Command handlers should call this module when they need to update global or user TOML instead of editing config dictionaries inline.

`magent.config_proposals` owns schema-limited natural-language config proposals. It
parses only known-safe operations, renders diffs, writes workbench events, creates
backups, and delegates actual mutations to `magent.config_ux` and
`magent.permission_ux`.

`magent.permission_ux` owns friendly permission-mode status, explanations, and mode
changes for user profiles.

`magent.artifact_contracts` infers explicitly requested artifact paths from user
prompts and verifies that those files exist and are not obvious placeholders
before final responses claim success.

`magent.command_policy` centralizes command risk classification for internal
automation surfaces such as hooks, sandbox execution, and update helpers.

`magent.diagnostics` composes deep local checks across project diagnostics,
provider readiness, MCP config, hooks, plugins, permissions, and artifact
contracts.

`magent.ecosystem_readiness` composes versioned MagAgent contracts, provider catalog
validation, packaged docs, MagGraph source/installed capabilities, and Command Center
source metadata into `mag.ecosystem-readiness.v1`. It keeps deterministic local checks
separate from release-operations evidence such as signing and paid provider smokes.

`magent.ux_flows` owns guided onboarding behavior: profile presets, project initialization, safe doctor fixes, and next-action recommendations. It composes config, workbench, memory inbox, and playbook helpers without making those lower-level modules depend on UX prompts.

`magent.provider_catalog` is the shared source of truth for provider metadata: setup labels, default models, environment variables, access modes, display names, LiteLLM routing modes, and OpenAI-compatible base URLs. Provider additions should start there, then add focused tests for runtime model routing and config detection.

`magent.project_scan` owns bounded project file iteration. Repo maps, code
indexes, test maps, and performance diagnostics should use this shared scanner
so file caps, git-aware discovery, and ignored directories remain consistent.

### Agent Runtime

`magent.agent.AgentSession` is the stable compatibility facade. Its runtime is split into typed layers under `magent.agent_runtime`: `context.py` owns prompt/context/provider request assembly, `tool_loop.py` owns provider rounds and bounded tool execution, `lifecycle.py` owns conversation/memory/subagent/session lifecycle, and `support.py` owns shared prompt constants and pure helpers.

`magent.subagents` lets the main agent delegate focused work to child sessions. The runner enforces the configured sub-agent cap and parallelism defaults before spawning child sessions.

`magent.goal_orchestrator` owns the opt-in staged goal flow used by
`magent goal --orchestrated`. It creates a durable cached master plan, derives
bounded step packets with validation criteria, records planning/execution model
role intent, and can run the packets sequentially through `magent.subagents`.
When staged execution runs without an explicit provider/model override, the CLI
resolves the execution provider from the configured execution model role. Saved
plans are resumable through `magent goal-run`, retriable by step, previewable
without model calls, and queueable through the daemon as `orchestrated_goal`
tasks. Default goal loops do not use this path.

`magent.agent_defs` loads built-in, user, project, and plugin-backed Markdown agent definitions. Manual `@review`, `@explore`, and `@docs` invocations are resolved before provider calls so specialist prompts can be reused from chat, one-shot tasks, and future sub-agent orchestration.

`magent.hooks` runs project-local lifecycle hooks around tool calls, edits, command failures, memory candidates, and release checks. Runtime modules should emit hook events through this facade instead of executing hook commands directly.

`magent.lsp_client` owns synchronous JSON-RPC framing, process lifecycle, initialization, capability negotiation, document synchronization, cancellation, bounded notification collection, restart, and shutdown. `magent.lsp` selects installed Python, TypeScript/JavaScript, Rust, or Go servers and exposes capability-aware symbols, diagnostics, definitions, references, hover, and rename. It retains accurately labeled AST/text fallbacks. Review and diagnostics flows consume this module instead of duplicating syntax checks.

The agent should depend on stable facades:

- `magent.memory.MemoryManager`
- `magent.tools.ToolExecutor`
- `magent.workbench` public helpers
- `magent.context` context-map and promotion helpers

### Memory

`magent.memory` is the MagGraph-backed long-term memory layer. It stores durable knowledge: preferences, project facts, recurring patterns, session summaries, bookmarks, and other facts worth recalling across sessions.

Semantic search and memory quality tools live alongside this layer because they operate on MagGraph nodes.

### Workbench

Workbench state is local operational state: tasks, artifacts, project profiles, plans, reviews, patches, checkpoints, command history, release checks, dashboards, and docs helpers.

`magent.workbench_store` owns the JSON-backed storage primitive. `magent.workbench` remains the compatibility facade for workbench functions. New workbench domains should move toward focused modules while being re-exported from `magent.workbench`.

`magent.events` stores structured workbench events for trust and auditability. Config
proposal creation, application, and discard operations record events there, and other
state-changing UX flows should follow the same pattern.

`magent.workbench_maintenance` owns workbench storage statistics, pruning, and
JSON compaction for high-volume local stores. New history-like stores should be
included there when they can grow indefinitely.

`magent.workbench_domains.*` exposes domain-specific import modules for plans, patches, checkpoints, project helpers, code/test intelligence, and release/workspace helpers. Compatibility re-exports remain in `magent.workbench`; the temporary facade exception and extraction conditions are tracked in `architecture-exceptions.md`.

### Context

`magent.context` bridges memory and workbench state. It answers "what does MagAgent know right now?" and promotes selected workbench facts into durable MagGraph memory.

Promotion is intentionally explicit:

- workbench records are temporary operational state
- MagGraph nodes are durable semantic memory
- `magent memory promote` is the bridge between them

`magent.memory_inbox` adds a review layer before durable writes. It gathers promotion candidates from context, sessions, tasks, reviews, plans, and command failures, then records accept/reject/edit decisions in the local workbench.

### Recipes And Playbooks

`magent.recipes` owns reusable workflow recipes such as release prep, bug triage, docs audit, dependency upgrade, and test repair. Running a recipe materializes a pending execution plan through the plan domain instead of executing shell commands directly.

`magent.playbook` loads `.magent/playbook.toml` and exposes project-specific test sequences, release checklists, review rules, and context briefing defaults. Project command inference reads playbook commands so `magent project commands`, `magent context map`, and recipe generation agree on project routines.

### Tools

`magent.tools` is the public tool API. `magent.tools.executor.ToolExecutor` is the
stable permission, lifecycle, and dispatch facade, and the package initializer
re-exports it for compatibility. Capability implementations can live in focused
modules inherited by that facade.

Shared tool support code lives in:

- `magent.tools.types` for `ToolResult` and tool budgets
- `magent.tools.registry` for OpenAI-compatible tool schema helpers
- `magent.tools.archive` for archive extraction safety
- `magent.tools.artifacts` for Word, PowerPoint, SVG, Mermaid, raster-image, and
  generated-image creation
- `magent.tools.data` for JSON queries and permission-aware named SQLite facades
- `magent.tools.files` for path-safe reads, outlines, writes, edits, deletes,
  directory listing, diffs, built-in docs search, compression, and safe extraction
- `magent.tools.shell` for trust-pattern handling, shell and Python subprocesses,
  package installation, subprocess-backed code search, and Git delegation
- `magent.tools.system` for system metrics, notifications, clipboard access,
  platform file opening, and image inspection
- `magent.tools.web` for ranked web search, readable fetches, research packets,
  generic HTTP requests, and Playwright browser delegation

The capability split is complete. `ToolExecutor` retains shared path and permission
policy, process/task cancellation, tool selection, argument normalization, dispatch,
progress reporting, and output budgeting. New tools should be implemented in the
matching capability module and registered through `magent.tools.catalog`.

`magent.tool_packs` groups runtime tools into files, shell, web, data, db, and desktop capability packs. The CLI exposes `magent tools list`, `magent tools explain`, `magent tools enable`, and `magent tools disable`; the executor filters advertised tools through that setting.

### Local UI

`magent.ui` serves the local browser dashboard. `magent.ui_actions` owns actionable handlers for release checks, memory promotion, patch preview, and checkpoint diffs so browser endpoints share the same domain helpers as the CLI.

`magent.workbench_cockpit` aggregates an action-oriented cockpit state for the UI, including pending plans, memory inbox candidates, recipes, sandbox runs, failed commands, and release checks.

UI state endpoints should stay cheap: dashboard refreshes summarize cached/local
state and must not run tests, linters, release checks, or other long-running
commands. Expensive actions belong behind explicit button endpoints such as
`/api/release/check`.

### Sandboxes, Evals, Browser, GitHub, And Background Work

`magent.agent_profiles` owns Open Agent Profile parsing, validation, canonical digests,
legacy conversion, root-derived trust, deterministic discovery, capability narrowing,
stable-prompt rendering, and reviewable state deltas. `ResolvedProfile` represents what a
document requests; only `EffectiveProfile`, after intersection with harness policy, may enter
`AgentSession`. Profile state is untrusted context and delta application is permanently scoped
to `/state`.

`magent.sandbox` owns isolated plan and recipe execution in worktree, copy, and Docker container modes.

`magent.task_runtime` owns the versioned durable execution contract. It stores task
snapshots and append-only ordered events in per-user SQLite, validates lifecycle
transitions, and models parent/child work. `magent.execution_bridge` adapts live agent
sessions without coupling the provider/tool loop to SQLite. Interactive sessions,
asks, recipes, gateways, daemon jobs, goals, and subagents now use the contract. CLI
and desktop consumers read the same JSON-shaped snapshots and event records.

`magent.evals` owns local JSON eval suites and run reports.

`magent.browser` owns optional Playwright-backed browser snapshot and screenshot helpers.

`magent.github_workflows` owns GitHub PR and issue commands through the authenticated `gh` CLI.

`magent.daemon` owns the durable background queue for asks, recipes, plans, shell tasks, scheduled followups, and gateway work. It uses the workbench store so queued work remains inspectable and resumable.

`magent.plugins` owns installable extension pack metadata and enabled state. Plugin packs can carry agents, recipes, skills, tool bundles, and MCP config. Enabled plugin agent directories participate directly in agent discovery, and enabled plugin MCP configs contribute collision-safe runtime MCP servers. Compatibility importers convert OpenCode, Claude, Gemini, Codex skill, Pi portable resources, and MCP config shapes into MagAgent-native packs. Pi extension source remains quarantined and can run only through Pi's own executable after plugin enablement and an explicit `external_process` grant; foreign JavaScript never loads into the MagAgent process.

`magent.mcp.profile` is the SDK-independent MCP configuration boundary. It normalizes
transport and protocol-era preferences, rejects ambiguous or unsafe configurations,
and emits redacted diagnostics. `magent.mcp.client` owns a private JSON-lines bridge
process; `magent.mcp.bridge` keeps the Python SDK v2 connection in one root coroutine
and adapts stdio, Streamable HTTP, and explicitly enabled legacy SSE transports.
Profiles and credentials cross the process boundary through stdin rather than command
arguments. `magent.mcp.manager` owns concurrent connections, tool namespacing, and
dispatch without depending on SDK lifecycle details. `magent.mcp.catalog` owns typed
prompt/resource descriptors and TTL/scope/freshness state. Catalogs load lazily,
resource bodies are explicit and bounded, and tool mutations plus classic notifications
and modern subscription events share one invalidation path. The bridge also owns MCP
completion and consent-gated MRTR callbacks so SDK lifecycle and sensitive host input
never leak into the model-facing tool schema.

### Local Session Messaging

`magent.session_messaging` owns the local peer roster, owner-only runtime endpoints,
rotating capabilities, bounded envelopes, policy enforcement, durable inbox/held/
outbox queues, receipts, retry, expiry, deduplication, hop limits, and rate limits.
`magent.tools.messaging` is the narrow agent-facing adapter. `AgentSession` registers
and stops its endpoint and drains accepted messages into a clearly delimited untrusted
system context at a safe turn boundary. Peer text never enters conversation history as
a user message and carries no permission, MCP, configuration, or tool authority.

The transport is Unix-domain sockets on macOS/Linux with OS-peer checks where the
platform exposes them. Windows uses authenticated loopback as the owner-local
equivalent. Durable state remains below `~/.config/magent/messaging`; cross-machine
delivery is outside this contract.

## Compatibility Rule

Public imports should remain stable unless a major version explicitly changes them:

```python
from magent.tools import ToolExecutor
from magent.workbench import WorkbenchStore
from magent.workbench import task_add
from magent.workbench_domains.plans import save_plan
```

When internals move, add compatibility tests before refactoring. This protects downstream users and keeps releases patch-safe.

## Dependency Direction

Runtime and tool-domain modules may not import `magent.cli` or `magent.ui`. CLI/UI layers compose domain services; they do not own runtime behavior. `tests/unit/test_runtime_architecture.py` enforces this rule and the runtime module size budget.

## Refactor Order

The safest future order is:

1. Move CLI command groups into focused registration modules that use `magent.cli.command_context`.
2. Continue extracting `magent.workbench` domains behind the existing facade and domain modules.
3. Keep `magent.tools.executor` as the stable lifecycle/dispatch facade; add new
   behavior to focused capability modules.
4. Add architecture docs and ownership tests whenever module boundaries change.
