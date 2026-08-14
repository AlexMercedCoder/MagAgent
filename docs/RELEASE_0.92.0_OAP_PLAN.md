# MagAgent 0.92.0 Open Agent Profile Release Plan

> Status: implemented and qualified. The final release record is
> `docs/RELEASE_0.92.0.md`.

**Status:** Proposed implementation plan
**Target:** Open Agent Profile v1, conformance Level 2
**Source guide:** `docs/oap-implementation-plan.md`
**Current baseline:** MagAgent 0.91.0

## Release Decision

Ship OAP as `0.92.0`, not as a late addition to `1.0.0`. OAP changes agent
definition parsing, runtime capability selection, prompt construction, and persistent
state. It therefore needs its own compatibility release and soak period before the 1.0
contract is declared final.

The release must preserve all existing `.magent/agents/*.md` files and the public
`magent agent` command group. OAP support is additive. Existing definitions are
converted in memory when read and are only rewritten by an explicit conversion command.

## Intended Outcome

At release, a user can:

- Load OAP YAML, JSON, or Markdown profiles from managed, user, project, and plugin roots.
- Continue using every legacy MagAgent agent definition without editing it.
- Inspect the profile as written and the narrower profile MagAgent will actually run.
- Start a profile-bound chat or one-shot task, or invoke a profile with `@name`.
- See the selected model, effective tools, effective permissions, limits, trust, revision,
  source, and every narrowing adjustment.
- Inject bounded, secret-scrubbed profile state as explicitly untrusted context.
- Review, accept, or reject proposed `/state` changes before durable writeback.
- Validate digests, inspect history, forget individual state entries, and roll back a bad
  write through checkpointed persistent state.

## Contract Decisions

### CLI Compatibility

Keep the canonical command group singular:

```text
magent agent list
magent agent show NAME
magent agent explain NAME
magent agent validate PATH
magent agent create NAME
magent agent convert PATH [--write]
magent agent state NAME
magent agent history NAME
magent agent forget NAME ENTRY_ID
magent agent inbox
magent agent accept DELTA_ID
magent agent reject DELTA_ID --reason TEXT
magent agent digest NAME
```

Do not rename the existing group to `magent agents`. A plural alias may be added later,
but it is not required for OAP conformance and must not duplicate command registration.
All commands provide stable JSON output for Command Center and other machine clients.

Add `--agent NAME` to one-shot and interactive entry points. A session created with this
option is profile-bound for its lifetime. Existing `@name` invocation remains turn-scoped
for backward compatibility, but its effective provider, tools, permissions, prompt, and
limits are resolved before that turn begins and restored in `finally` after the turn.
Profile state proposals from turn-scoped invocations remain attributed to the invoked
profile.

### Runtime Boundary

Introduce three immutable types:

- `ResolvedProfile`: parsed document, source, root-derived trust, digests, warnings.
- `EffectiveProfile`: policy intersection, model selection, limits, adjustments.
- `ProfileTurnContext`: the effective profile and bounded state used by one model turn.

`AgentSession` and the tool loop must consume only `EffectiveProfile` or
`ProfileTurnContext`; untrusted requested capabilities never cross directly into runtime
objects. The no-profile prompt and runtime path must remain byte-for-byte compatible.

### Trust and Precedence

Trust is assigned by the discovery root and any trust claim inside a profile is ignored.
Use one documented precedence order for name collisions:

1. User profile root
2. Project `.magent/agents`
3. Portable project `.agents`
4. Enabled plugin profiles
5. Managed built-ins

This follows the source guide's explicit acceptance rule that user definitions override
project and plugin definitions. Every shadowed profile is reported; duplicates within one
root are errors. A profile's precedence never grants authority because all capabilities
still pass through effective-policy narrowing.

### Permission and Tool Narrowing

Represent MagAgent permission modes as decision vectors over risk tiers rather than using
a string ordering. Intersect the configured vector with the requested OAP vector per tier,
then map to the nearest built-in mode that is no more permissive. Add tests for all mode
pairs, including the special tier-3 behavior of `yolo` and `silent`.

Effective tools are:

```text
configured capability tools
INTERSECT profile allow patterns
MINUS profile deny patterns
```

Missing allow patterns mean no additional profile restriction; they do not mean no tools.
Legacy `tools` mappings convert into allow/deny decisions without gaining tools. Limits and
budgets use the lower of the harness and profile values. Each drop, fallback, or narrowing
creates a machine-readable adjustment.

### State and Context Budgets

Do not compare token counts with byte counts. Enforce both independently:

- `max_state_bytes`: storage and parsing ceiling.
- `max_state_tokens`: prompt-injection ceiling.
- `memory_budget_tokens`: existing MagGraph recall ceiling.
- `context_window_tokens`: combined final ceiling.

Profile state gets its declared token allocation first, then MagGraph recall uses its own
allocation, and final context assembly enforces the overall window. Evict whole unpinned
entries according to the profile strategy; never truncate an entry or evict a pinned entry.
Report omitted entry counts in the untrusted state block.

### Review and Writeback

Reuse the inbox UX, not the current MagGraph-specific accept implementation. Introduce a
typed review-candidate dispatcher with `memory` and `agent_profile_delta` backends. The
profile backend validates revision, digest, operation scope, writeback ceiling, retention,
history, and checkpoint creation before applying anything.

Only `/state` JSON Pointer paths are writable. There is no bypass flag. Proposal operations
never auto-apply. Every operation value is secret-scrubbed before queueing and again before
writing. Writes use same-directory temporary files, file `fsync`, `os.replace`, and directory
`fsync`.

Project profiles are outside MagAgent's config backup root, so profile writes need their own
checkpoint registration. Do not claim `magent system rollback` covers project profiles until
the rollback inventory explicitly includes those files.

## Implementation Sequence

### 0. Pin the Specification and Record an ADR

- Fetch the OAP v1 specification, conformance fixtures, security guide, implementer guide,
  and reference applicator from one exact upstream commit.
- Vendor the required schemas and fixtures under `src/magent/agent_profiles/schema/v1/`
  and `tests/fixtures/oap/v1/` with source URL, commit, license, and SHA-256 records.
- Add an architecture decision covering activation semantics, precedence, trust, narrowing,
  state budgeting, and writeback.
- Confirm Level 2 requirements against the pinned spec before coding.

**Gate:** vendored schema validates against upstream fixtures and the source digest is
reproducible.

### 1. Document Model, Validation, Digests, and Legacy Adapter

- Add `agent_profiles/models.py`, `resolver.py`, `digest.py`, `legacy.py`, and `errors.py`.
- Use the existing `jsonschema` dependency; do not add a second validation framework unless
  schema ergonomics demonstrate a concrete need.
- Parse Markdown frontmatter with a SafeLoader that disables implicit YAML timestamp
  conversion.
- Detect OAP by the frontmatter `oap` key, independent of extension.
- Convert legacy definitions in memory, preserve unmapped fields in annotations, default
  writeback to `propose`, and never write during read/list/show.
- Implement canonical spec/profile digests and compare them with the reference fixtures.
- Leave `agent_defs.py` as a compatibility facade returning `AgentDefinition`.

**Gate:** all valid and invalid fixtures behave as expected, all current legacy fixtures
load unchanged, and reads produce no filesystem changes.

### 2. Registry, Discovery, Trust, Built-ins, and Performance

- Add lazy metadata discovery across managed, user, project, portable project, and plugin
  roots.
- Enforce the documented precedence, collision diagnostics, root-derived trust, maximum
  profile count, and path containment.
- Re-express `review`, `explore`, and `docs` as managed OAP documents while preserving their
  current prompts and legacy `AgentDefinition` projections.
- Add an OAP registry cache keyed by root path plus file stat signature.
- Add profile discovery and selected-profile load benchmarks to the quick performance suite.

**Gate:** built-in behavior is unchanged; collisions and false trust claims are visible;
discovery remains within the existing startup budget.

### 3. Effective Policy and Model Resolution

- Add `effective.py` and permission-vector intersection helpers.
- Intersect tools with enabled capability packs and explicit config policy.
- Narrow permission decisions, tool budgets, turn limits, spend limits, filesystem roots,
  network access, memory mode, and writeback mode.
- Resolve exact provider/model, fallbacks, model tier/role, then default, recording every
  fallback.
- Resolve context paths after symlinks and reject workspace escapes.
- Produce a complete `agent explain` payload from this layer.

**Gate:** dedicated security tests prove profiles cannot add tools, widen permissions,
increase budgets, escape the workspace, select unavailable credentials, or delegate around
the parent ceiling.

### 4. Runtime Activation and Prompt Assembly

- Add optional profile selection to `AgentSession` and update CLI, subagent, daemon, gateway,
  graph, eval, and provider-smoke call sites explicitly.
- Resolve `--agent` before constructing providers and `ToolExecutor`.
- Implement a guarded turn scope for legacy `@name` invocation so capability changes are
  applied before prompt/tool execution and always restored.
- Assemble the stable prompt in OAP normative order while retaining MagAgent's preamble and
  safety postamble as authoritative.
- Record name, revision, digests, trust, source, and adjustments in scratchpad, durable task
  metadata, session timeline, and activity events.
- Add `lifecycle.on_start` and `on_end` as named-hook references. Profiles may name configured
  hooks but never contain commands.

**Gate:** `@review` has its actual read-only effective tools and paranoid permissions, a
profile-bound session retains identity, and the no-profile prompt is byte-identical.

### 5. Bounded State Injection

- Add state loading, secret scrubbing, retention selection, token accounting, and rendering.
- Inject the delimited `<agent-state trust="untrusted">` block in the normative position.
- Coordinate profile state, MagGraph recall, repository context, skills, and conversation
  under the final context budget.
- Reject variable substitution inside state and treat state text only as background data.

**Gate:** malicious state cannot alter permissions or tool access, pinned entries survive
eviction, and all context sources remain within measured token budgets.

### 6. Delta Proposals, Inbox Dispatch, Atomic Apply, and Recovery

- Add evidence-derived profile delta generation to session lifecycle without reusing the
  MagGraph memory output shape.
- Route agent-specific operating knowledge to profile state and general user/project facts
  to MagGraph with explicit tests for both directions.
- Generalize inbox candidate records and backend dispatch while preserving existing memory
  CLI and UI behavior.
- Add revision/digest conflict checks, `/state`-only operations, retention, history, atomic
  writes, checkpoints, and interrupted-write recovery.
- Reject conflicts in 0.92.0 with actionable diagnostics; defer automatic rebase.

**Gate:** proposed changes require review, secrets never reach disk, interrupted writes keep
the previous revision valid, and accepted deltas increment revision exactly once.

### 7. CLI, Machine API, Plugins, Migration, and Documentation

- Expand `magent agent` with list/show/explain/validate/create/convert/state/history/forget/
  inbox/accept/reject/digest.
- Make conversion preview-only unless `--write`; create a backup and checkpoint before
  explicit conversion.
- Add profile schema and effective-profile endpoints to the desktop machine contract so Mag
  Command Center never parses human output.
- Load plugin profiles at plugin trust and route imported Claude, OpenCode, Gemini, Pi, and
  Codex agent documents through the same legacy adapter.
- Register OAP state in persistent-state and compatibility inventories without declaring
  unstable writeback fields as frozen 1.x contracts.
- Add repository, packaged, CLI, and in-app docs plus `docs/oap-conformance.json`.

**Gate:** all commands have CLI and JSON contract tests; plugin profiles cannot widen install
permissions; docs drift and packaged-doc checks pass.

### 8. Release Qualification

- Run the full unit, integration, architecture, security, migration, package, and agent eval
  suites on Python 3.11 through 3.14.
- Run upstream OAP Level 2 conformance fixtures from the pinned commit.
- Add mutation/property tests around narrowing and delta scope.
- Run profile discovery, prompt assembly, and 200-profile performance cases.
- Build exact wheel/sdist, install in clean core and full environments, and verify legacy plus
  OAP sessions from the installed artifact.
- Run Linux, macOS, and Windows hosted acceptance on the release commit.
- Publish sanitized conformance, performance, compatibility, test, coverage, and migration
  evidence.

**Gate:** no critical/high security or data-loss issue, no legacy agent regression, all Level
2 conformance checks pass, and the 0.92 artifact can be rolled back safely before tagging.

## Test Map

| Test module | Required coverage |
| --- | --- |
| `test_agent_profile_documents.py` | Valid/invalid fixtures, safe YAML, canonical digests |
| `test_agent_profile_legacy.py` | Existing definitions, annotations, preview/write conversion |
| `test_agent_profile_registry.py` | Roots, precedence, duplicates, trust, lazy caching |
| `test_agent_profile_narrowing.py` | Permission vectors, tools, limits, paths, adjustments |
| `test_agent_profile_runtime.py` | `--agent`, `@name`, restoration, all session call sites |
| `test_agent_profile_render.py` | Normative order, untrusted labels, combined budgets |
| `test_agent_profile_delta.py` | Scope, secrets, conflicts, atomicity, retention, revision |
| `test_agent_profile_routing.py` | Profile-state versus MagGraph routing |
| `test_agent_profile_cli.py` | Human and JSON output for every command |
| `test_agent_profile_plugins.py` | Imported/plugin trust and permission ceilings |
| `test_agent_profile_performance.py` | Discovery, selected load, prompt assembly at scale |

## Deferred Level 3 Work

Do not include these in 0.92.0 unless Level 2 is complete and the release is still within
all gates:

- `extends` composition.
- Profile-declared MCP servers.
- Profile-declared skill references.
- OAP subagent declarations and full delegation composition.
- MagGraph declared as a portable profile memory store.
- Automatic conflict rebase or profile synchronization.

Existing MagAgent MCP, skills, subagents, and MagGraph continue to work through harness
configuration. The 0.92 conformance statement must list these OAP fields as unimplemented.

## Primary Risks

| Risk | Mitigation |
| --- | --- |
| A profile widens runtime authority | Immutable effective type, vector intersection, security tests |
| `@name` mutates a live session incorrectly | Guarded turn scope with restoration and failure tests |
| State becomes prompt injection | Untrusted delimiter, authoritative postamble, no substitution |
| State leaks credentials | Scrub before queue and before write; secret regression corpus |
| Concurrent sessions lose updates | Revision and digest compare; reject conflicts in 0.92 |
| Inbox refactor breaks MagGraph review | Backend dispatch with unchanged memory contract tests |
| Project profile rollback is incomplete | Profile-specific checkpoints and explicit inventory |
| Discovery slows startup | Metadata-only scan, stat cache, 200-profile benchmark |
| OAP destabilizes the 1.0 candidate | Separate 0.92 release and soak before final contract freeze |

## Definition of Done

The release is ready only when all of the following are true:

1. The pinned OAP v1 Level 2 conformance suite passes from the packaged wheel.
2. Every existing MagAgent agent definition and `@review`, `@explore`, and `@docs` behavior
   remains compatible.
3. A profile cannot widen tools, permissions, budgets, paths, network, writeback, memory, or
   delegation authority.
4. State is bounded, untrusted, secret-scrubbed, reviewable, atomic, versioned, and
   recoverable.
5. Human CLI, JSON machine APIs, repository docs, packaged docs, and Command Center contract
   documentation agree.
6. Full tests, security gates, performance budgets, exact-package tests, and three-platform
   acceptance pass on the tagged commit.
