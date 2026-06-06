# Architecture

MagAgent is organized around four local layers. Keeping these layers distinct makes future feature work easier to reason about and keeps MagGraph focused on durable memory rather than operational bookkeeping.

## Layers

### CLI And TUI

`magent.cli.app` composes the Typer app and command groups. `magent.cli.main` imports that app and owns command implementations, callbacks, and interactive session entry points. `magent.tui` owns Rich rendering helpers such as the startup banner, response panels, status lines, and streaming output.

Future command modules should register command groups from `magent.cli.commands.*` while preserving `magent.cli.main:app` as the console entry point.

`magent.cli.command_context` owns reusable command helpers such as current-user lookup, store creation, provider construction, and command-tree introspection. New command modules should depend on this helper layer instead of copying setup code.

### Agent Runtime

`magent.agent` coordinates provider calls, memory recall, tool dispatch, checkpoints, and memory writes for interactive and one-shot sessions.

The agent should depend on stable facades:

- `magent.memory.MemoryManager`
- `magent.tools.ToolExecutor`
- `magent.workbench` public helpers
- `magent.context` context-map and promotion helpers

### Memory

`magent.memory` is the MagGraph-backed long-term memory layer. It stores durable knowledge: preferences, project facts, recurring patterns, session summaries, bookmarks, and other facts worth recalling across sessions.

Semantic search and memory quality tools live alongside this layer because they operate on MagGraph nodes.

### Workbench

Workbench state is local operational state: tasks, artifacts, project profiles, plans, reviews, patches, checkpoints, command history, release checks, dashboards, and docs helpers.

`magent.workbench_store` owns the JSON-backed storage primitive. `magent.workbench` remains the compatibility facade for workbench functions. New workbench domains should move toward focused modules while being re-exported from `magent.workbench`.

`magent.workbench_domains.*` exposes domain-specific import modules for plans, patches, checkpoints, project helpers, code/test intelligence, and release/workspace helpers. These modules currently preserve compatibility while providing stable targets for future extraction.

### Context

`magent.context` bridges memory and workbench state. It answers "what does MagAgent know right now?" and promotes selected workbench facts into durable MagGraph memory.

Promotion is intentionally explicit:

- workbench records are temporary operational state
- MagGraph nodes are durable semantic memory
- `magent memory promote` is the bridge between them

### Tools

`magent.tools` is the public tool API. The implementation lives in `magent.tools.executor`, and the package initializer re-exports `ToolExecutor` for compatibility.

Shared tool support code lives in:

- `magent.tools.types` for `ToolResult` and tool budgets
- `magent.tools.registry` for OpenAI-compatible tool schema helpers
- `magent.tools.archive` for archive extraction safety

Future tool modules should split by capability:

- file and archive tools
- shell and process tools
- web and HTTP tools
- data and document tools
- registry/schema helpers

## Compatibility Rule

Public imports should remain stable unless a major version explicitly changes them:

```python
from magent.tools import ToolExecutor
from magent.workbench import WorkbenchStore
from magent.workbench import task_add
from magent.workbench_domains.plans import save_plan
```

When internals move, add compatibility tests before refactoring. This protects downstream users and keeps releases patch-safe.

## Refactor Order

The safest future order is:

1. Move CLI command groups into focused registration modules that use `magent.cli.command_context`.
2. Continue extracting `magent.workbench` domains behind the existing facade and domain modules.
3. Split `magent.tools.executor` by capability while keeping `ToolExecutor` public.
4. Add architecture docs whenever module boundaries change.
