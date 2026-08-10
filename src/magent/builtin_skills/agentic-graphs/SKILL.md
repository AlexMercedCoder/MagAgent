---
name: agentic-graphs
description: Author, validate, review, and execute portable Agentic Graph Specification 1.0 plans.
version: "1.0"
tools_required: [file_read, file_write]
trigger_keywords: [agentic graph, agraph, execution graph, portable plan, DAG workflow]
---

# Agentic Graphs

Use this skill when a user asks to create, inspect, validate, or run an Agentic Graph.

## Workflow

1. Decide whether the goal benefits from a reviewable DAG. Small one-step requests do not.
2. Generate a graph with `magent graph generate "<goal>" --out plan.agraph.yaml` or author YAML directly.
3. Run `magent graph validate plan.agraph.yaml --strict`.
4. Run `magent graph plan plan.agraph.yaml` and review tiers, gates, cost, and fan-out.
5. Edit the document if needed, then run it with `magent graph run plan.agraph.yaml`.

## Authoring Rules

- Use `ags_version: "1.0"` and `kind: AgenticGraph`.
- Keep the effective edge set acyclic. Use `loop` and `map` nodes for bounded repetition.
- Give every task a focused title, concrete description, declared outputs, constraints, and machine-checkable success criteria.
- Use logical tool names such as `file_read`, `file_search`, `file_write`, `shell_exec`, `web_search`, and `web_fetch`.
- Never put secret values in a graph. Declare only secret names and let the harness resolve them out of band.
- Prefer deterministic criteria: `command`, `file_exists`, `artifact_present`, `expression`, `regex`, and `json_schema`.
- Use `llm_judge` only when deterministic checks cannot evaluate quality, and pair it with deterministic evidence.
- Add a rationale for `advanced` and `frontier` tiers. Keep high tiers scarce.
- Bound retries, loops, maps, wall-clock time, cost, and node executions.
- Human gates must fail or hold when no approval channel is available; never silently approve them.

## Output Contract

During node execution, emit every declared output with `graph_emit_output(name, value)`. A final JSON object and `path_hint` discovery are fallbacks, not the primary contract.

## Tier Mapping

| AGS tier | MagAgent role |
| --- | --- |
| `minimal` | `cheap` |
| `standard` | `coding` |
| `advanced` | `coding` |
| `frontier` | `frontier`, falling back to `review` when unset |

Read `reference/authoring.md` for node types, criteria, and CLI details when more context is needed.
