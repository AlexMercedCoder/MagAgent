# Architecture Exceptions

The 0.60 size budget permits a module over roughly 1,000 lines only when the compatibility reason and extraction condition are documented.

## `magent.cli.main`

This remains a large compatibility facade because the public console entry point, interactive chat loop, and older top-level command callbacks share closure-based Typer registration. Focused groups already live in `magent.cli.commands.*`; 0.60 also extracts tool capability commands. New command behavior may not be added directly unless it is inseparable from the interactive root loop. The exception closes when remaining legacy groups use injected registration modules and `main.py` contains only composition, root callbacks, and interactive entry points.

## `magent.workbench`

This remains a compatibility facade for downstream imports accumulated before domain modules existed. `workbench_domains.*` are stable import targets, and dependency tests prevent presentation-layer ownership. New domain behavior must begin in a focused domain module and be re-exported. The exception closes when plans, project, code intelligence, patches, checkpoints, and release implementations are physically owned by those modules.

## `magent.agraph.execute`

The graph executor is a cohesive portable specification interpreter with tightly coupled scheduling, recovery, criteria, and run-record invariants. Splitting it during the LSP/runtime milestone would increase change risk. New helpers should move to existing `agraph` modules when independently testable. The exception closes when execution phases have explicit typed protocols that preserve AGS conformance fixtures.
