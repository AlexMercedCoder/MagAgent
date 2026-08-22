# Agentic Graphs

MagAgent implements Agentic Graph Specification (AGS) 1.0 conformance level 3. Graphs are portable JSON or YAML execution plans with typed inputs and outputs, deterministic dependency scheduling, model-tier routing, harness-checked success criteria, human gates, retries, budgets, and durable run records.

## Start

```bash
magent graph validate plan.agraph.yaml --strict
magent graph plan plan.agraph.yaml
magent graph run plan.agraph.yaml --project .
magent graph status <run-id> --json
magent graph resume <run-id>
```

Generate a conservative inspect, implement, and verify graph from a goal:

```bash
magent graph generate "repair the failing API tests" --project . --out repair.agraph.yaml
```

## Visual authoring and desktop contracts

Mag Command Center's Graph Board uses the same portable Graph Spec documents and these
machine-readable authoring commands:

```bash
magent graph schema --project .
magent graph inspect work.agraph.yaml
magent graph preview --input - --project .
magent graph apply work.agraph.yaml --input - --project . --expected-digest DIGEST
magent graph generate-draft "repair the tests" --project .
```

`preview` and `apply` read a JSON graph document from standard input. `apply` validates
strictly, confines writes to the active project, writes atomically, and rejects a stale
`--expected-digest` instead of overwriting a graph changed elsewhere.

Assign an Open Agent Profile to one node with the namespaced extension:

```yaml
nodes:
  review:
    type: task
    title: Review the implementation
    description: Review correctness, security, and test coverage.
    x-magagent-profile: review
```

MagAgent resolves the named profile for that node only. Its personality, provider, model,
tools, and effective permissions apply without widening harness policy. Unknown profiles
fail authoring validation and fail closed at runtime.

`magent graph plan ... --json` and `magent graph preview` return
`magent.graph-plan.v2`. Each job includes its dependencies, initial blocking reasons,
resolved provider/model route, and effective profile authority so a desktop can show what
will run before execution begins.

Generation takes a bounded project scan and token-limited repository map before writing per-node contracts. This keeps generated plans project-aware without embedding source files or spending provider quota merely to create the first reviewable draft.

Review or edit the generated document, validate it again, then run it. `--yes` approves every graph gate and checkpoint; omit it for interactive approval. Do not use `--yes` for an untrusted graph.

Release tests generate a fresh inspect, implement, and verify graph, require strict validation,
and execute it through the real dependency scheduler with deterministic node runners. CLI smoke
tests additionally cover generation, strict validation, planning, and dry-run execution. This
separates graph-runtime correctness from provider/model variability while exercising the same
executor used by live runs.

## Execution

- `minimal`, `standard`, `advanced`, and `frontier` intelligence tiers map to the `cheap`, `coding`, `coding`, and `frontier` model roles. If `frontier` is not configured, MagAgent uses `review`.
- A node receives only its declared logical tools. AGS tools map to MagAgent tools as documented by `magent system info`; undeclared tools fail with `RT012`.
- Graph permissions are a ceiling beneath the user's MagAgent permission policy. They never grant additional access.
- `graph_emit_output` is the reliable output contract. `path_hint` can discover a file after the node returns.
- `before_start`, `before_side_effects`, and `after_outputs` checkpoints are enforced by the harness. A required checkpoint that cannot be displayed fails with `RT015`.
- `shared`, `worktree`, and copied `sandbox` workspaces are supported. Unsupported or unavailable isolation fails with `RT014`; MagAgent does not silently downgrade it. Container-isolated agent sessions are currently refused.
- Resume reuses completed node outputs only when the canonical graph digest matches. Use `--force` only after reviewing graph changes.
- `magent graph resume RUN_ID --retry-nodes implement,verify` reruns the selected jobs and every downstream dependent while retaining unaffected successful work.

## Live status and terminal results

Use `magent graph run ... --jsonl` for `magent.graph-event.v1` lifecycle events. Jobs emit
queued, started, and completed events with stable state, dependency, profile, summary,
error-code, changed-file, and blocker fields. The final line is a
`magent.graph-result.v1` envelope, and the process exits nonzero when any job fails or is
blocked.

`magent graph status RUN_ID --json` returns a reconnectable `magent.graph-status.v1`
snapshot reconstructed from the durable graph task and its child job tasks. Terminal jobs
retain a concise success, failure, skip, or blocker summary. `--jsonl` replays persisted
graph boundary events for log-oriented clients.

Core logical mappings include `file_read` to bounded file readers, `file_write` to file editing tools, `shell_exec` to `run_shell`, `web_search` to search/research, both `web_fetch` and `http_fetch` to URL fetch tools, `browser` to browser automation, and `image`/`document` to artifact creation tools. `magent system info` is the machine-readable source of truth for the complete mapping.

## Safety

Treat graph files as executable workflow definitions. Review requested tools, permissions, command criteria, network access, secrets, isolation, and human gates before execution. Secret values never belong in graph expressions or run records. Graph-declared secret names resolve from the process environment and are never inserted into prompts by the graph runtime.

Portable run records conform to `agentic-graph-run-1.0.schema.json` and include routing, attempts, criteria evidence, node state, edge decisions, human events, resource usage, and diagnostics. They are stored in the user's `graph_runs` workbench collection.

## Integration

- `magent goal --orchestrated` uses the same graph executor rather than a second orchestration engine.
- Recipes can export AGS fragments with `magent graph export-recipe`.
- Existing plans can export with `magent graph export-plan`.
- `magent daemon enqueue agraph <path>` runs a graph as durable background work.
- Gateways accept `/graph validate`, `/graph plan`, and `/graph run` commands scoped to their configured project.
- `magent graph export-plugin` packages the schemas and bundled authoring skill for another installation.

Examples live under `docs/examples/agraph/`, including release preparation, bug triage, documentation audit, loops, maps, branching, and subgraphs. Tests strictly validate every example and structurally execute every packaged YAML graph through the real scheduler without provider calls or side effects.
