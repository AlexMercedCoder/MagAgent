# MagAgent 0.60.0 Release Record

## Scope

0.60.0 makes the runtime easier to reason about, introduces genuine local LSP code intelligence, tightens the type gate, and reduces the default installation shape.

## Runtime And Contracts

- Split `AgentSession` into typed context, tool-loop, lifecycle, and support modules while preserving the public facade.
- Reduced `agent.py` from 1,769 lines to under 400; no extracted runtime module exceeds 1,000 lines.
- Enabled `check_untyped_defs` and removed agent, memory, tool executor, daemon, gateway router, graph executor, and MCP bridge exemptions. All 173 source modules pass mypy.
- Added typed runtime boundary records, stable task/event contract fixtures, and dependency-direction tests.
- Extracted tool capability commands from `cli.main` and documented remaining compatibility-facade exceptions.

## Code Intelligence

- Added a framed JSON-RPC LSP client with process lifecycle, initialization, capabilities, document sync, cancellation, timeouts, server requests, restart, and clean shutdown.
- Added real definitions, references, symbols, diagnostics, hover, and rename for installed Python, TypeScript/JavaScript, Rust, and Go servers.
- Kept bounded and accurately labeled AST/text fallbacks.
- Added deterministic protocol tests and real Python/TypeScript server integration tests in CI.
- Bounded diagnostics to one server per language and one collection window per workspace.

## Installation And Performance

- Moved document, media, desktop, browser, gateway, MCP, and Python LSP dependencies into optional extras.
- Added `mag-agent[full]`, `magent tools doctor`, and `magent performance install-shape`.
- Added actionable install hints and a fresh core-wheel CI smoke test.
- Added a no-hook fast path that avoids unnecessary thread-executor startup on every tool call.
- Reduced a clean Python 3.14 core environment from 403,485,284 bytes to 296,012,278 bytes (26.6%) and from 106 to 76 installed distributions.
- Improved average cold `magent.cli.main` import time from 388.92 ms to 306.91 ms (21.1%) across five subprocess samples.
- Verified both the core wheel and `mag-agent[full]`; the full environment imports all 18 optional capability modules and `magent tools doctor` reports all seven packs ready.

## Validation

- Extracted runtime branch coverage: 86.4%.
- Context runtime: 94%; lifecycle runtime: 90%.
- Real LSP round trips pass with `pylsp` and `typescript-language-server`.
- 755 unit tests and 5 integration tests pass on Python 3.14.5.
- Branch-aware package coverage is 67.45% against the retained 64% regression floor.
- The deterministic AgentSession suite passes 32/32 tasks and 20/20 artifact tasks.
- Ruff, mypy across 173 source modules, documentation drift, sdist/wheel metadata, core/full clean installs, and Twine checks pass.

Machine-readable evidence is committed at:

- `docs/reports/0.60.0-agent-evals.json`
- `docs/reports/0.60.0-install-shape.json`
- `docs/reports/0.60.0-release-evidence.json`

## Compatibility

- Python 3.11 through 3.14 remain supported.
- MagGraph 0.4.x remains the supported memory family; `maggraph>=0.4.1` is required.
- Stable task and task-event schemas remain `magent.task.v2` and `magent.task-event.v1`.
- Existing `AgentSession`, CLI, machine API, plugin, MCP, and desktop integration surfaces remain compatible.
