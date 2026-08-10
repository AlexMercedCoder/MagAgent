# MagAgent × Agentic Graph Specification — implementation roadmap

> Companion to [ROADMAP.md](ROADMAP.md). Scoped to one capability: making MagAgent a first-class
> **Agentic Graph** harness — able to accept, validate and execute graphs users hand it, and to
> generate conformant graphs from a goal.
>
> Spec repository: **`agentic-graph-spec`** (AGS 1.0) —
> <https://github.com/AlexMercedCoder/agentic-graph-spec>
> Key references: `SPEC.md`, `schema/agentic-graph-1.0.schema.json`,
> `schema/agentic-graph-run-1.0.schema.json`, `docs/harness-integration.md`,
> `docs/skill-authoring.md`, `tools/validate_agraph.py`.
>
> Status: proposed. Nothing here is built yet.
> Last updated: 2026-08-09. Baseline: MagAgent 0.34.0, MagGraph 0.4.1, 411 passing tests.

---

## 1. Why this fits MagAgent specifically

MagAgent already has almost every runtime primitive AGS needs. What it does not have is a
**portable, reviewable representation of the decomposition** — and that is precisely the gap AGS
fills.

The existing pieces, and what each becomes under AGS:

| MagAgent today | AGS concept | Fit |
| --- | --- | --- |
| `src/magent/agent.py` → `AgentSession.chat()` | The inside of a `task` node | Direct. The agentic loop becomes the node executor's inner loop and needs no change. |
| `src/magent/goal_orchestrator.py` → `create_orchestrated_goal`, `_build_steps`, `build_step_packet` | A generated graph, and its execution | Near-direct. `orchestration.steps` is already a linear node list with validation criteria and summary requirements; AGS generalizes it from a list to a DAG. |
| `src/magent/task_runtime.py` → `TaskRuntime` SQLite ledger | Node state machine + run record | Very close. `TASK_STATES` is `queued/planning/running/waiting/blocked/validating/completed/failed/cancelled`; AGS wants `pending/ready/running/awaiting_human/succeeded/failed/skipped/cancelled/blocked`. The overlap is most of the way there. |
| `TaskRuntime` `parent_task_id`, `planning_role`, `execution_role`, `permission_policy` | Subgraph nesting, tier routing, permission ceiling | Already the right columns; they need AGS-shaped values. |
| `src/magent/subagents/__init__.py` → `SubAgentRunner.spawn`, `spawn_parallel` | Parallel node execution | Direct, but capped at `max_subagents: 3` / `max_parallel_subagents: 2`. AGS `constraints.max_parallel_nodes` needs to drive this. |
| `src/magent/config/__init__.py` → `models` roles (`coding`, `review`, `memory`, `cheap`, `image_maker`, `fallback`) and `provider_and_model_for_role()` | **Routing profile** | This *is* an AGS routing profile with different key names. Mapping `minimal→cheap`, `standard→coding`, `advanced→coding`, `frontier→review` is a config decision, not new machinery. |
| `src/magent/model_capabilities.py` → `model_capabilities()`, `context_tokens`, `cost_tier` | `intelligence.min_context_tokens` enforcement | Already tracks the one number AGS makes a hard floor. |
| `src/magent/permissions/__init__.py` → `RiskTier` 0–3, modes (`balanced` default) | `requirements.permissions` intersection, HITL confirmation | Direct. AGS permissions are a *requested ceiling*; MagAgent's policy stays the enforced one. |
| `src/magent/sandbox.py` → worktree / copied / Docker | `constraints.isolation` (`shared`/`worktree`/`sandbox`/`container`) | Direct, four-to-three mapping. |
| `src/magent/workbench_store.py` → `WorkbenchStore` collections (`plans`, `tasks`, `goals`, `runs`, `artifacts`, `checkpoints`, `reviews`, `patches`) | Graph documents and run records at rest | Direct. A `graphs` collection joins the set. |
| `src/magent/execution_bridge.py` → `SessionTaskBridge` | Per-node attempt recording | Direct. Already persists evidence and forwards records. |
| `src/magent/hooks.py`, `src/magent/events.py`, `src/magent/activity_events.py` | Run-record events, `before_side_effects` checkpoints | Hooks around tools and edits are exactly the interception point AGS needs. |
| `src/magent/skills/__init__.py` → `SkillRegistry`, `MAX_ACTIVE_SKILLS` | `requirements.skills` | Direct. |
| `src/magent/tools/registry.py`, `tool_packs.py`, `tools/catalog.py` | `requirements.tools` logical names | Needs a name-mapping layer: AGS says `file_write`, MagAgent has its own tool ids. |
| `src/magent/desktop_api.py` | Machine interface for graph plan/run in Mag Command Center | The plan-review UI has a home already. |
| `src/magent/recipes.py`, `src/magent/agent_defs.py`, `.magent/playbook.toml` | Reusable graph fragments | A recipe that is really a DAG becomes an AGS `subgraphs` fragment. |

**The strategic argument.** ROADMAP.md's stated thesis is that Mag should be "the local-first agent
ecosystem where execution is inspectable" with "one stable machine interface shared by the CLI and
desktop app". A graph document is inspectable execution in file form, and it is a machine interface
that is not MagAgent-specific. AGS support turns `magent goal --orchestrated` from an internal
feature into an interoperable one, and gives Mag Command Center something concrete to render.

**The honest counter-argument.** MagAgent already ships `goal --orchestrated`. If AGS support becomes
a second, parallel execution path, the codebase gets a duplicate orchestrator and the concentrated-
module risk ROADMAP.md already flags gets worse. **The plan below therefore treats AGS as the
successor representation for orchestrated goals, not as a sibling** — Phase 4 explicitly retargets
`goal_orchestrator.py` onto the graph runner rather than leaving two engines.

---

## 2. Target architecture

New package `src/magent/agraph/`, with everything else reused:

```
src/magent/agraph/
├── __init__.py
├── document.py      # load JSON/YAML, duplicate-key rejection, canonical digest
├── validate.py      # AG0xx / AG1xx / AG2xx / AG9xx findings with JSON Pointers
├── expressions.py   # AGX tokenizer, parser, evaluator (no host eval)
├── plan.py          # effective edge set, topo order, reachability, worst-case count, cost
├── schedule.py      # readiness, edge activation, skip propagation, join modes
├── execute.py       # per-node lifecycle; wraps AgentSession
├── routing.py       # intelligence tier -> magent model role -> provider/model
├── criteria.py      # the nine criterion kinds
├── hitl.py          # gate nodes and human[] checkpoints
├── generate.py      # goal -> graph (the second direction)
└── record.py        # AGS run record emission
```

Integration seams, all existing:

- **Node execution** → `AgentSession` (`src/magent/agent.py`) via `SubAgentRunner`
  (`src/magent/subagents/__init__.py`), one sub-agent per node.
- **State and events** → `TaskRuntime` (`src/magent/task_runtime.py`), one task row per node
  execution, `parent_task_id` giving the graph run its tree.
- **Documents and records at rest** → `WorkbenchStore` (`src/magent/workbench_store.py`), new
  `graphs` and `graph_runs` collections.
- **CLI** → a new `graph_app` Typer group registered in `src/magent/cli/app.py`, with commands in
  `src/magent/cli/commands/graph.py`. **Do not add commands to `src/magent/cli/main.py`** — it is
  4,881 lines and ROADMAP.md already flags it.
- **Desktop** → `src/magent/desktop_api.py` gains graph plan/run/approve endpoints.

---

## 3. Phases

Effort key: **S** ≈ 1–2 days · **M** ≈ 3–5 days · **L** ≈ 1–2 weeks. Sizes assume familiarity with
the module being touched.

### Phase 0 — Decide and de-risk (before writing code)

| # | Item | Effort | Depends on | Notes |
| --- | --- | --- | --- | --- |
| 0.1 | Decide the relationship to `goal_orchestrator.py`: successor (recommended) vs sibling | S | — | Everything downstream branches on this. Successor means Phase 4 exists; sibling means permanent duplication. |
| 0.2 | Fix the tier → model-role mapping and write it into `DEFAULT_CONFIG["models"]` docs | S | 0.1 | Proposed: `minimal→cheap`, `standard→coding`, `advanced→coding`, `frontier→review`, with a new optional `frontier` role for users who want a distinct top model. |
| 0.3 | Fix the logical-tool-name mapping table (AGS `file_read`/`file_write`/`shell_exec`/… → MagAgent tool ids in `src/magent/tools/catalog.py`) | S | — | Publish it; it is part of MagAgent's conformance claim. |
| 0.4 | Vendor or depend on `tools/validate_agraph.py` from the spec repo; add `jsonschema`/`pyyaml` to `pyproject.toml` if not already present | S | — | `pyyaml` is already a dependency (`src/magent/skills/__init__.py` imports it). |
| 0.5 | Write three real MagAgent-shaped example graphs into `docs/examples/agraph/` | M | 0.2, 0.3 | Release prep, bug triage, docs audit — mirror the existing recipes in `src/magent/recipes.py` so the comparison is concrete. |

**Exit:** the two mapping tables exist and three example graphs validate cleanly under the spec
repo's `--strict` validator.

---

### Phase 1 — Read and understand graphs (AGS conformance level 0)

Ship this alone. It is useful on its own and it is what every later phase is built on.

| # | Item | Effort | Depends on | Notes |
| --- | --- | --- | --- | --- |
| 1.1 | `agraph/document.py`: load `.agraph.json` / `.agraph.yaml`, reject duplicate YAML keys, compute the canonical SHA-256 digest | S | 0.4 | Duplicate-key rejection matters: a duplicated node id would silently drop a node. Spec §3. |
| 1.2 | `agraph/validate.py` layers 1 and 2 — JSON Schema plus cycles, dangling ids, entrypoints, joins, decision branches, fragment refs | M | 1.1 | Findings as `{code, severity, message, pointer}`. Port from the spec repo's validator. |
| 1.3 | `agraph/expressions.py`: AGX tokenizer + recursive-descent parser | M | — | Parser only in this phase. **Never `eval()`** — graph documents are untrusted input (spec §22). |
| 1.4 | `agraph/validate.py` layer 3 — scope checks, the predecessor rule (AG201), undeclared references, `secrets.*` prohibition (AG205) | M | 1.2, 1.3 | This is where most generated-graph bugs get caught. |
| 1.5 | `agraph/plan.py`: effective edge set, topological order, reachability, worst-case execution count, projected cost from `estimate`, tier histogram | M | 1.2 | Worst-case count multiplies `retry.max_attempts` × `loop.max_iterations` × `map.max_items` through every nesting level. |
| 1.6 | CLI: `magent graph validate <file>` and `magent graph plan <file> [--json]` in a new `src/magent/cli/commands/graph.py` | S | 1.2, 1.5 | Register `graph_app` in `src/magent/cli/app.py` alongside `plan_app`/`execution_app`. |
| 1.7 | Rich rendering of the plan: nodes in topological order with tier and estimate, parallel groups, gate positions, projected cost | S | 1.5 | Reuse the table/panel patterns in `src/magent/ui.py`. |
| 1.8 | Store graph documents in `WorkbenchStore` under a new `graphs` collection: `magent graph add`, `list`, `show` | S | 1.1 | Keeps the digest so later runs can be tied to a document version. |
| 1.9 | Tests: the spec repo's `conformance/invalid/` fixtures, each asserting its `# EXPECT:` code | M | 1.4 | Straight into `tests/`; keeps MagAgent honest against the spec as it moves. |

**Exit:** `magent graph validate` and `magent graph plan` work on all five spec examples, and every
`conformance/invalid/` fixture reports its expected diagnostic. MagAgent can claim **conformance
level 0**.

---

### Phase 2 — Execute graphs (AGS conformance level 1)

The milestone that makes the format real for users.

| # | Item | Effort | Depends on | Notes |
| --- | --- | --- | --- | --- |
| 2.1 | `agraph/routing.py`: tier → model role → `Config.provider_and_model_for_role()`; enforce `min_context_tokens` against `model_capabilities()`; refuse with `RT011` when the tier cannot be met and `allow_downgrade` is false | M | 0.2 | Spec §11.4 is normative and short. The refusal-before-spending rule is the valuable part. |
| 2.2 | Extend `TaskRuntime` with AGS node states: add `ready`, `awaiting_human`, `skipped`; map `completed→succeeded`, `validating→` criteria evaluation | M | — | `TASK_STATES` and `_TRANSITIONS` in `src/magent/task_runtime.py`. Bump `TASK_SCHEMA_VERSION` and migrate. Touches the desktop contract — coordinate with `src/magent/desktop_api.py`. |
| 2.3 | `agraph/schedule.py`: edge activation table, readiness per join mode, skip propagation, deterministic tie-break (topological then declaration order) | M | 1.5, 2.2 | Spec §17.3–§17.6. The tie-break is normative — without it the same graph runs in different orders twice. |
| 2.4 | `agraph/execute.py`: per-node lifecycle — resolve inputs once, verify requirements, run `AgentSession` via `SubAgentRunner`, collect outputs, evaluate criteria | L | 2.1, 2.3 | Inputs resolve **once** and are reused verbatim by retries (spec §9.2). |
| 2.5 | Output contract: decide how a node reports declared outputs (recommended: a `graph_emit_output` tool registered in `src/magent/tools/registry.py`, plus `path_hint` file discovery) and put it in the node prompt | M | 2.4 | Without one mechanism this is the flakiest part of the whole feature. |
| 2.6 | `agraph/criteria.py`: `command`, `file_exists`, `artifact_present`, `human` | M | 2.4 | `command` runs through the existing permission and sandbox path (`src/magent/permissions/`, `src/magent/sandbox.py`). Always honor `timeout_seconds`. Capture evidence. |
| 2.7 | Retry with feedback: `retry.max_attempts`, `retry_on` class matching, `feedback: failed_criteria` injecting each failed criterion's `description` **and evidence** into the next attempt | M | 2.6 | This is what makes a retry a different task instead of a coin flip. |
| 2.8 | `gate` nodes and `human` checkpoints at `before_start` / `after_outputs`, via the existing confirmation UX in `src/magent/permission_ux.py` and `src/magent/ux_flows.py` | M | 2.4 | If a checkpoint cannot be presented, fail the node with `RT015`. Never skip silently. |
| 2.9 | `requirements` enforcement: intersect `permissions` with `Config.permission_mode` policy; map logical tool names; block on unavailable non-optional tools (`RT012`) | M | 0.3, 2.4 | Intersect, never union. A graph asking for more than policy allows gets `blocked`. |
| 2.10 | CLI: `magent graph run <file> [--dry-run] [--yes]`, `magent graph status <run-id>`, `magent graph resume <run-id>` | M | 2.4 | Wire `graph status` through `TaskRuntime.events()` so it reuses the existing execution event stream. |
| 2.11 | Reject graphs above the supported level with `AG303`, naming the missing features | S | 1.2 | A level 1 harness must reject, not degrade (spec §19). |
| 2.12 | Tests: execute `examples/minimal.agraph.yaml` end to end; assert scheduling determinism; assert the `RT011` routing refusal | M | 2.10 | Add to `evals/` as a repeatable suite, per ROADMAP.md's reliability-measurement goal. |

**Exit:** `magent graph run examples/minimal.agraph.yaml` completes with criteria actually checked.
**Conformance level 1.**

---

### Phase 3 — Branching, budgets and parallelism (AGS conformance level 2)

| # | Item | Effort | Depends on | Notes |
| --- | --- | --- | --- | --- |
| 3.1 | AGX **evaluator** on top of the Phase 1 parser: strict typing, the fixed function set, no host eval | M | 1.3 | Spec `docs/expressions.md` §4–§5. Strict typing is deliberate; do not coerce. |
| 3.2 | `decision` nodes: constrain the model's answer to declared labels; `default_branch` + `RT022` on an out-of-set answer; `evaluator: expression` needs no model call | M | 3.1, 2.4 | Reuse structured-output handling already used for memory extraction (`src/magent/memory/extraction.py`). |
| 3.3 | `conditional` and `on_failure` edges, node-level `when`, `join: any` / `n_of` | M | 3.1, 2.3 | Mostly scheduler additions once the evaluator exists. |
| 3.4 | Criterion kinds `expression`, `regex`, `json_schema` | S | 3.1 | |
| 3.5 | Budget enforcement: node `constraints` (tokens, cost, wall clock, tool calls, `max_agent_steps`) and graph `constraints`, with the nesting rule `min(node, remaining global)` | M | 2.4 | Token accounting exists in `src/magent/tokens.py`; per-node attribution is the new part. |
| 3.6 | Real parallelism: drive `SubAgentRunner.spawn_parallel` from `constraints.max_parallel_nodes`, honor `concurrency_group` | M | 2.3, 2.4 | Today `max_subagents: 3` / `max_parallel_subagents: 2` are hard config caps (`src/magent/config/__init__.py`). Graph-declared parallelism must be clamped by them, and the clamp reported. |
| 3.7 | `constraints.isolation` → `src/magent/sandbox.py` (`worktree`, `sandbox`, `container`); fail rather than downgrade (`RT014`) | M | 3.6 | Worktree isolation is what makes parallel write-heavy nodes safe. |
| 3.8 | `failure.fallback` (all five strategies) and `failure.escalation` | M | 2.7 | `escalation.to: supervisor` maps naturally onto the main agent session. |
| 3.9 | `human` checkpoints at `before_side_effects` — classify mutating tool calls and pause | M | 2.8 | `src/magent/hooks.py` already fires around tools and edits; that is the interception point. |
| 3.10 | `policy` switches: `on_expression_error`, `on_node_failure`, `on_unknown_field`, human timeouts, `checkpointing`, `resume` | S | 3.1 | |
| 3.11 | Desktop: graph plan view, live run view, approval inbox via `src/magent/desktop_api.py` | L | 2.10, 3.9 | The Command Center payoff. Coordinate with the Mag Command Center repo. |

**Exit:** the canonical `library-v1-release` example runs, taking the correct branch, with budgets
enforced and parallel tracks actually parallel. **Conformance level 2.**

---

### Phase 4 — Composition, judges, run records (AGS conformance level 3)

| # | Item | Effort | Depends on | Notes |
| --- | --- | --- | --- | --- |
| 4.1 | `loop` nodes: `while`/`until`/`repeat`, `max_iterations`, `carry`, `collect`, `on_max_iterations` | M | 3.3 | Recursive use of the same scheduler over the body fragment. Do not inline fragment nodes into the parent scope. |
| 4.2 | `map` nodes: `over`, `max_items`, `max_parallel`, `on_item_failure`, order-preserving `collect` | M | 3.6, 4.1 | `collect` gathers in **input** order regardless of completion order. |
| 4.3 | `subgraph` nodes: `use` (local fragment), `inline`, `ref` (another file) with `integrity` and `expected_id` verification | M | 4.1 | `parent_task_id` in `TaskRuntime` already gives the nesting tree. |
| 4.4 | `llm_judge` criteria: route by `judge_intelligence`, `samples` with median, evidence capture | M | 3.1, 2.6 | Do not judge with the same live session that produced the output without recording it. |
| 4.5 | `external` criteria registry, plugged into `src/magent/plugins.py` so plugin packs can register checkers | S | 4.4 | Natural fit for the existing extension-pack model. |
| 4.6 | `failure.compensation` — reverse-order undo on a failed run | M | 3.8 | Pairs well with the existing checkpoint/restore system (`src/magent/workbench_domains/checkpoints.py`). |
| 4.7 | AGS run records conforming to `agentic-graph-run-1.0.schema.json`, written to a `graph_runs` workbench collection | M | 2.4, 3.5 | Populate `attempt.routed` including `downgraded` — it is what explains quality differences between harnesses. Honor `redact: true`. |
| 4.8 | Resume: refuse when `graph_digest` no longer matches (`RT053`) unless forced | S | 4.7 | |
| 4.9 | **Retarget `goal_orchestrator.py` onto the graph runner**: `create_orchestrated_goal` emits an AGS document; `run_orchestrated_plan` becomes a thin wrapper over `agraph/execute.py` | L | 4.1, phase 3 | The de-duplication step from decision 0.1. Preserve the existing `magent goal --orchestrated` CLI surface and cache-key behavior so nothing user-visible breaks. |
| 4.10 | Recipe → fragment bridge: let `src/magent/recipes.py` recipes that are really DAGs export to a `subgraphs` fragment | M | 4.3 | Makes existing user recipes reusable inside graphs. |

**Exit:** all five spec examples execute. **Conformance level 3.**

---

### Phase 5 — Generating graphs (the second direction)

Accepting graphs is half the value. This half is what most users will actually touch.

| # | Item | Effort | Depends on | Notes |
| --- | --- | --- | --- | --- |
| 5.1 | `agraph/generate.py` skeleton pass: goal + project context → nodes, `depends_on`, `outputs` only, generated against the JSON Schema with constrained output | L | 1.4, 2.1 | Feed it `src/magent/project_scan.py` and `src/magent/repo_map.py` output, plus MagGraph recall — this is where persistent memory is a genuine differentiator over a stateless planner. |
| 5.2 | Specification pass, **per node**: given one node, generate `success.criteria`, `intelligence`, `requirements`, `constraints`, `failure`, `estimate` | L | 5.1 | Two passes are not optional. Single-pass generation of a 12-node graph reliably produces criteria like "the code works". Parallelize via `SubAgentRunner.spawn_parallel`. |
| 5.3 | Validate → repair loop: feed `{code, message, pointer}` findings back until clean under `--strict` or N attempts | M | 5.2, 1.4 | The advisory rules are the quality bar: `AG902` (side-effecting node with no criteria), `AG906` (only judged criteria), `AG904` (unread output), `AG905` (unjustified frontier tier). |
| 5.4 | Tier calibration: require `rationale` for `advanced`/`frontier`; check the histogram against the spec's guidance (≈1 frontier, 2–3 advanced in a 12-node graph) | S | 5.2 | Tier inflation is the most common generation failure. |
| 5.5 | CLI: `magent graph generate "<goal>" [--project .] [--out plan.agraph.yaml]` | S | 5.3 | |
| 5.6 | Approve-then-run flow: render the plan (Phase 1.7), let the user edit the YAML, re-validate, then run | M | 5.5, 2.10 | The point of the whole feature: the user approves the *plan*, not the output. |
| 5.7 | Learn from run records: feed `graph_runs` outcomes back so generation improves — which criteria kinds actually caught problems, which tiers were over- or under-specified | L | 4.7, 5.2 | Store the derived lessons in MagGraph. This is the compounding advantage MagAgent has that a stateless planner does not. |
| 5.8 | Export existing orchestrated plans to AGS: `magent plan export <plan-id> --format agraph` | M | 4.9 | Immediate portability for every plan a user already has. |

**Exit:** `magent graph generate "ship v2 of the API"` produces a graph that validates strictly,
reads sensibly to a human, and runs.

---

### Phase 6 — Ecosystem and polish

| # | Item | Effort | Depends on | Notes |
| --- | --- | --- | --- | --- |
| 6.1 | Ship an AGS **skill** under `src/magent/skills/` following the spec's `docs/skill-authoring.md`: `SKILL.md` under 300 lines, `reference/` for on-demand detail, templates, vendored validator | M | 1.6, 5.5 | `SkillRegistry` and `MAX_ACTIVE_SKILLS = 3` already support progressive disclosure. Gets AGS authoring into ordinary chat sessions without a CLI subcommand. |
| 6.2 | Plugin pack export so other harnesses can consume MagAgent's AGS support via `src/magent/plugins.py` / `plugin_sdk.py` | S | 6.1 | |
| 6.3 | Offline docs: an `agraph` topic in `src/magent/docs.py` so `magent docs agraph` works with no network | S | 2.10 | |
| 6.4 | Eval suite in `evals/`: generation quality, execution reliability, criteria-kind distribution, tier distribution | M | 5.4, 2.12 | Directly serves ROADMAP.md's "reliability is not yet measured end to end" gap. |
| 6.5 | Gateway support: submit a graph from Slack/Discord/Telegram and approve gates from chat via `src/magent/gateway/` | M | 3.9 | Human approval from chat is the natural home for `awaiting_human` with `on_timeout: hold`. |
| 6.6 | Daemon support: run graphs as background work through `src/magent/daemon.py` | M | 2.10 | Long graphs with day-scale approvals need this. |
| 6.7 | Publish MagAgent's conformance level and `supported_features` in `magent system info` | S | any level claim | Feeds the run record's `harness` block. |

---

## 4. Start here

The five items to do first, in order. Together roughly **two to three weeks**, and they produce
something shippable at the end of each.

1. **0.2 — Write down the tier → model-role mapping** (S).
   `minimal→cheap`, `standard→coding`, `advanced→coding`, `frontier→review`, plus an optional new
   `frontier` role. This is a docs-and-config change that unblocks all routing work and forces the
   one design decision people will argue about.

2. **1.1 + 1.2 — Loader and validation layers 1–2** (S + M).
   `agraph/document.py` and `agraph/validate.py`. Port from the spec repo's
   `tools/validate_agraph.py`. At the end of this you can tell a user their graph is wrong and
   exactly where.

3. **1.5 + 1.6 + 1.7 — Plan and render** (M + S + S).
   `magent graph plan` showing topological order, parallel groups, gates, tier histogram and
   projected cost. **Ship this.** It is conformance level 0, it is genuinely useful on its own, and
   it gives the Command Center something to draw.

4. **2.1 — Tier routing** (M).
   `agraph/routing.py` over `Config.provider_and_model_for_role()` and `model_capabilities()`.
   Small, self-contained, and the piece with no equivalent anywhere in MagAgent today.

5. **2.4 + 2.6 — Minimal executor** (L + M).
   Sequential `task` and `gate` nodes over `SubAgentRunner`, with `command` and `file_exists`
   criteria. Target: `magent graph run examples/minimal.agraph.yaml` green. That is conformance
   level 1 and the point at which the feature is real.

Deliberately **not** in the first five: loops, maps, subgraphs, judges, generation. Generation
(Phase 5) is the most exciting part and the most tempting to start with; doing it before the
validator exists produces graphs nobody can check.

---

## 5. Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| **Two orchestrators.** AGS execution lands beside `goal_orchestrator.py` and neither gets retired. | High. Duplicate semantics, doubled maintenance, worsens the concentrated-module problem ROADMAP.md flags. | Decide 0.1 up front. Commit to Phase 4.9 in the same release train as Phase 3. |
| **`cli/main.py` grows again.** | Medium. It is already 4,881 lines. | All graph commands go in `src/magent/cli/commands/graph.py`; `graph_app` registered in `cli/app.py`. No exceptions. |
| **`TaskRuntime` schema change breaks the desktop contract.** | Medium. `desktop_api.py` and Mag Command Center read task states. | Additive states only, bump `TASK_SCHEMA_VERSION`, keep `completed` as an alias of `succeeded` for one release, coordinate the Command Center release. |
| **Output reporting is unreliable.** Agents do not consistently report declared outputs. | High — it makes every node look like it failed. | Decide item 2.5 early and enforce it: one explicit tool, plus `path_hint` discovery as a fallback, plus a clear statement in the node prompt. |
| **Generation produces plausible but useless criteria.** | High. Judged-only success blocks make graphs unverifiable. | Two-pass generation (5.1/5.2), `--strict` repair loop (5.3), and track the criteria-kind distribution in the eval suite (6.4). |
| **Parallelism caps surprise users.** A graph asks for `max_parallel_nodes: 8`; config caps at 2. | Low but confusing. | Clamp, and say so in the run record and in `graph plan` output. |
| **Command criteria execute arbitrary shell from a submitted document.** | High if graphs are ever shared. | Run under existing `RiskTier` policy and sandbox; require explicit opt-in for command criteria from a graph the user did not author. Spec §22. |
| **Spec churn.** AGS 1.0 is a draft standard. | Low. | Pin `ags_version: "1.0"`; MINOR releases are additive by policy (spec §21). Track the spec repo's CHANGELOG. |

---

## 6. Definition of done

MagAgent can claim AGS support when all of the following hold:

- `magent graph validate` reproduces every diagnostic in the spec's `conformance/invalid/` fixtures.
- `magent graph plan` renders any valid document without executing anything.
- `magent graph run` executes all five spec examples, with criteria checked by the harness rather
  than asserted by the model.
- `magent graph generate` produces documents that pass `--strict` within three repair iterations for
  at least 80% of a ten-goal test corpus.
- Every run emits a record conforming to `agentic-graph-run-1.0.schema.json`, including
  `attempt.routed` with the effective tier and whether it was downgraded.
- `magent system info` reports the conformance level and feature list.
- `magent goal --orchestrated` runs on the graph engine, with no separate orchestrator remaining.
- Test coverage for `src/magent/agraph/` is at or above the repository floor, and the AGS eval suite
  runs in `evals/`.
