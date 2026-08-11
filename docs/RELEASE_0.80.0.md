# MagAgent 0.80.0 Release Record

MagAgent 0.80.0 focuses on memory quality, visible progress, task recovery, desktop
contracts, and measurable local performance.

## Release Scope

- thresholded memory retrieval quality evaluations and a reproducible fixture graph
- scope and provenance preservation in explainable recall results
- backlink-aware terminal and desktop recall explanations
- model and tool liveness heartbeats with stable activity events
- interactive durable-task recovery and spend visibility
- quick and 10,000-event release performance budgets

## Required Evidence

The release requires a passing full test suite, branch-coverage floor, lint, typing,
documentation drift, deterministic agent evaluations, memory quality gates, local
performance budgets, security assurance, exact-wheel checks, secret scanning, and
Linux/macOS/Windows packaged acceptance.

Credentialed provider qualification remains separate from deterministic local release
evidence. Provider support tiers and evidence dates remain visible through
`magent provider matrix` and `magent provider support-report`.

The complete local suite passes 785 tests at 67% branch-aware coverage. The enforced
coverage floor is raised from 64% to 67%. The deterministic memory fixture passes every
configured quality gate, and the 10,000-event performance profile passes every local budget
on the documented release machine.

## Compatibility

Existing simple memory eval files remain valid. The report schema is now
`magent.memory-eval.v2`; new thresholds and labels are opt-in. Desktop recall packets use
`magent.memory-recall.v2`. Stable task and task-event contracts are unchanged.
