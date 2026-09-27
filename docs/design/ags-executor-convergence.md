# AGS Executor Convergence

Status: design note, for decision. No code changes are proposed in this document.
Date: 2026-09-27. Scope: the Agentic Graph Specification (AGS) 1.0 executors in
`Loro/src/loro/agraph` (Loro 0.21 line) and `MagAgent/src/magent/agraph` (MagAgent 1.4.0 line).

## Question

Loro and MagAgent each run AGS 1.0 graphs at conformance level 3. Should they share one executor
package, and if so, what would it contain and what would moving to it cost?

## Recommendation (short version)

Do not build a shared executor now. Converge in three smaller steps instead:

1. Move the **pure, normative pieces** into the `agentic-graph-spec` support library (`ags`),
   which both harnesses already depend on: an AGX **evaluator** next to the existing AGX
   parser, edge activation and node readiness, and a run-record builder.
2. Add a **behavioural conformance suite** to that library for what the current fixtures do not
   pin down: resume, budgets, gate timeouts, retries and fallbacks.
3. Reconcile the **semantic divergences** listed below in each harness, one at a time.

Revisit a shared executor only after both harnesses sit behind the same small set of host
interfaces. The reasons are in "Why not a shared executor yet".

## What exists today

Both harnesses validate with the `ags` reference validator, compute RFC 8785 digests with
`ags.graph_digest`, validate run records against the same `agentic-graph-run-1.0` schema, and
publish level-3 conformance results at the same fixture revision
(`f180a4dbd07911f90dd0821f531d7ccd51bb0764`: Loro in `docs/ags-conformance.json`, 2026-09-12;
MagAgent in `docs/ags-conformance.json`, 2026-09-27). Everything above validation is separate
code.

| Area | Loro (`src/loro/agraph`) | MagAgent (`src/magent/agraph`) |
| --- | --- | --- |
| Size | about 3,300 lines, `execute.py` 1,242 | about 5,100 lines, `execute.py` 2,180 |
| Concurrency model | synchronous; `ThreadPoolExecutor` for ready nodes and map fan-out | `asyncio`; `Semaphore` and `gather`, `ContextVar` for per-node state |
| Node agent | `AgentRuntime` built by a `RuntimeFactory` from a routed `LoroConfig` | `agent_runner(node_id, prompt, route, task_id)` coroutine over the MagAgent agent loop |
| AGX evaluator | own, 404 lines (`expressions.py`) | own, 349 lines (`expressions.py`) |
| AGX functions | `all any contains count default endswith in join len lower matches not split startswith trim upper` | the same sixteen |
| Criterion kinds | `command file_exists artifact_present json_schema regex expression human external llm_judge` | the same nine |
| Routing | tiers with downgrade and credential references (`routing.py`) | tiers with refusal before spending (`routing.py`) |
| Graph-level policy | `evaluate_policy` against `[agraph]` config, codes `LP001`-`LP010` | `_preflight`, strict-mode findings such as `AG908` (no cost cap) |
| Starting a run | refuses unless the plan (by digest) is approved: `plan_approved` | `--expected-digest` pin; per-action approvals during the run |
| Unenforced fields | reported as `AG901` warnings (`support.py`): gate timeouts, `on_reject`, `on_expression_error`, `map.max_parallel`, `failure.escalation`, `success.evaluation_order` | gate `timeout_seconds`/`on_timeout`/`on_reject`, `on_expression_error: skip_node`, `failure.escalation` and map `max_parallel` are applied; no `AG901`-style report |
| Retries | `failure.retry.max_attempts` by failure class, no delay | same, plus backoff delay (`_retry_delay`) |
| Fallback and compensation | `alternate_node`, compensation on failure | `alternate_node` with recursion guard, compensation on failure |
| Human checkpoints | `before_start`, `before_side_effects` through a `GateProvider` | same points, through the permission prompt, AAIS approvals or `--approve-gates` |
| Run storage | `GraphRunStore`: atomic files, size cap, data-protection redaction | `WorkbenchStore` collection `graph_runs`, status snapshots for desktop reconnection (`status.py`) |
| Node records | keyed by node id while running, list when saved | list with `scope_path`, so nested loop, map and subgraph nodes resume individually |
| Resume | refuses when any node is `running` (uncertain effects) unless `--force`; a changed digest needs `--force` plus approval; redacted params must be supplied again | reuses succeeded nodes whose outputs are not redacted; a changed digest needs `--force` (`RT053`); `retry_nodes` invalidates dependants; `policy.resume: restart` |
| Events | `event_handler(type, payload)` plus audit log | versioned graph event schema (`events.py`) for CLI JSONL and the desktop app |
| Host integration | Loro approvals, permissions engine, identity, audit, skills | MagAgent task runtime, AAIS approval broker, sandboxed graph workspace, per-node tool policy (`runtime_context.py`) |
| Extensions honoured | `x-agent-profile` (per-node Open Agent Profile) | `x-magagent-profile` (same purpose), `x-magagent-executor` (MCP/A2A nodes, experimental) |
| Generation and authoring | goal-to-graph generation (`generate.py`, 406 lines) | generation (`generate.py`) plus desktop authoring contracts (`authoring.py`) |
| Runtime error codes | `RT011`, `RT021`, `RT031` | `RT001`-`RT054` (about 25 distinct codes) |

## Divergences that matter

These are cases where the same graph can behave differently, or where a user moving between the
tools would be surprised. None are conformance failures today: the level-3 fixtures do not cover
them.

1. **Resume after a crash mid-node.** Loro refuses to resume while a node is recorded as
   `running`, because its side effects are unknown. MagAgent re-runs any node that did not
   succeed, so a side-effecting node can run twice (at-least-once). Loro's guard is the safer
   default.
2. **Redacted parameters on resume.** Both harnesses write secrets into saved run records as
   a marker and must not feed the marker back into a resumed run. MagAgent (fixed in G-14)
   replaces declared-secret values with `[REDACTED]` anywhere in the record; `graph resume`
   takes the real values again (`--param`, `--params`, `--param-file`, or a hidden prompt),
   stops naming them otherwise, and the executor refuses any parameter that *contains* the
   marker (`RT055`). Loro requires `--params` and refuses to resume when a saved parameter
   *equals* `[redacted]`. Two gaps there, from reading `loro/agraph/execute.py` and
   `loro/data_protection.py`: the marker is set only for params whose spec has `redact: true`,
   which the AGS 1.0 `param_spec` schema does not allow (so valid graphs never set it this
   way); and the run store's data-protection pass can redact part of a value (a token inside a
   longer string), which an equality check does not catch. The markers also differ in case
   (`[redacted]` and `[REDACTED]`). A shared rule: one marker, a containment check, and a
   list of the parameters to re-supply.
3. **Plan approval.** Loro makes approval of the graph digest a precondition of every real run.
   MagAgent treats the digest pin as optional and relies on per-action approvals. Both are
   defensible; the spec could name the two models so graphs and UIs can say which they need.
4. **Declared but unenforced fields.** Loro enforces fewer optional fields but says so with
   `AG901`. MagAgent enforces more of them but has no equivalent report for what it ignores
   (for example `success.evaluation_order`). The honest-diagnostics idea should be shared.
5. **Per-node profile extension.** `x-agent-profile` in Loro and `x-magagent-profile` in
   MagAgent mean the same thing. A graph written for one silently ignores the other's key. A
   single `x-oap-profile` (or a spec field in a later AGS minor version) would fix this.
6. **Error codes.** Runtime failures are coded differently (`RT011` in both means a routing
   refusal; most other codes exist in only one harness). Records are schema-valid either way,
   but tools that read records across harnesses cannot rely on codes.
7. **Retry timing.** MagAgent waits between attempts; Loro retries immediately. Rate-limited
   providers make this visible.
8. **Map fan-out.** MagAgent honours `map.max_parallel`; Loro uses its graph-wide limit and
   warns. Throughput and provider load differ for the same graph.

## What a shared package would look like

If the harnesses later converge on one executor, the boundary that falls out of the comparison
is a pure core plus host ports.

**Core (host independent, no I/O):**

- AGX parsing and evaluation, template interpolation.
- Plan building, topological order, edge activation, readiness, skip propagation.
- Node-state machine: pending, running, succeeded, failed, skipped, blocked, cancelled,
  awaiting human; retry and fallback decisions; loop and map bookkeeping; budget accounting.
- Criterion dispatch with the pure kinds built in (`expression`, `regex`, `json_schema`,
  `file_exists` over a supplied filesystem view) and the rest delegated to ports.
- Run-record building, redaction markers, resume planning (which nodes to reuse, which are
  uncertain), and one runtime error-code registry.

**Ports (each harness implements them):**

| Port | Loro today | MagAgent today |
| --- | --- | --- |
| `NodeRunner.run(node, prompt, route)` | `RuntimeFactory` plus `AgentRuntime` | `agent_runner` coroutine |
| `Approvals.request(action)` | `ApprovalManager`, `approval_provider` | AAIS broker, `permission_prompt` |
| `Gates.ask(node, checkpoint)` | `GateProvider` | permission prompt, `--approve-gates` |
| `Criteria.command/judge/external` | `CriteriaEvaluator` methods | `_run_command_criterion`, `_judge`, plugin checkers |
| `Router.route(node)` | `route_model` | `route_for_node` |
| `RunStore.save/get` | `GraphRunStore` | `WorkbenchStore` plus status snapshots |
| `Events.emit(type, payload)` | `event_handler` plus audit | graph event schema |
| `Executors[x-...]` | none | `x-magagent-executor` |

The core would be written async-first, with a thin synchronous adapter for Loro (run the event
loop in the calling thread, keep thread pools inside Loro's `NodeRunner`).

**Where it would live.** The pure pieces that define AGS semantics (AGX evaluation, edge
activation, readiness, record building) belong in the `ags` support library, which already
ships the AGX parser and the schemas. A full executor with ports should be a separate package
(for example `ags-runtime`) so the spec library does not have to release every time runtime
behaviour changes. The spec documents themselves would not change.

## Migration cost (estimates, not measurements)

| Step | Loro | MagAgent | Risk |
| --- | --- | --- | --- |
| AGX evaluator from `ags` | replace about 400 lines; keep strict typing errors | replace about 350 lines | low: same function set; differences would show up as test failures |
| Readiness and edge activation from `ags` | `schedule.py`, part of `plan.py` | `schedule.py`, part of `plan.py` | low to medium: skip propagation details differ |
| Behavioural conformance suite | new tests, some expected to fail first | same | low: tests only |
| Reconcile divergences 1-8 | resume params, retry delay, `map.max_parallel`, codes | uncertain-node guard, `AG901`-style report, codes | medium: user-visible behaviour changes, need changelog and docs |
| Full shared executor | rewrite `execute.py` onto ports, sync adapter; about 1,200 lines touched | rewrite `execute.py` onto ports; about 2,200 lines touched, desktop events and task runtime rewired | high: both are the most tested and most used parts of each harness |

The first three rows are days of work each; the last row is weeks per harness plus a period of
running both executors side by side.

## Why not a shared executor yet

- **Most of each `execute.py` is host glue.** Approvals, task runtime, permissions, audit,
  identity, sandboxes and desktop events account for most of the lines, and they differ by
  design. Sharing the remaining scheduler would not remove much code from either harness.
- **Different concurrency models.** Loro is synchronous with threads; MagAgent is `asyncio`
  with context variables. A shared core forces one model on the other harness's hot path.
- **The semantics are not settled.** The divergences above are exactly the places a shared
  executor would have to pick a winner. Settling them first, in the spec's conformance suite,
  makes the later extraction mechanical instead of contentious.
- **The biggest duplication is already the cheapest to remove.** Two AGX evaluators with the
  same sixteen functions are the clearest conformance risk (a subtle difference changes which
  edge a graph takes). Moving that one piece into `ags` captures most of the benefit.

## Proposed next steps

1. Propose `ags.agx.evaluate` (and interpolation) for the support library, with the union of
   both harnesses' expression tests as its test suite.
2. Draft behavioural conformance fixtures for resume (uncertain nodes, redacted params, digest
   change), retries, gate timeouts and `map.max_parallel`.
3. Agree one per-node profile extension key and a shared runtime error-code table.
4. In MagAgent: add an uncertain-node resume guard and an `AG901`-style report for fields it
   does not enforce. In Loro: retry backoff and `map.max_parallel`.
5. Re-run this comparison after steps 1-4 and decide on the full executor then.
