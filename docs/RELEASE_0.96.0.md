# MagAgent 0.96.0

MagAgent 0.96.0 completes the machine and runtime contracts required by Mag Command Center's full Graph Board.

- `magent.agentic-graph-authoring.v2` exposes strictly valid templates for all AGS node types and trusted plugin graph templates.
- New JSON-stdin commands perform reference-aware node rename, duplication, model-backed generation, strict repair, and reviewable change summaries.
- Graph runs can attach to an existing durable task, publish node IDs on child tasks, honor pause and cancellation at safe boundaries, and resume through the original digest-guarded run record.
- Selective gate approval replaces blanket desktop approval.
- Run records retain both the graph digest and an immutable graph snapshot.
- `magent.graph-event.v1` JSONL streams card lifecycle updates and `magent.graph-result.v1` closes every run with deterministic exit semantics.
- `magent.graph-status.v1` reconstructs the three-column board after a desktop reconnect, including dependency blockers, summaries, error codes, and changed files.
- `magent.graph-plan.v2` previews every job's dependencies, route, and resolved Open Agent Profile authority.
- Selective retry reruns failed jobs and their downstream dependents without discarding unaffected successes.

Release qualification requires the full graph, CLI, lint, packaging, and Mag Command Center contract suites.
