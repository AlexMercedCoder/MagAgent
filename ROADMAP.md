# Mag Ecosystem Roadmap

> Canonical direction for MagAgent, MagGraph, and Mag Command Center.
>
> Last audited: 2026-08-09
> Current releases: MagAgent 0.34.0, MagGraph 0.4.1, Mag Command Center 0.2.0

## Purpose

The Mag ecosystem already covers an unusually broad surface: a terminal coding and
productivity agent, durable graph memory, provider and model routing, subagents,
orchestrated goals, MCP and plugin compatibility, browser and document tools,
background work, and a cross-platform desktop application.

The next stage should not be driven by adding more isolated commands. It should make
the existing system more dependable, easier to understand, measurably better at real
tasks, and consistent across the CLI and desktop application.

The product thesis for the next several releases is:

> Mag should be the local-first agent ecosystem where execution is inspectable,
> memory is genuinely useful, and every capability is available through one stable
> machine interface shared by the CLI and desktop app.

## Audit Snapshot

### Strengths

- **MagAgent has a broad, coherent feature set.** It supports 20 provider options,
  model roles, persistent MagGraph memory, specialist agents, subagents, hooks,
  recipes, playbooks, permissions, checkpoints, MCP, plugin imports, LSP helpers,
  browser automation, research, document and visual artifacts, a daemon, and staged
  goal execution.
- **MagGraph is a useful differentiator.** Markdown-native storage, Git-friendly
  history, structured search, backlinks, incremental updates, recall bundles,
  memory schemas, and suppression/merge operations give MagAgent durable memory
  without hiding user knowledge in an opaque hosted service.
- **Mag Command Center is already a real cross-platform client.** It covers setup,
  project switching, chat, configuration, memory, SQLite, plugins, research, and
  workbench actions, with release artifacts for Linux, Intel and Apple Silicon macOS,
  and Windows.
- **Release engineering is mature for the project age.** All three projects have
  automated builds or tests, and the desktop app produces native installers across
  supported platforms.
- **Current functional baselines are healthy.** The audit ran 411 passing MagAgent
  tests, 122 passing MagGraph workspace tests plus 3 doc tests, and 10 passing
  Command Center tests. The Command Center production web build also completed.

### Risks and gaps

- **Reliability is not yet measured end to end.** MagAgent has a local eval scaffold,
  but there is no maintained corpus of representative coding, research, document,
  memory, permission, and provider tasks with version-over-version scores.
- **MagAgent still has concentrated modules.** `cli/main.py` is about 4,760 lines,
  `agent.py` about 1,950, and `workbench.py` about 1,760. These files still increase
  regression risk and slow focused testing. `tools/executor.py` is now a roughly
  390-line lifecycle and dispatch facade backed by focused capability modules.
- **The MagAgent coverage gate should keep ratcheting upward.** The checkout-isolation
  guard, fatal resource warnings, and connection cleanup are now in place, and the
  suite reaches 64.61% against the 63% floor. High-blast-radius agent, gateway,
  sandbox, and UI paths remain the next coverage targets.
- **Command Center test depth is low.** Ten utility/integration tests do not exercise
  its chat lifecycle, cancellation, project/session switching, setup flows, memory
  edits, SQLite pagination, plugin actions, accessibility, or native command bridge.
- **Command Center has its own concentration point.** `App.tsx` is about 900 lines and
  owns most application state and orchestration. The Tauri bridge is also a broad
  process wrapper rather than a narrow typed client for a versioned MagAgent API.
- **Desktop state is mostly browser-local.** Chat and project state stored in
  `localStorage` is convenient for an MVP but weak for migrations, larger histories,
  concurrent work, recovery, and parity with CLI sessions.
- **MagGraph's current contract is documented and benchmarked.** Version 0.3.0 now
  has a current support matrix, crash-consistency guarantees, downstream Python API
  contract tests, and measured 1K/10K/100K retrieval benchmarks. Hybrid retrieval,
  temporal validity, and transactional graph-edit batches remain roadmap work.
- **Provider breadth creates a conformance burden.** A provider being configurable
  does not prove streaming, tool calls, retries, caching telemetry, context limits,
  structured output, and cancellation behave consistently.
- **MCP core interoperability is dual-era, but experimental surfaces remain.** The
  SDK v2 bridge now negotiates classic MCP through `2025-11-25` and modern
  `2026-07-28`, over stdio and Streamable HTTP. Tools, prompts, resources, completion,
  cache invalidation, subscriptions, and consent-gated MRTR are implemented. Tasks,
  OAuth, sandboxed Apps rendering, remote Skills, and formal conformance remain.

## Product Boundaries

Each repository should have a clear responsibility:

| Project | Owns | Should not own |
| --- | --- | --- |
| MagGraph | Durable graph data, indexing, retrieval, provenance, memory lifecycle, graph performance | Agent prompts, provider routing, UI workflows |
| MagAgent | Agent execution, tools, permissions, providers, orchestration, workbench state, stable machine API | Desktop-only state and presentation |
| Mag Command Center | Native setup and updates, project/session UX, streamed activity, visual memory and data management | Reimplementations of MagAgent or MagGraph business rules |

New behavior should first land in the lowest appropriate domain, then be exposed by
MagAgent's machine API, and finally consumed by Command Center. The desktop app should
not reproduce CLI parsing or edit MagAgent-owned files directly when a domain command
or API exists.

## Phase 1: Confidence and Architecture Baseline

**Goal:** Make the current capability set safe to evolve. This phase is complete when
all three repositories have trustworthy local and CI quality gates and no critical
workflow depends on a monolithic module.

**Progress (2026-08-09):** The first MagAgent confidence unit is complete. Pytest now
imports the checkout explicitly, resource leaks fail the suite, cached user databases
have deterministic shutdown, semantic-memory connections close correctly, and 411
tests pass with 64.61% branch coverage against the 63% gate.

The first modularization unit is also complete: document, diagram, and image tools now
live in a strictly typed `magent.tools.artifacts` capability module. The public
`ToolExecutor` facade and all existing dispatch contracts remain unchanged, with
architecture tests pinning the new ownership boundary.

The second modularization unit moves shell trust rules, subprocess execution, Python
snippets, package installation, and code search into the strictly typed
`magent.tools.shell` capability module. Process cancellation remains centralized in
the facade, and compatibility tests pin all inherited public methods to their owner.

The third modularization unit moves ranked search, readable web fetches, deep-research
packets, generic HTTP requests, and browser delegation into the strictly typed
`magent.tools.web` capability module. Existing browser helper exports and all
`ToolExecutor` dispatch names remain compatible.

The fourth modularization unit moves path-safe file operations, outlines, diffs,
built-in docs search, compression, and safe archive extraction into the strictly typed
`magent.tools.files` capability module. The facade continues to own path policy and
checkpoints, while an end-to-end regression test rejects ZIP traversal attempts.

The fifth modularization unit completes the tool split. JSON and named SQLite facades
live in `magent.tools.data`; system metrics, notifications, clipboard operations,
platform file opening, and image inspection live in `magent.tools.system`; and Git
delegation lives with shell execution. `ToolExecutor` is now limited to shared policy,
lifecycle, selection, dispatch, progress, and output budgeting.

### MagAgent

- Make tests fail if `magent.__file__` is outside the checkout during development or
  CI. Standardize an editable-install or `src`-layout test command.
- Restore and ratchet coverage above the current 63% floor. Prioritize behavior with
  high blast radius: the agent loop, artifact recovery, memory writes, permissions,
  daemon jobs, setup, gateway routing, and provider error handling.
- Close SQLite connections deterministically and turn resource warnings into test
  failures on at least one CI job.
- Continue moving command groups out of `cli/main.py`; keep only app composition,
  the root callback, and interactive-session entry points there.
- Keep the completed `ToolExecutor` capability split stable. New tools belong in
  focused modules while the existing `ToolExecutor` remains the public dispatch facade.
- Extract the provider/tool loop, artifact lifecycle, session lifecycle, and context
  assembly from `agent.py` behind typed interfaces.
- Move workbench domain implementations out of `workbench.py`; keep re-exports for
  compatibility and add import-contract tests before each move.
- Add static type checking to CI for the extracted core modules, then broaden it as
  legacy surfaces are cleaned up.

### MagGraph

- Refresh or archive v0.1-oriented status and backlog documents. Maintain one current
  support matrix for Rust, Python, CLI, UI, and release artifacts.
- Add explicit API stability tests for the Python methods MagAgent consumes.
- Add realistic index benchmarks for 1K, 10K, and 100K nodes, including incremental
  update, search, backlinks, recall bundles, suppression, and merge operations.
- Record benchmark history in CI and fail on statistically meaningful regressions,
  not only the current small traversal threshold.
- Define crash-consistency tests for node writes, index updates, and interrupted
  merge operations.

### Mag Command Center

- Break `App.tsx` into project, session, setup, configuration, memory, SQLite, and
  workbench controllers/hooks with a small composition shell.
- Introduce a typed MagAgent client and normalize command errors, progress events,
  cancellation, and version negotiation in one place.
- Add component tests for chat, setup, memory, SQLite, and plugin workflows.
- Add native bridge tests for allowed commands, path handling, concurrent streams,
  process cleanup, and cancellation.
- Add Playwright end-to-end tests for first run, opening two projects, switching chat
  sessions, running a streamed task, editing memory, and browsing SQLite data.
- Add automated accessibility checks and keyboard-navigation coverage in both themes.

### Exit criteria

- All required checks pass from a fresh clone on supported Python versions and major
  desktop operating systems.
- MagAgent coverage is at least 70% overall, with 85% or better on newly extracted
  runtime modules.
- Command Center has at least 50 meaningful frontend tests and six critical-path E2E
  scenarios.
- No core orchestration module exceeds roughly 1,000 lines without a documented
  reason; facades may remain larger only when they contain little implementation.
- Baseline latency, memory, token, and success-rate reports are checked into release
  artifacts.

## Phase 2: One Execution Contract

**Goal:** Make interactive chat, one-shot asks, goals, recipes, gateways, daemon jobs,
and desktop sessions use the same durable execution model.

**Progress (2026-08-09):** The first shared-runtime unit is implemented on the future
release branch. `magent.task_runtime` provides transactional SQLite task snapshots,
legal state transitions, parent/child relationships, append-only ordered events,
event cursors, execution evidence, and pause/resume/cancel/retry operations. Daemon
jobs and orchestrated goals now produce this contract, while `magent execution` and
desktop API helpers expose it without terminal scraping. One-shot `magent ask` now
records live session events, usage, changed files, permission failures, and audit
evidence under the same task ID. Interactive chat, recipes, foreground and background
gateways, direct subagents, and orchestrated subagents now share the same lifecycle.
Daemon workers poll durable controls and stop child commands promptly on pause or
cancel. Provider requests remain cooperatively cancellable at request/tool boundaries;
true mid-request suspension depends on provider transport support.

### Shared task model

- Define a versioned task state machine: `queued`, `planning`, `running`, `waiting`,
  `blocked`, `validating`, `completed`, `failed`, and `cancelled`.
- Give every run a durable task ID, project ID, session ID, parent/child relationship,
  timestamps, selected model roles, permission policy, token/cost counters, files
  changed, checkpoints, and final audit.
- Store append-only structured events for model activity, tool intent, tool progress,
  permission decisions, artifacts, validation, retries, subagents, and completion.
- Expose a versioned JSON/JSONL API through MagAgent. Keep terminal rendering and
  desktop rendering as consumers of the same event stream.
- Support cancellation, pause/resume, retry-from-step, and reconnect without orphaning
  child processes or losing the final result.

### Reliable agent execution

- Make tool intent a first-class optional field with bounded length and redaction.
- Validate tool arguments locally before dispatch and give models a compact,
  machine-readable correction packet when an argument is missing or malformed.
- Turn artifact requirements into durable contracts with path, type, minimum content,
  verification method, and completion state. Prevent placeholder or filename-only
  output from satisfying a task.
- Make goal loops evidence-based: a goal may complete only when declared validation
  criteria pass or the user explicitly accepts an exception.
- Use the planning role for the cached master plan, the execution role for bounded
  steps, and inexpensive reviewer/verifier roles where configured.
- Add provider capability negotiation so unsupported temperature, reasoning,
  structured output, tool-choice, or caching options are omitted predictably.

### Command Center integration

- Replace ad hoc command-specific parsing with the versioned MagAgent event protocol.
- Render planning, tool activity, permissions, files, validation, and subagent work in
  the chat flow, with advanced diagnostics available in a collapsed inspector.
- Keep the UI responsive while tasks run; allow project/session switching and parallel
  background work without cancelling unrelated tasks.
- Add native notifications for blocked permissions and completed background tasks.

**Progress (2026-08-09):** Command Center now consumes the versioned task contract
through a typed client. It pre-creates and attaches one-shot asks, polls append-only
events by cursor, renders task state in chat, and exposes pause/resume/cancel/retry.
Tauri tracks streamed children so cancellation terminates the native process. Desktop
state moved from browser-only storage to a WAL-backed, versioned SQLite store with
migration fallbacks.

### Exit criteria

- The same test task produces equivalent lifecycle events in CLI interactive mode,
  `magent ask`, an orchestrated goal, the daemon, and Command Center.
- Every task can be cancelled within two seconds and resumed or retried without stale
  permission prompts or duplicate writes.
- Artifact-heavy evals reach at least a 95% verified-write success rate on the primary
  supported tool-calling models.
- No terminal or desktop workflow must scrape human-formatted output.

## Phase 3: Memory That Improves the Work

**Goal:** Turn memory from a storage feature into the ecosystem's clearest competitive
advantage while keeping recall explainable and token-efficient.

**Progress (2026-08-09):** The hybrid-memory foundation is implemented on coordinated
feature branches. MagGraph provides explainable lexical/semantic/graph/recency ranking,
project and temporal validity, suppression and supersession filtering, canonical IDs,
typed provenance, and rollback-capable reviewed batches. MagAgent routes optional local
sidecar scores into that ranker, builds bounded recall bundles with reasons/backlinks,
writes provenance when supported, prevents suppressed fallback leakage, guards inbox
promotion on exact duplicates or identity conflicts, exposes CLI/desktop batch APIs,
and ships deterministic precision/staleness/explanation/token-budget evals. The scalable
Command Center memory studio and learned ranking from accumulated feedback remain.

### MagGraph retrieval engine

- Add a native hybrid retrieval API combining lexical search, graph relationships,
  recency, node type, project scope, suppression state, and optional embeddings.
- Keep embeddings pluggable and optional. Support a local embedding model first, with
  provider-backed adapters only when users opt in.
- Add persisted retrieval indexes with schema/version metadata and incremental rebuilds.
- Add temporal validity (`valid_from`, `valid_until`, `supersedes`) and canonical node
  identity so old facts can remain auditable without being recalled as current truth.
- Make provenance first class: source session/task/tool, parent memory, extraction
  method, confidence, edits, merges, and supporting backlinks.
- Add transaction-like batches for multi-node edits and merge operations so Command
  Center can preview and safely apply graph changes.

### MagAgent memory policy

- Separate automatic candidates from durable accepted memory and make promotion rules
  configurable by node type and project.
- Add contradiction and duplicate detection before promotion.
- Learn retrieval quality from explicit accept, reject, suppress, edit, and “not useful”
  feedback without silently changing user-authored memory.
- Build context packets against a strict token budget and explain every recalled item:
  lexical match, semantic match, backlink, project fact, preference, or recent decision.
- Add memory evals for recall precision, stale-fact avoidance, cross-session continuity,
  provenance, and token cost.

### Command Center memory studio

- Replace the preview graph with an interactive, scalable graph/table split view.
- Add side-by-side diff and batch review for inbox candidates, merges, rewrites,
  contradictions, stale facts, and orphaned nodes.
- Let users chat about a selected subgraph while showing exactly which nodes are in
  context and how many tokens they consume.
- Add undoable memory operations and a history view backed by MagGraph provenance/Git.

### Exit criteria

- Retrieval benchmarks show better precision than lexical-only search at the same or
  lower context-token budget.
- Every recalled memory has a human-readable reason and navigable provenance.
- Memory writes and batches survive interruption without partial graph corruption.
- A user can inspect, modify, undo, and explain all durable memory from either CLI or
  Command Center.

## Phase 4: Daily-Driver Desktop Product

**Goal:** Move Mag Command Center from a capable cockpit to the easiest way for most
people to use MagAgent across several projects.

**Progress (2026-08-09):** The locally implementable daily-driver runtime is complete
on the desktop feature branch. Chat uses durable task tabs and remains interactive
during concurrent project work; native cancellation, restart recovery, notifications,
rich path-safe artifact previews, native SQLite state, hybrid-memory evidence, reviewed
memory batches, selective checkpoint compare/restore, and policy-governed local session
messaging are available. Redacted diagnostics include local-only performance budgets,
and component/contract/axe tests cover critical workflows. Signed updater delivery,
manual three-OS WCAG review, and hardware-scale 4-task/100K-node acceptance runs remain
release gates because they require signing credentials, packaged OS builds, and the
maintainer benchmark environment.

### Core experience

- Make chat the default workspace, with project and session navigation always
  available but visually quiet.
- Persist projects, sessions, task events, drafts, view state, and saved queries in a
  versioned local SQLite store instead of relying on `localStorage`.
- Support multiple concurrent tasks across projects with clear running, waiting,
  failed, and completed indicators.
- Add rich artifact previews for Markdown, code diffs, HTML, images, SVG, diagrams,
  documents, presentations, and PDFs.
- Add checkpoint comparison, selective rollback, and “open changed files” actions.
- Provide searchable command history and task diagnostics without exposing raw JSON
  unless the user opens the inspector.

### Installation and lifecycle

- Ship a first-run flow that can install MagAgent in an isolated managed environment,
  detect Python compatibility, import existing configuration, and test a provider.
- Add signed application updates and a compatibility check between Command Center,
  MagAgent, and MagGraph versions.
- Make upgrades transactional with rollback when provider/config migrations fail.
- Add crash recovery for active streams and unfinished tasks.
- Keep credentials in OS-native secure storage or environment references; never copy
  secret values into project files, logs, task events, or desktop local storage.

### Product polish

- Complete keyboard-first navigation, screen-reader labels, reduced-motion support,
  focus management, and contrast checks for light and dark themes.
- Add concise in-app onboarding around projects, permission modes, model roles,
  memory review, and background tasks.
- Add an opt-in diagnostics bundle that redacts secrets and packages versions, recent
  errors, task events, provider capabilities, and performance timings for bug reports.
- Track local performance budgets for startup, project switching, first activity,
  memory search, large tables, and long chat histories.

### Exit criteria

- Fresh installation to first successful task takes less than five minutes on macOS,
  Windows, and Linux without manual config-file editing.
- The app remains interactive during long model and tool calls and can manage at least
  four simultaneous project tasks.
- Critical workflows meet WCAG 2.2 AA expectations and pass automated plus manual
  keyboard checks.
- A 10,000-event session and a 100,000-node memory graph remain navigable within the
  documented performance budgets.

## Phase 5: Ecosystem and 1.0 Readiness

**Goal:** Establish a trusted extension ecosystem and stable public contracts, then
release 1.0 only when quality is demonstrated by data.

### Extension ecosystem

- Publish a versioned plugin SDK and manifest schema for agents, skills, recipes,
  hooks, tools, MCP servers, and UI-safe metadata.
- Add a registry index with compatibility ranges, permissions, checksums, signatures,
  source URLs, maintainers, trust state, and automated security scans.
- Run plugins with least-privilege capability grants and clear per-project/user scope.
- Maintain import compatibility for Codex skills, Claude plugins/instructions,
  OpenCode agents/commands, Gemini extensions where practical, and standard MCP
  server configurations.
- Add a plugin conformance kit and sample packs that exercise every supported surface.

**Progress (2026-08-09):** Plugin SDK v1 now defines a machine-readable manifest
schema, deterministic content digests, strict/compatibility conformance reports,
permission inference, project/user grant records, registry index generation, tamper
checks before enablement, and a reference agent/skill pack. Registry hosting,
cryptographic signing roots, security-scan infrastructure, and least-privilege runtime
enforcement for executable third-party tool modules remain delivery work.

**Progress (2026-08-09, contracts):** `magent system contracts` publishes task, event,
plugin, memory, provider-report, and dual-era MCP compatibility levels plus Python and
deprecation support windows. `magent provider support-report` generates a secret-free
release artifact and keeps offline catalog, live completion, and live tool-use status
separate. Checkpoint JSON contracts and a reference plugin pack/conformance suite are
consumed by Command Center. Hosted registry operations, trusted signing roots,
automated third-party security scanning, and real-provider qualification remain
operational release gates rather than local code TODOs.

### Dual-era MCP and portable skills

MCP `2026-07-28` is a new protocol era, not a transparent revision of classic MCP.
The modern protocol removes `initialize`, protocol sessions, and `Mcp-Session-Id`;
puts protocol version, identity, and capabilities on each request; and adds formal
extension negotiation. The specification calls `2025-11-25` and earlier **legacy**
and implementations supporting both eras **dual-era**. MagAgent should preserve the
large classic server ecosystem while making modern MCP the preferred path.

**Progress (2026-08-08):** The first compatibility unit is complete. Typed profiles,
redacted diagnostics, strict `modern`/`legacy` modes, automatic negotiation, stdio,
Streamable HTTP, and explicitly enabled legacy SSE now route through an SDK v2 bridge.
The bridge keeps SDK lifecycle ownership in one root coroutine and receives profiles
and credentials over stdin. Wire-independent interoperability tests prove modern,
legacy, and automatic stdio discovery/tool calls on Python 3.11 and 3.14; the optional
integration suite repeats those checks whenever the MCP extra is installed.

The SDK v2 high-level server's externally spawned stdio fixture did not answer in the
migration environment even though its in-process transport did. Keep official SDK
server and conformance-suite interoperability as an acceptance gate; MagAgent's wire
fixture intentionally shares no MCP implementation code with the client.

**Progress (2026-08-09):** The second compatibility unit adds lazy, deterministic
prompt, resource, and resource-template catalogs; explicit prompt rendering and
bounded resource reads; SDK cache-mode integration; TTL/scope/freshness diagnostics;
and conservative invalidation after tool calls. Modern, legacy, and automatic wire
tests cover every new primitive. Normalized list-changed events now share one
invalidation seam; live legacy notifications and modern `subscriptions/listen`
consumption remain the next increment.

**Progress (2026-08-09, third compatibility unit):** Core dual-era client work is now
complete for the surfaces implemented by Python SDK v2. MagAgent consumes classic
notifications and modern `subscriptions/listen`, reports honored filters and stream
failures, routes both through deterministic cache invalidation, exposes prompt and
resource-template completion, preserves tool output schemas/annotations/extension
metadata, and handles legacy callbacks plus modern MRTR elicitation through an
explicit host-consent boundary. Sampling is never silently delegated and project-root
disclosure requires separate confirmation. Modern/legacy/automatic real-process tests
cover negotiation, tools, prompts, resources, completion, caching, and reconnect-safe
cleanup. Tasks and remote Skills remain experimental upstream; MagAgent must not
advertise them until a compatible SDK adapter and conformance fixture exist.

**Current MagAgent baseline**

- Keep the existing local and project `SKILL.md` registry, relevance matching,
  context budgets, lockfile, and Codex-style skill importer. MagAgent already supports
  file-based skills; the missing surface is discovery and consumption of skills
  delivered by an MCP server.
- Treat the current MCP implementation as dual-era core catalog support: it negotiates
  modern or classic peers through SDK v2; discovers and calls tools; and explicitly
  browses prompts/resources, completes arguments, consumes notifications, and handles
  consent-gated MRTR input. It preserves MCP Apps metadata with a safe textual fallback
  but does not render Apps or activate experimental Tasks/Skills extensions.
- Keep the optional SDK on the compatible v2 major line and run the wire-independent
  migration fixture whenever the optional extra is installed.

**Compatibility architecture**

- Introduce a typed MCP connection abstraction separating transport, protocol era,
  authentication, discovered capabilities, catalog caching, and MagAgent adaptation.
  Keep `MCPManager` as orchestration rather than embedding SDK-version details in it.
- Support `stdio` and Streamable HTTP for both eras. Retain deprecated HTTP+SSE only
  as an explicitly enabled compatibility adapter with a warning and removal date; do
  not select it for new configurations.
- Add `protocol_mode = "auto" | "modern" | "legacy"` per server, defaulting to
  `auto`. Record the selected era, exact protocol revision, transport, server identity,
  extensions, and fallback reason in diagnostics without logging credentials.
- Follow the official dual-era algorithm. On stdio, probe `server/discover` and fall
  back to `initialize` only for a non-modern error or timeout. On HTTP, try a modern
  request and inspect an unrecognized `4xx` response before falling back. A recognized
  `UnsupportedProtocolVersionError` identifies a modern server and should trigger a
  retry with the highest mutually supported revision, not legacy fallback.
- Cache era detection for a stdio process or HTTP origin and invalidate it after a
  protocol failure or configuration change. Test modern/modern, modern/legacy,
  legacy/modern, legacy/legacy, and both dual-era combinations.

**Modern `2026-07-28` client support**

- Upgrade through the Python SDK v2 `Client` API so each request carries
  `io.modelcontextprotocol/protocolVersion`, client capabilities, and client identity.
  Add required HTTP `MCP-Protocol-Version`, `Mcp-Method`, and `Mcp-Name` headers.
- Consume `server/discover`, including supported versions, server capabilities,
  extension settings, instructions, identity, `ttlMs`, and `cacheScope`. Treat server
  identity and instructions as untrusted display/model context, never authorization
  policy.
- Cache deterministically ordered `tools/list`, `prompts/list`, `resources/list`, and
  safe `resources/read` responses according to server cache hints. Invalidate through
  `subscriptions/listen` when supported, and expose cache/freshness data in diagnostics.
- Preserve structured tool content instead of flattening everything to text: text,
  images, audio, embedded resources, resource links, structured content, annotations,
  and tool execution errors must map into MagAgent's typed result and permission model.
- Implement Multi Round-Trip Requests for `input_required` results using MagAgent's
  existing approval/form UX. Never answer elicitation from hidden context without
  explicit user consent, and redact sensitive answers from logs and memory promotion.
- Add opt-in extension handlers, beginning with `io.modelcontextprotocol/tasks` for
  durable long-running calls. Map task handles, polling, updates, cancellation, and
  reconnect recovery into MagAgent's durable queue. Surface MCP Apps only through a
  sandboxed, permission-aware Command Center renderer; the CLI should provide a safe
  textual fallback.
- Implement modern OAuth requirements for remote servers: protected-resource and
  authorization-server discovery, issuer validation, Resource Indicators, incremental
  consent, Client ID Metadata Documents, secure token storage, and origin validation.
  Keep Dynamic Client Registration only as a visibly deprecated compatibility path.

**Skills over MCP**

- Track the official Skills over MCP extension separately from core protocol support.
  As of 2026-08-08, the working group's resources-based SEP-2640 and reference
  implementation are still in review, so ship interoperability behind an experimental
  feature flag until the extension identifier and schemas are final.
- Adapt remote skill descriptors into the existing `Skill` model with explicit
  provenance: server, URI, version, content hash, declared tools, trust state, fetched
  time, expiry, and protocol/extension revision. Preserve local `SKILL.md` as the
  canonical offline format rather than replacing it with an MCP-only representation.
- Use progressive disclosure: fetch compact skill metadata first, match it against the
  current request, then read full instructions only for selected skills within the
  existing skill token budget. Cache content using MCP hints and permit users to pin a
  reviewed snapshot in `skills.lock` for reproducible/offline sessions.
- Require explicit trust before activating a remote skill that requests tools,
  scripts, external resources, or broader permissions. A skill is instruction content,
  not permission to execute; all referenced MCP and built-in tools continue through
  MagAgent's normal capability and approval policies.
- Add `magent mcp skills list/show/trust/pin/refresh` plus readable `/skills` provenance
  in interactive sessions. Detect name/version collisions across local, project,
  plugin, and remote sources, with project policy deciding precedence rather than
  silently shadowing a skill.
- Test round trips with the MCP experimental reference implementation and Agent Skills
  compatible `SKILL.md` fixtures. Cover lazy loading, stale/offline cache, hash changes,
  malicious instructions, oversized content, missing required tools, server removal,
  and extension fallback when the peer does not advertise Skills over MCP.

**Conformance and delivery gates**

- Run the official MCP conformance suite in CI against pinned legacy and modern SDK
  versions, plus fixture servers for stdio, Streamable HTTP, authentication, MRTR,
  Tasks, catalog caching, and Skills over MCP. Network-dependent interoperability tests
  should be scheduled or opt-in so ordinary pull requests remain fast and deterministic.
- Publish a generated support matrix listing protocol revisions, transports, core
  primitives, extensions, authentication modes, SDK versions, deprecations, and tested
  server implementations. `magent mcp test` should identify negotiation and extension
  failures with actionable remediation.
- Do not declare modern MCP complete until legacy stdio configurations pass unchanged,
  modern stateless tool calls pass conformance, fallback cannot downgrade a recognized
  modern server, credentials stay redacted, and remote skills cannot bypass permission
  or context-budget controls.

Research basis: the official [2026-07-28 specification](https://modelcontextprotocol.io/specification/2026-07-28),
[version compatibility rules](https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning),
[release changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog),
[Python SDK v2 notes](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/whats-new.md),
and [Skills over MCP working-group charter](https://modelcontextprotocol.io/community/working-groups/skills-over-mcp).

### Stable platform contracts

- Version the MagAgent machine API, event protocol, plugin manifest, MagGraph Python
  API, graph schema, configuration schema, and migration format.
- Publish support windows and deprecation rules before 1.0.
- Add generated API documentation and compatibility matrices to each release.
- Introduce coordinated ecosystem releases only when a cross-project contract changes;
  otherwise release projects independently to control CI cost and user churn.

### Session-to-session messaging

**Implemented in MagAgent 0.33.0.** Local peer discovery,
authenticated delivery, receiving policies, bounded durable queues, receipts, retry,
agent tools, CLI workflows, safe context injection, and security tests are complete.
Command Center visualization and any encrypted cross-machine relay remain future work.

The design borrows the useful safety properties of Claude Code v2.1.224 without
coupling MagAgent to Claude's supervisor implementation.

- Add `list_sessions` and `send_session_message` agent tools plus readable
  `magent session peers` and `magent session send` commands. Address durable session
  IDs first; names are display aliases and must fail closed when ambiguous or reused.
- Register each eligible live session in a per-user local roster and bind a per-session
  Unix-domain socket on macOS/Linux. Use an owner-only named-pipe equivalent on Windows.
  Authenticate the OS user and rotate an unguessable session capability at restart.
- Send a bounded plain-text envelope containing sender ID/name, reply address,
  project/worktree, related task ID, timestamp, nonce, and provenance. Never transfer
  conversation history, files, hidden context, credentials, or permission state.
- Deliver messages only at safe turn boundaries. An idle receiver is notified and
  queues the message for its next turn; an active receiver receives it after the
  current tool boundary. Persist an undelivered local outbox so restarts do not
  silently lose coordination.
- Give each receiving session `accept`, `hold`, and `refuse` policy with user, project,
  and managed-setting precedence. Held messages require explicit user review and
  expire; headless sessions may accept only through an explicit configuration policy.
- Treat peer text as untrusted agent input, never user authority. It cannot approve a
  permission, answer an MCP elicitation, change configuration/instructions, widen tool
  access, or execute slash commands. The receiving session's own sandbox and approval
  rules govern every resulting action.
- Return delivery receipts (`delivered`, `held`, `refused`, `expired`, `unreachable`)
  when the sender is reachable. Add loop protection with per-peer rate limits,
  duplicate-message suppression, hop counts, bounded inbox/outbox sizes, and audit
  events that store redacted summaries rather than hidden reasoning.
- Surface peers, unread/held messages, delivery state, and reply controls in Command
  Center's project/session navigation. Cross-project sends should visibly identify both
  roots and warn when worktrees may conflict.
- Keep cross-machine delivery out of the first release. A later opt-in relay must be
  end-to-end encrypted, device-bound, explicit about which peers are reachable, and
  default to reply-only until the user grants broader initiation rights.
- Test same-user isolation, spoofed roster entries, stale sockets, name collisions,
  supervisor restart, active-turn ordering, headless policy, permission laundering,
  loops, duplicate delivery, queue overflow, worktree conflicts, and Windows parity.

Research basis: Anthropic's official
[cross-session messaging guide](https://code.claude.com/docs/en/cross-session-messaging),
[parallel agents overview](https://code.claude.com/docs/en/agents), and
[Claude Code changelog](https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md).

### Optional collaboration

- Keep the default experience local-first. Add encrypted, opt-in graph sync and team
  workspaces only after local reliability and permission boundaries are proven.
- Separate personal preferences from project/team knowledge with explicit sharing
  policies and provenance.
- Provide redacted task exports and reproducible eval bundles for teams that cannot
  share source code.

This section is intentionally deferred. Cross-machine sync is not required for the
local-first roadmap to be code-complete and must not begin until signing, recovery,
permission, and stable-contract acceptance gates above are met.

### 1.0 gates

- A maintained eval suite covers coding, research, artifacts, memory, permissions,
  providers, goals, plugins, and desktop workflows, with published release trends.
- No open critical security or data-loss defects; recovery and migration tests pass on
  all supported platforms.
- Provider conformance tests pass for every provider advertised as fully supported.
- Public contracts have migration tests and at least one release of deprecation notice
  before incompatible changes.
- Documentation includes a five-minute quickstart, task-oriented guides, architecture,
  extension authoring, troubleshooting, security, privacy, and a tested upgrade path.
- MagAgent and MagGraph are ready for stable 1.0 APIs; Command Center can advance on
  its own product version while declaring compatible runtime ranges.

## Cross-Project Delivery Order

For work spanning repositories, use this sequence:

1. **Define the contract and acceptance test.** Decide the event, schema, graph API,
   or task behavior before implementation.
2. **Implement MagGraph primitives** when durable graph behavior is required.
3. **Expose behavior through MagAgent** with a typed Python API and versioned JSON.
4. **Integrate Command Center** through the machine API rather than shell-output
   interpretation or direct file mutation.
5. **Run ecosystem smoke tests** against released artifacts in clean environments.
6. **Document and release from the bottom up:** MagGraph, MagAgent, then Command Center
   only when downstream dependency changes require it.

## Metrics to Publish Per Release

| Category | Measures |
| --- | --- |
| Agent reliability | Task success, verified artifact success, tool argument failures, retries, duplicate writes |
| Model efficiency | Input/output/cache tokens, cost, time to first activity, time per model round |
| Safety | Permission prompts, blocked actions, approval reuse, rollback success, secret-redaction tests |
| Memory | Recall precision, stale recall rate, context tokens, promotion acceptance, duplicate rate |
| Performance | CLI startup, project scan, memory search, event throughput, desktop startup and interaction latency |
| Quality | Test count, branch coverage, E2E pass rate, provider conformance, open regressions |

Metrics should be local and anonymous by default. Release reports can be generated from
maintainer-run evals without adding product telemetry.

## What Not to Prioritize Yet

- A hosted account system or cloud control plane before local task recovery and stable
  APIs are complete.
- More providers without an automated provider conformance contract.
- More top-level commands when the behavior belongs in an existing workflow or can be
  discovered through chat/configuration UX.
- Autonomous memory writes without review, provenance, and undo.
- A public plugin marketplace before signatures, permissions, compatibility, and
  trust metadata are enforced.
- A VS Code extension before the machine API and task event protocol are stable; once
  stable, an editor client becomes much cheaper to build correctly.

## Recommended Immediate Release Sequence

1. **MagAgent 0.33.0 (released):** test isolation, coverage repair, SQLite cleanup,
   tool modularization, dual-era MCP, and authenticated local session coordination.
2. **MagGraph 0.4.1 (release prepared):** API contract tests, scale benchmarks,
   crash-safe atomic updates, hybrid retrieval, temporal/provenance fields, and reviewed batches.
3. **MagAgent 0.34.0 (release prepared):** versioned task/event protocol, durable lifecycle, cancellation,
   artifact contracts, and unified execution surfaces.
4. **Mag Command Center 0.2.0 (release prepared):** typed client, controller extraction,
   persistent native state, event-native concurrent chat, cancellation, recovery,
   checkpoint/session workbench, artifact previews, diagnostics, and accessibility checks.
5. **Ecosystem beta milestone (local evidence complete; release operations next):**
   `mag.ecosystem-readiness.v1` now aggregates component contracts, graph benchmark
   evidence, packaged docs, and explicit external gates. Run real-provider and packaged
   three-OS acceptance matrices, configure signing, publish the first cross-project eval
   report, and freeze candidate 1.0 contracts for feedback.

This order deliberately builds confidence first, then shared execution, then memory
quality, then desktop polish. It turns the breadth already present in Mag into a
dependable product advantage instead of continuing to increase its maintenance load.
