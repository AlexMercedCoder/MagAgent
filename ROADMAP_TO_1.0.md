# MagAgent Roadmap To 1.0

> Version sequence: `0.50.0`, `0.60.0`, `0.70.0`, `0.80.0`, `0.90.0`, `1.0.0`.
>
> The project is currently preparing `0.60.0`. The `0.50.0` notation is intentional:
> semantic version `0.5.0` would be older than `0.35.1`.

## Purpose

MagAgent already has enough feature breadth for a general-purpose local coding and
productivity agent. The path to 1.0 should therefore emphasize proof, stability,
cohesion, and supportability rather than accumulating more unrelated commands.

The 1.0 promise is:

> A user can install MagAgent on a supported platform, configure a qualified provider,
> complete real coding and productivity work through one durable execution model, inspect
> and control every meaningful action, recover interrupted work, and trust documented
> compatibility and safety boundaries.

Every milestone below has required exit criteria. A release may move scope forward, but
it should not claim the milestone until its gates pass and the evidence is recorded.

## Principles

- Prefer reliability and simplification over new top-level features.
- Treat real task success as the primary quality metric, not command count.
- Keep local-first behavior, inspectable state, explicit permissions, and user-owned memory.
- Qualify provider/model combinations instead of implying identical support for every model.
- Keep terminal, JSON/JSONL, daemon, gateway, and desktop behavior on the same contracts.
- Make optional integrations genuinely optional so the core install stays practical.
- Ratchet tests, typing, security checks, and performance budgets upward; do not lower gates
  to make a release pass.
- Do not stabilize an interface merely because it already exists. Stabilize it after it is
  exercised by real consumers and has a migration policy.

## Current Baseline

As of `0.35.1`:

- 715 unit tests and 3 MCP integration tests pass.
- Branch coverage is approximately 66%, with a 64% CI floor.
- Python 3.11 through 3.14 are tested on Linux CI.
- The task and task-event contracts are stable; several desktop, provider, config, memory,
  and registry contracts remain beta.
- MagAgent exposes 20 provider configurations and 43 built-in tools.
- The largest remaining concentration points are `cli/main.py`, `workbench.py`, and
  `agent.py`.
- Provider behavior, real-agent task success, optional integrations, and packaged
  cross-platform behavior are not yet continuously qualified.
- Code intelligence detects language servers but currently uses AST and text fallbacks
  rather than an LSP protocol client.

## 0.50.0: Measured Reliability

**Release status:** Implemented for 0.50.0. The real-agent harness, 32-task offline baseline,
5-task live Nous qualification, MCP CI, release evidence, drift checks, and public policies are
complete. The 72% branch-coverage target is not claimed: measured branch-aware coverage remains
64.9% against the 64% regression floor and carries forward as the first 0.60 hardening item.

**Theme:** Prove that MagAgent completes representative work reliably.

### Real Agent Evals

- Replace command-only eval execution with a harness that creates an isolated fixture repo,
  runs MagAgent against the task prompt, captures its task/event stream, and then runs
  independent validators.
- Maintain versioned eval suites for:
  - focused code repair and test repair
  - multi-file feature implementation
  - research with source-backed Markdown output
  - HTML, Word, PowerPoint, diagram, image, and spreadsheet artifacts
  - permission approval, denial, reuse, and rollback
  - memory recall, stale-memory avoidance, promotion, merge, and suppression
  - orchestrated goals, verifier/reviewer loops, cancellation, and resume
  - malformed tool arguments and provider-specific tool-call formats
- Record success rate, retries, tool calls, elapsed time, time to first activity, input/output
  tokens, cache tokens, estimated cost, changed files, and validation results.
- Add deterministic offline evals to pull requests and credentialed provider evals to a
  scheduled or manually dispatched workflow.
- Publish a machine-readable eval report with every milestone release.

### Test And Failure Coverage

- Raise overall branch coverage to at least 72% and the CI floor to 70%.
- Reach at least 80% branch coverage on permissions, artifact contracts, task runtime,
  workbench storage, provider request construction, and execution bridges.
- Add focused tests for currently weak high-blast-radius paths: agent recovery, memory writes,
  shell execution, sandbox cleanup, daemon claims, setup, gateway lifecycle, MCP bridge, and
  local UI mutations.
- Run the integration suite in CI with the MCP extra installed.
- Add fault-injection tests for provider timeout, malformed streaming chunks, process crash,
  partial file writes, SQLite lock contention, interrupted memory updates, and disk-full
  behavior where practical.

### Release And Documentation Hygiene

- Correct stale support statements and extend docs drift checks beyond command generation to
  dependency floors, contract versions, provider defaults, and supported Python versions.
- Add a release evidence command that assembles local checks, CI links, eval reports,
  provider qualification, artifact hashes, and outstanding exceptions.
- Define severity levels and a release-blocking defect policy.
- Keep a public known-limitations document with workarounds and affected versions.

### 0.50.0 Exit Criteria

- At least 30 representative real-agent tasks run through the new harness.
- Primary qualified provider/model combinations achieve at least 90% task success overall and
  95% verified artifact-write success.
- No known critical data-loss, command-policy bypass, secret exposure, or unrecoverable task
  defect remains open.
- Unit, integration, docs, package, and offline eval gates pass from a fresh clone.
- The release includes a reproducible baseline report for future comparison.

## 0.60.0: Coherent Runtime And Real Code Intelligence

**Release status:** Implemented for 0.60.0. Agent runtime layers, enforced typing,
stable contract fixtures, real Python/TypeScript LSP integration, bounded fallbacks,
optional install shapes, core wheel smoke coverage, and architecture dependency rules
are complete. Remaining oversized compatibility facades have explicit exceptions and
closure criteria in `src/magent/docs/architecture-exceptions.md`.

**Theme:** Reduce regression risk and make coding intelligence substantive.

### Runtime Modularization

- Extract the provider round, tool loop, context assembly, artifact lifecycle, memory lifecycle,
  and session lifecycle from `agent.py` behind typed interfaces.
- Finish moving command implementations out of `cli/main.py`; leave app composition, the root
  callback, and interactive entry points in the facade.
- Move workbench implementations into focused domain modules while preserving compatibility
  re-exports and import-contract tests.
- Keep `ToolExecutor` as the stable dispatch/policy facade and keep capability logic in the
  existing focused tool modules.
- Define dependency-direction tests so CLI and UI layers cannot become domain owners.

### Type Safety And Contracts

- Remove the agent loop, task runtime, tool executor, memory facade, gateway router, daemon,
  graph executor, and MCP manager from the mypy ignore list.
- Enable `check_untyped_defs` and stricter checks incrementally for extracted runtime modules.
- Replace unstructured dictionaries at key boundaries with typed task, event, tool-result,
  permission, provider-capability, and artifact records.
- Add compatibility fixtures for every stable machine contract.

### Real LSP Client

- Implement JSON-RPC LSP process lifecycle, initialization, capability negotiation, document
  open/change/close, cancellation, timeout, restart, and clean shutdown.
- Support definitions, references, symbols, diagnostics, hover, and rename where the connected
  server advertises them.
- Start with Python, TypeScript/JavaScript, Rust, and Go using installed servers.
- Retain bounded AST/text fallbacks and label their source accurately.
- Feed actual diagnostics and symbol locations into context assembly, review, repair, and evals.

### Installation Shape

- Measure clean install size and startup cost.
- Move document, media, desktop, gateway, browser, and MCP dependencies into coherent optional
  extras where they are not required for the core agent.
- Add friendly readiness/install flows when an optional capability is requested but absent.
- Verify core and full-feature installation paths independently.

### 0.60.0 Exit Criteria

- No implementation-heavy core orchestration module exceeds roughly 1,000 lines without a
  documented exception.
- Extracted core runtime modules have at least 85% branch coverage and pass enforced mypy.
- Real LSP integration tests pass against at least Python and TypeScript servers.
- Core installation size and cold CLI startup improve against the 0.50.0 baseline.
- Existing CLI, machine API, plugin, and desktop contract fixtures remain compatible.

## 0.70.0: Qualified Providers And Interoperability

**Theme:** Make support claims precise and integration behavior dependable.

### Provider Qualification

- Add Trusted Router and Prime Intellect as first-class providers across the shared provider
  catalog, configuration wizard, CLI setup flows, credential storage, model discovery, model
  roles, readiness checks, documentation, and Command Center machine contracts.
- Implement and test each provider's endpoint routing, authentication environment variables,
  model-name normalization, request parameters, streaming, native tool calls, usage reporting,
  errors, timeouts, and rate-limit behavior before assigning a support tier.
- Include Trusted Router and Prime Intellect in scheduled live completion and tool-use smoke
  reports, using inexpensive qualified models for routine checks where available.
- Introduce explicit support tiers:
  - **qualified:** completion, streaming, tools, cancellation, retries, usage, and caching tested
  - **compatible:** catalog and adapter validation pass, but release qualification is incomplete
  - **experimental:** known limitations or upstream instability
- Maintain a small primary matrix covering OpenAI, Anthropic, Gemini, Nous Portal, Trusted
  Router, Prime Intellect, OpenRouter, OpenCode Go/Zen, one local Ollama model, and one custom
  OpenAI-compatible server.
- Test plain chat, native tool use, malformed argument correction, streaming, cancellation,
  context limits, rate limits, model-role routing, caching telemetry, and artifact creation.
- Store sanitized qualification reports without credentials or prompt content.
- Detect stale model defaults and provider API changes before release.

### Unified Execution Reliability

- Verify equivalent lifecycle events for interactive chat, `ask`, goals, graphs, recipes,
  subagents, daemon work, gateways, and Command Center.
- Guarantee bounded cancellation and child-process cleanup; target two seconds for local work.
- Add crash/restart recovery tests for running tasks, daemon claims, checkpoints, permission
  waits, and partially completed graph nodes.
- Make retries idempotent where possible and explicitly report operations that cannot be safely
  replayed.
- Add stress tests for concurrent tasks, subagents, database readers/writers, event consumers,
  and session messages.

### MCP, Plugins, Gateways, And Browser

- Run MCP conformance fixtures for classic stdio and modern Streamable HTTP transports.
- Complete or explicitly defer OAuth, Tasks, remote Skills, and Apps rendering based on stable
  upstream specifications; do not blur experimental support into core claims.
- Add subprocess isolation, permission declarations, signature metadata, and compatibility
  checks for executable plugin capabilities.
- Add integration tests for Slack, Discord, and Telegram routing, authorization, mention rules,
  serialization, approval expiry, and shutdown using platform fakes.
- Add Playwright integration tests for navigation, snapshots, screenshots, downloads, timeout,
  cancellation, and browser cleanup.

### Cross-Platform CI

- Add Windows and macOS jobs for targeted filesystem, shell policy, subprocess, keyring,
  notification, session messaging, and installation tests.
- Run full Linux tests and a high-value cross-platform subset on pull requests.
- Run packaged wheel smoke tests instead of testing only editable installations.

### 0.70.0 Exit Criteria

- Every advertised provider has a published support tier and current evidence date.
- The primary provider matrix has no unresolved critical tool-use or streaming failure.
- MCP core conformance passes on supported classic and modern transports.
- Gateway, browser, and plugin integration suites run in CI or scheduled qualification jobs.
- Packaged smoke tests pass on Linux, macOS, and Windows.

## 0.80.0: Memory And Daily-Driver UX

**Theme:** Make MagAgent's differentiators consistently useful in ordinary work.

### Memory Quality

- Maintain retrieval evals for precision, stale-fact avoidance, contradiction handling,
  cross-session continuity, provenance, backlinks, project scope, and token cost.
- Tune hybrid lexical, semantic, graph, and recency ranking against those evals.
- Complete temporal validity, supersession, canonical identity, reviewed transaction batches,
  and rollback across MagGraph and MagAgent.
- Make automatic candidates, accepted durable memory, and user-authored memory visibly distinct.
- Add explainable “why recalled?” output everywhere memory enters context.
- Let feedback improve ranking only through inspectable, reversible local state.

### Terminal UX

- Provide immediate activity feedback for every model call and long-running tool.
- Make multiline composition, cancellation, resume, retries, permission decisions, and artifact
  previews work consistently across supported terminals.
- Consolidate overlapping planning, goal, graph, recipe, job, and execution commands behind a
  smaller set of discoverable workflows while keeping compatibility aliases.
- Make `/config`, `/context`, `/permissions`, `/usage`, and task status readable by default with
  explicit JSON modes for automation.
- Add first-class session switching, background completion notifications, and blocked-task
  recovery without leaving the interactive experience.
- Run terminal snapshot and keyboard-interaction tests at narrow and wide dimensions.

### Command Center Parity

- Keep Command Center on the versioned task/event/config/memory APIs with no scraping of human
  terminal output.
- Verify project and session switching while multiple tasks continue in the background.
- Render planning, tools, permissions, files, validation, memory context, and subagents in the
  chat flow, with detailed diagnostics collapsed by default.
- Complete scalable memory and SQLite browsers with undoable edits and selected-context chat.
- Add first-run installation, provider setup, upgrades, recovery, and compatibility warnings.

### Performance Budgets

- Establish budgets for cold startup, warm startup, project scan, context construction, memory
  search, event throughput, idle daemon memory, and four concurrent tasks.
- Profile and remove repeated scans, unbounded histories, duplicate serialization, and eager
  optional imports.
- Verify usability with 10,000 task events, 100,000 memory nodes, and large repositories.

### 0.80.0 Exit Criteria

- Memory evals meet documented precision, stale-recall, explanation, and token-budget targets.
- Critical terminal and desktop workflows pass automated end-to-end tests.
- No common operation can appear hung without activity or blocked-state feedback.
- Performance budgets pass on documented baseline hardware.
- User testing can complete setup, a coding task, memory review, recovery, and an update without
  manually editing configuration files.

## 0.90.0: Release Candidate And Contract Freeze

**Theme:** Stop changing the product shape and prove it can be supported.

### API And Compatibility Freeze

- Inventory and classify every public Python import, CLI command, config key, task/event schema,
  plugin manifest field, MCP behavior, memory batch operation, and desktop API.
- Freeze the 1.0 stable set and label all remaining surfaces beta or experimental.
- Add migration tests from representative older user configurations, workbench stores, task
  databases, memory graphs, plugins, recipes, agents, and session transcripts.
- Publish a deprecation and compatibility policy covering the 1.x line.
- Add downgrade/rollback guidance and refuse unsafe schema downgrades clearly.

### Security And Supply Chain

- Commission or perform a dedicated security review of command policy, path containment, SSRF,
  gateways, local HTTP servers, session messaging, plugin execution, archive extraction,
  credential storage, and update flows.
- Add dependency auditing, secret scanning, SBOM generation, artifact hashes, and provenance to
  release automation.
- Sign Git tags and release artifacts; sign native desktop installers where the platform permits.
- Document the threat model and security-response process.
- Resolve all critical/high findings and document accepted lower-risk exceptions.

### Release-Candidate Qualification

- Run a multi-week dogfood/soak period with crash, latency, model, permission, and recovery
  observations stored locally and summarized without secrets.
- Run the complete real-agent eval corpus against qualified primary providers.
- Test fresh install, upgrade, repair, uninstall, and reinstall on supported Python versions and
  desktop operating systems.
- Validate offline/local-only use with Ollama or LM Studio.
- Freeze user-facing strings and complete CLI, packaged, repository, and in-app documentation.

### 0.90.0 Exit Criteria

- Overall branch coverage is at least 80%; core execution, permission, persistence, and migration
  modules are at least 90%.
- No ignored mypy errors remain in stable core runtime modules.
- No open P0/P1 defects and no unexplained flaky release gate remain.
- Stable contracts are frozen and exercised by CLI plus at least one external consumer.
- Signed release candidates install and pass acceptance tests on all supported platforms.
- The 1.0 upgrade and rollback procedure has been rehearsed from published artifacts.

## 1.0.0: Supported Local Agent Platform

**Theme:** Publish a dependable compatibility and support promise.

### Release Scope

- Ship the frozen stable contracts without adding a late feature family.
- Publish signed source and wheel artifacts, hashes, SBOM, provenance, GitHub release notes, and
  migration guidance.
- Publish the qualified provider matrix, platform support matrix, known limitations, security
  policy, deprecation policy, architecture, contributor guide, and troubleshooting guide.
- Publish comparable eval, coverage, performance, memory-quality, and cross-platform acceptance
  reports.
- Ensure the packaged docs, repository docs, CLI help, Command Center help, and website describe
  the same supported behavior.

### 1.x Support Promise

- Stable task, event, plugin, configuration, memory, and desktop contracts remain backward
  compatible throughout 1.x except for urgent security corrections with migration guidance.
- Supported Python and platform changes receive advance deprecation notice.
- Provider support tiers may change as upstream APIs change, but evidence dates and limitations
  remain visible.
- Security fixes and data-loss defects take priority over feature development.
- Every patch release runs the stable regression, migration, package, and acceptance suites.

### 1.0.0 Exit Criteria

- All `0.90.0` release-candidate gates remain green on the final commit.
- The full real-agent eval report meets or exceeds the published `0.90.0` baseline.
- Fresh installs and upgrades complete on every supported platform from public artifacts.
- Documentation and contract drift checks report no stale versions or unsupported claims.
- Maintainer release, rollback, security-response, and support procedures are documented and
  usable by someone other than the original implementer.
- The release has no known blocker that would make ordinary coding, productivity, memory, or
  recovery workflows unsafe or materially unreliable.

## Milestone Scorecard

| Milestone | Primary outcome | Required evidence |
| --- | --- | --- |
| `0.50.0` | Measured reliability | Real-agent eval corpus, 72%+ coverage, release evidence |
| `0.60.0` | Maintainable runtime | Core extraction, typed boundaries, real LSP, lean installs |
| `0.70.0` | Qualified interoperability | Provider tiers, MCP/integration suites, three-OS package smokes |
| `0.80.0` | Daily-driver quality | Memory quality, terminal/desktop E2E, performance budgets |
| `0.90.0` | Release candidate | Contract freeze, migrations, security review, signed artifacts |
| `1.0.0` | Supported platform | Public evidence, compatibility promise, rehearsed operations |

## Scope Discipline

The following should normally wait until after 1.0 unless required by a milestone gate:

- additional providers without qualification capacity
- a hosted account or synchronization service
- a public executable-plugin marketplace
- editor extensions that bypass the stable machine API
- more orchestration syntaxes beyond recipes, goals, and Agentic Graphs
- autonomous memory mutation without review, provenance, and undo
- experimental upstream protocols presented as stable support

This roadmap is intentionally demanding. MagAgent does not need six more rounds of feature
accumulation; it needs six rounds that turn its existing breadth into evidence-backed trust.
