# MagAgent Roadmap to 1.0

> Canonical roadmap for all remaining MagAgent work through `1.0.0`.
>
> Last reviewed: 2026-08-14
> Current release: `0.93.0`

## Product Promise

MagAgent 1.0 will be a dependable local-first coding and productivity agent. A user
should be able to install it on a supported platform, configure a qualified model,
complete real work through the CLI or a machine client, inspect and control meaningful
actions, recover interrupted work, and understand the compatibility and safety promise.

The remaining path is about reliability, evidence, cohesion, and supportability. New
feature families should wait unless they directly close a milestone gate.

Open Agent Profile v1 is the deliberate pre-1.0 interoperability exception. Version 0.93.0
ships provisional Level 3 harness support behind MagAgent's existing safety boundaries:
composition, scoped MCP and skills, declared memory stores, constrained delegation, and
background profile continuity. Formal certification remains pending until the canonical OAP
repository and reference fixtures can be pinned and compared.

## Principles

- Measure real task completion, not command count.
- Prefer one execution contract across chat, goals, graphs, recipes, daemon work,
  gateways, and desktop clients.
- Keep state local, inspectable, exportable, and recoverable.
- Fail closed at command, network, path, credential, gateway, and plugin boundaries.
- Qualify provider/model combinations instead of implying that catalog presence equals
  full support.
- Keep optional integrations optional and preserve a practical core installation.
- Ratchet tests, typing, security checks, and performance budgets upward.
- Freeze interfaces only after real CLI and external-client use proves them.

## Released Foundation

### 0.50.0: Measured Reliability

- Added a 32-task deterministic AgentSession evaluation corpus and low-cost live-provider
  qualification workflow.
- Added independent artifact validation, MCP CI, documentation drift checks, and release
  evidence records.
- Established task success, artifact success, latency, tool-call, token, cache, and cost
  measurements.

### 0.60.0: Coherent Runtime and Code Intelligence

- Split the agent runtime into focused context, lifecycle, support, and tool-loop modules.
- Added typed runtime contracts and dependency-direction checks.
- Added a real JSON-RPC LSP client with Python and TypeScript integration coverage plus
  bounded fallbacks for Python, TypeScript/JavaScript, Rust, and Go.
- Split optional capability dependencies into install extras and added clean core-wheel
  smoke testing.
- Shipped with 760 passing tests, 67.45% branch-aware coverage, 32/32 offline agent tasks,
  and 20/20 validated artifact tasks.
- Reduced clean core installation size by 26.64% and average cold CLI import time by
  21.09% against the 0.50.0 baseline.

Tracked implementation histories remain available in Git history. Actionable themes from
the superseded local audit are captured in the 0.70 security and durability gates rather
than preserved as a competing roadmap document.

## 0.70.0: Security, Providers, and Interoperability

**Outcome:** advertised integrations have precise support claims, and high-risk boundaries
have current evidence rather than historical assumptions.

**Status:** released with 777 passing tests, 67.73% branch-aware coverage, 32/32 offline
agent tasks, 20/20 artifact tasks, a passing security-assurance report, and exact-wheel
Python 3.14 acceptance. The 72% roadmap coverage target remains an explicit medium exception;
gateway routing and artifact execution coverage carry forward as focused 0.80 hardening work.

### Security and Durability

- Re-audit structural shell parsing and permission classification with regression cases for
  substitutions, redirects, executable normalization, mutating flags, network uploads,
  saved approvals, and interpreter probes.
- Verify command policy is identical for tools, hooks, recipes, graphs, daemon jobs, and
  gateways; no alternate execution path may bypass the effective policy.
- Enforce shared SSRF and network-action policy across web fetch, HTTP, browser, and shell
  fetch behavior, including redirect and response-size limits.
- Revalidate fail-closed gateway allowlists, scoped approvals, mention rules, rate limits,
  error redaction, shutdown, and session isolation.
- Revalidate local HTTP authentication, host/origin checks, POST-only mutations, bounded
  exposure, and clean shutdown for dashboard and operations surfaces.
- Verify atomic, locked persistence and corruption recovery for workbench, daemon, session,
  permission, and graph state under concurrent access and interrupted writes.
- Add release-blocking tests for path containment, archive extraction, plugin execution,
  credential redaction, runtime-directory ownership, and secret-safe subprocess environments.
- Publish a threat model and a sanitized security verification report. Resolve every known
  critical or high finding before release.

### Provider Qualification

- Add Trusted Router and Prime Intellect as first-class providers across the catalog,
  wizard, credential store, model roles, readiness checks, machine contracts, and docs.
- Define support tiers:
  - **qualified:** completion, streaming, tools, cancellation, retries, usage, and caching tested
  - **compatible:** adapter and catalog checks pass, but live qualification is incomplete
  - **experimental:** explicit upstream or implementation limitations remain
- Maintain a primary matrix for OpenAI, Anthropic, Gemini, Nous Portal, Trusted Router,
  Prime Intellect, OpenRouter, OpenCode Go/Zen, Ollama, and custom OpenAI-compatible servers.
- Exercise chat, native tools, malformed arguments, streaming, cancellation, context limits,
  rate limits, role routing, caching telemetry, and artifact creation.
- Store sanitized, dated qualification reports and detect stale defaults or API behavior.

### Integration Reliability

- Run classic stdio and modern Streamable HTTP MCP conformance fixtures, including timeout,
  invalid payload, cancellation, capability-change, and reconnect behavior.
- Keep MCP Tasks, remote Skills, and Apps experimental until their upstream contracts and
  local conformance gates are stable.
- Add plugin isolation, permission declaration, signature metadata, compatibility, malformed
  manifest, and path-containment tests.
- Add gateway adapter fakes and Playwright browser integration tests for lifecycle,
  authorization, downloads, screenshots, timeout, cancellation, and cleanup.
- Add packaged-wheel acceptance jobs for Linux, macOS, and Windows, with a focused subset for
  filesystem, shell, subprocess, keyring, notification, and installation behavior.

### 0.70.0 Exit Gates

- No unresolved critical or high security or data-loss finding.
- Overall branch coverage reaches at least 72%; permission, persistence, provider request,
  gateway routing, and artifact modules reach at least 85%.
- Every advertised provider has a support tier, evidence date, and documented limitations.
- Primary provider live smokes have no unresolved critical tool-use or streaming defect.
- MCP core, gateway, browser, and plugin integration suites pass their documented gates.
- Public-wheel acceptance passes on Linux, macOS, and Windows.

## 0.80.0: Memory and Daily-Driver Experience

**Outcome:** ordinary terminal and desktop workflows feel responsive, understandable, and
recoverable, while memory produces measurable value within a bounded token budget.

**Status:** released with thresholded memory-quality evidence,
scope/provenance-preserving recall, backlink explanations, model/tool liveness heartbeats,
interactive task recovery and spend controls, versioned desktop recall packets, and quick
plus 10,000-event performance budgets. Final test, coverage, package, and cross-platform
evidence is recorded in the 0.80 release record and generated reports.

### Memory Quality

- Maintain retrieval evaluations for precision, stale-fact avoidance, contradiction handling,
  cross-session continuity, provenance, backlinks, project scope, and token cost.
- Tune lexical, semantic, graph, and recency ranking against those evaluations.
- Complete temporal validity, supersession, canonical identity, reviewed transaction batches,
  rollback, duplicate handling, and corruption recovery across MagGraph and MagAgent.
- Clearly distinguish automatic candidates, reviewed durable memory, and user-authored memory.
- Show a concise, backlink-aware explanation wherever recalled memory enters context.
- Keep ranking feedback inspectable, reversible, and local.

### Terminal Experience

- Provide immediate, timed activity for every model call and long-running tool without
  overwhelming the transcript.
- Make multiline composition, true token streaming, cancellation, resume, retries, permission
  decisions, file changes, validation, and artifact previews consistent across supported terminals.
- Consolidate overlapping plan, goal, graph, recipe, job, and execution entry points around a
  small set of discoverable workflows while retaining compatibility aliases.
- Make configuration, context, permissions, usage, and task status readable by default, with
  explicit machine-output modes.
- Add first-class session switching, background completion notifications, spend guardrails,
  and blocked-task recovery inside interactive sessions.
- Add terminal snapshots and keyboard-interaction tests for narrow and wide layouts.

### Command Center Parity

- Keep Mag Command Center on versioned task, event, config, provider, memory, and artifact APIs;
  it must not scrape human terminal output or duplicate domain behavior.
- Verify project and session switching while multiple tasks continue in the background.
- Render plans, tools, permissions, files, validation, memory, and subagents in the chat flow,
  with detailed diagnostics collapsed by default.
- Complete scalable memory and SQLite browsers with undoable edits and selected-context chat.
- Cover first-run installation, provider setup, upgrades, compatibility warnings, and recovery.

### Performance Budgets

- Establish release gates for cold/warm startup, project scan, context assembly, memory search,
  event throughput, idle daemon memory, and four concurrent tasks.
- Remove repeated scans, unbounded logs, duplicate serialization, eager optional imports, and
  quadratic memory maintenance paths found by profiling.
- Verify responsive behavior with 10,000 task events, 100,000 memory nodes, large repositories,
  and concurrent CLI/desktop readers and writers.

### 0.80.0 Exit Gates

- Memory evaluations meet published precision, stale-recall, explanation, and token targets.
- Critical CLI and Command Center workflows pass automated end-to-end tests.
- No common operation can appear hung without activity or blocked-state feedback.
- Performance budgets pass on documented baseline hardware.
- User testing completes setup, a coding task, session recovery, memory review, and update
  without manual configuration-file editing.

## 0.90.0: Contract Freeze and Release Candidate

**Outcome:** the product shape stops moving and the complete support promise is rehearsed.

**Status:** release candidate implemented with a versioned contract inventory, backup-first
state migration and rollback, unsafe-downgrade refusal, dependency and secret audits,
CycloneDX SBOMs, SHA-256 manifests, in-toto provenance, and CI acceptance evidence. The
multi-week soak, 80% overall branch coverage target, full live-provider corpus, and
maintainer-backed signing remain 1.0 qualification gates rather than implied successes.

### Stable Contract Candidate

- Inventory every public Python import, CLI command, config key, task/event schema, plugin
  manifest field, MCP behavior, memory operation, and desktop API.
- Mark the proposed 1.0 stable set; explicitly label all other surfaces beta or experimental.
- Add migration tests from representative older configurations, workbench stores, task
  databases, memory graphs, plugins, recipes, agent definitions, and transcripts.
- Publish 1.x compatibility, deprecation, upgrade, downgrade, and rollback policies.
- Refuse unsafe schema downgrades with actionable diagnostics.

### Supply Chain and Operations

- Add dependency auditing, secret scanning, SBOM generation, artifact hashes, and provenance
  to release automation.
- Sign Git tags and Python artifacts; sign native desktop installers where platform tooling and
  maintainer credentials permit.
- Publish security reporting, response, release, rollback, and support procedures that another
  maintainer can follow.
- Exercise fresh install, upgrade, repair, uninstall, and reinstall from public artifacts.

### Release-Candidate Qualification

- Run a multi-week dogfood and soak period, recording crash, latency, permission, provider,
  recovery, and resource observations without product telemetry or secrets.
- Run the complete real-agent corpus against qualified primary providers.
- Validate local-only use with Ollama or LM Studio.
- Freeze user-facing terminology and reconcile repository, packaged, CLI, API, and Command
  Center documentation.

### 0.90.0 Exit Gates

- Overall branch coverage reaches at least 80%; core execution, permission, persistence,
  migration, and credential modules reach at least 90%.
- Stable runtime modules have no ignored typing errors.
- No open P0/P1 defects and no unexplained flaky release gate.
- Candidate contracts are frozen and exercised by the CLI and Mag Command Center.
- Signed release candidates install and pass acceptance tests on supported platforms.
- The 1.0 upgrade and rollback procedure has been rehearsed from published artifacts.

## 0.91.0: Release-Candidate Hardening

**Status:** released as a focused corrective pass over the 0.90 candidate. Provider errors
now fail qualification, common provider aliases are canonicalized, clean base wheels run an
explicit core eval profile, and the complete optional-capability profile remains mandatory.
Durable event ingestion uses bounded transactions while interactive events retain immediate
full-sync durability. Task persistence, workbench persistence, migrations, command policy,
and permissions now meet the focused core coverage target.

The remaining 1.0 gates are intentionally unchanged: overall branch coverage, multi-week
soak evidence, full live-provider qualification, local-only model qualification,
cross-platform hosted acceptance on the final commit, and maintainer-backed signing.

## 1.0.0: Supported Local Agent Platform

**Outcome:** publish the frozen contracts and an evidence-backed compatibility promise.

### Release Work

- Ship the 0.90 stable contract candidate without introducing a late feature family.
- Publish signed wheel and source artifacts, hashes, SBOM, provenance, migration guidance,
  provider matrix, platform matrix, known limitations, and security policy.
- Publish comparable agent-eval, coverage, performance, memory-quality, and cross-platform
  acceptance reports.
- Ensure packaged docs, repository docs, CLI help, machine APIs, Command Center help, and the
  project website describe the same behavior.

### 1.x Promise

- Stable task, event, plugin, configuration, memory, and desktop contracts remain backward
  compatible throughout 1.x except for urgent security corrections with migration guidance.
- Supported Python and platform changes receive advance deprecation notice.
- Provider support tiers may change with upstream APIs, but evidence dates and limitations
  remain visible.
- Security and data-loss defects take priority over feature work.
- Every patch release runs stable regression, migration, package, and acceptance suites.

### 1.0.0 Exit Gates

- All 0.90 release-candidate gates remain green on the final commit.
- Real-agent results meet or exceed the published 0.90 baseline.
- Fresh installs and upgrades succeed from public artifacts on every supported platform.
- Documentation and contract drift checks report no stale versions or unsupported claims.
- Maintainer release, rollback, security-response, and support procedures are independently usable.
- No known blocker makes ordinary coding, productivity, memory, or recovery workflows unsafe or
  materially unreliable.

## Milestone Scorecard

| Milestone | Primary outcome | Required evidence |
| --- | --- | --- |
| `0.70.0` | Qualified and hardened integrations | Security report, provider tiers, integration suites, three-OS wheel acceptance |
| `0.80.0` | Daily-driver quality | Memory evals, CLI/desktop E2E, streaming UX, performance budgets |
| `0.90.0` | Release candidate | Contract freeze, migrations, supply-chain evidence, signed acceptance builds |
| `0.91.0` | Candidate hardening | Fail-closed provider evals, exact-wheel profiles, persistence and performance evidence |
| `1.0.0` | Supported platform | Public evidence, compatibility promise, rehearsed operations |

## Scope Held Until After 1.0

- Additional providers without qualification capacity.
- A hosted account, synchronization service, or cloud control plane.
- A public executable-plugin marketplace before trust and signing are enforced.
- Editor extensions that bypass the stable machine API.
- More orchestration syntaxes beyond goals, recipes, and Agentic Graphs.
- Autonomous durable-memory mutation without review, provenance, and undo.
- Experimental upstream protocols presented as stable support.

This roadmap is intentionally demanding. MagAgent already has substantial breadth; the path
to 1.0 is to turn that breadth into evidence-backed trust.
