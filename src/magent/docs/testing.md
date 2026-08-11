# Testing And Reliability

Agentic Graph coverage includes the upstream invalid conformance fixtures, strict validation of every packaged example, provider-free structural execution of every packaged YAML graph, strict expressions and lazy defaults, deterministic plans, routing, decision outputs, checkpoints, permissions, isolation refusal, branching, loops, maps, subgraphs, resume digest guards, measured budgets, and portable run-record schema validation. Run it directly with `pytest -q tests/unit/test_agraph.py`.

MagAgent uses focused unit tests plus CLI smoke tests to keep local agent workflows reliable.
The CI coverage gate is ratcheted to the measured unit-suite floor so it catches
regressions without overstating the current full-package percentage.

Recommended local checks:

```bash
python -m pytest -q
python -m ruff check src tests
python -m pytest tests/unit --cov=magent --cov-report=term-missing:skip-covered
magent docs doctor
magent eval run evals/reliability-offline.json --report-out agent-eval-report.json
magent readiness
magent provider test-matrix
magent provider tool-smoke <provider> --model <cheap-model>
```

Pytest is configured with `src/` first on its import path, and the suite refuses to
start if it resolves `magent` from a globally installed package instead of the current
checkout. This keeps local coverage and release validation tied to the code under
review without requiring developers to alter their global MagAgent installation.

Resource warnings and pytest unraisable-exception warnings are errors. Cached user
database connections are closed after every test, while production processes register
the same cleanup for shutdown. Semantic-memory SQLite operations use short-lived,
transactional connections that always release their file handles.

The 0.80.0 baseline is 785 passing tests with 67% branch-aware coverage. The configured
floor is ratcheted from 64% to 67% for this release. The earlier roadmap's 72% overall target
remains unmet and visible; the release does not disguise that gap by changing the historical
target.
Current high-risk module evidence includes provider requests at 92%, persistence at 88%,
network policy at 87%, permissions at 84%, and gateway routing and artifact execution at 76%.
The next coverage work should close those focused gaps before broad CLI line coverage.

High-confidence coverage focuses on:

- agent loop tool dispatch and provider failure handling
- workbench plans, checkpoints, code/test intelligence, and reviews
- memory quality controls and semantic memory
- provider routing and config loading
- SQLite data tools and tool result shaping
- system, clipboard, notification, image-inspection, and archive safety contracts
- packaged docs coverage and local UI endpoints
- terminal UI rendering and streaming behavior
- context maps and explicit workbench-to-memory promotion
- non-interactive ask audits and provider tool-use smoke checks
- opt-in orchestrated goal plan creation, dry-run preview, retry/resume, background queueing, model-role diagnostics, and sub-agent step packet contracts
- isolated AgentSession task execution, independent artifact validators, per-task fault containment, and release evidence assembly
- thresholded memory ranking, stale/contradiction avoidance, scope, provenance, backlink, explanation, and token-budget gates
- model/tool liveness heartbeats, four concurrent task writers, and 10,000-event performance budgets

CI installs the MCP extra, runs the MCP integration fixtures, and uploads the deterministic
real-agent eval report. Credentialed Nous Portal qualification runs in the separate scheduled
or manually dispatched `Provider Qualification` workflow when its repository secret is set.

Use `magent test explain <file>` when targeted test selection is surprising. Use
`magent plan-apply --dry-run <plan-id>` before executing buffered plan operations.

One-shot tasks are non-interactive by default. If a tool action needs a prompt,
the tool returns `permission_required` and the final response includes a task
audit warning. Use `magent ask --yes` only for trusted local tasks where
YOLO-style approval is acceptable.

Use `magent provider test-matrix` to verify lightweight provider pings, then
`magent provider tool-smoke` for the more realistic check that a configured
provider can perform a minimal tool call and create `smoke.txt`.
Generate the static release artifact with `magent provider support-report -o
provider-support.json`. It records provider IDs, adapters, credential variable names,
and conformance state, never credential values. Full-support release qualification
still requires maintainer-run completion and tool-use checks for that release.
Use `magent provider models <provider> --refresh` when a provider changes model
IDs, and `magent model health` to review recent smoke outcomes.

For release readiness, run `magent release check`. For scriptable reviews, use
`magent review --fail-on P1`.
For a cross-project artifact, run `magent system ecosystem-report --root <workspace>
--output ecosystem-readiness.json`; review every `external_gates` entry separately.

Use `magent ui` for a live read-only view of workspace status, project doctor,
patches, checkpoints, memory quality, docs search, and release checks while
running local verification.
