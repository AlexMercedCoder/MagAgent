# Architecture Exceptions

The 0.60 size budget permits a module over roughly 1,000 lines only when the compatibility reason and extraction condition are documented.

## `magent.cli.main` (closed in 1.4)

Closed: `main.py` now contains only composition, the root callback and command-module imports. Commands moved to `magent.cli.commands.*` and shared helpers to `magent.cli.shared`, with a golden contract test proving the CLI surface did not change. The module also passes mypy now.


## `magent.workbench`

This remains a compatibility facade for downstream imports accumulated before domain modules existed. `workbench_domains.*` are stable import targets, and dependency tests prevent presentation-layer ownership. New domain behavior must begin in a focused domain module and be re-exported. The exception closes when plans, project, code intelligence, patches, checkpoints, and release implementations are physically owned by those modules.

## `magent.agraph.execute`

The graph executor is a cohesive portable specification interpreter with tightly coupled scheduling, recovery, criteria, and run-record invariants. Splitting it during the LSP/runtime milestone would increase change risk. New helpers should move to existing `agraph` modules when independently testable. The exception closes when execution phases have explicit typed protocols that preserve AGS conformance fixtures.
