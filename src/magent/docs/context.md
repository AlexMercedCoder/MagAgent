# Context Map

`magent context map` answers a practical question: what does MagAgent know about this project right now?

It combines four local sources:

- MagGraph memory stats and optional recall
- workbench tasks, plans, patches, reviews, and failed commands
- project command roles and project doctor output
- memory-promotion candidates derived from workbench state

## Usage

```bash
magent context map
magent context map --project /path/to/repo
magent context map --query "release workflow"
magent context map --json
```

By default, the CLI renders a compact terminal briefing with tables for workspace
signals, active plans, memory candidates, and optional recall. Use `--json` when
a desktop app, script, or debugging session needs the full structured payload.
Use `--query` when you want the context map to include a compact memory recall
result for the topic you are about to work on.

## Memory Promotion

`magent memory promote` lists workbench records that are good candidates for durable memory.

```bash
magent memory promote
magent memory promote task task_0001
magent memory promote --all
```

Promotion writes selected candidates into MagGraph using the same memory manager as normal agent sessions. This keeps operational records in the workbench until you decide they are important enough to become long-term knowledge.

After promotion, MagAgent asks MagGraph for `changed_since` entries so callers can update memory views from the change feed instead of rescanning the full graph.

Good promotion candidates include:

- project command profiles
- open tasks worth remembering
- pending, failed, or executable plans worth remembering
- repeated command failure patterns
- saved review findings

## Design Boundary

The context map keeps MagAgent's local layers distinct:

- **MagGraph** stores durable semantic memory.
- **Workbench JSON** stores operational session and project state.
- **Code/test indexes** store current repository navigation hints.

Promotion is the explicit bridge from temporary operational state into durable memory.
