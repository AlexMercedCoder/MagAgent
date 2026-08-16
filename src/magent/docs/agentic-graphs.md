# Agentic Graphs

MagAgent implements Agentic Graph Specification (AGS) 1.0 conformance level 3. Graphs are portable JSON or YAML execution plans with typed inputs and outputs, deterministic dependency scheduling, model-tier routing, harness-checked success criteria, human gates, retries, budgets, and durable run records.

## Start

```bash
magent graph validate plan.agraph.yaml --strict
magent graph plan plan.agraph.yaml
magent graph run plan.agraph.yaml --project .
magent graph status <run-id>
magent graph resume <run-id>
```

Generate a conservative inspect, implement, and verify graph from a goal:

```bash
magent graph generate "repair the failing API tests" --project . --out repair.agraph.yaml
```

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
