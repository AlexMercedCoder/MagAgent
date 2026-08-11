# MagAgent 0.91.0 Release Record

MagAgent 0.91.0 is a focused release-candidate hardening pass. It improves provider
qualification correctness, clean-wheel acceptance, persistence coverage, and durable event
throughput without expanding the frozen 1.0 product surface.

## Release scope

- fail-closed agent evals and provider smokes for provider-error responses
- canonical aliases with actionable refusal for unknown provider IDs
- explicit `core` and `full` offline eval profiles
- bounded transactional event batches with WAL and full SQLite synchronization
- LiteLLM logging-worker cleanup for one-shot command lifecycles
- focused 90% or better branch coverage for core permission and persistence boundaries
- precise migration rollback documentation

## Qualification boundary

The release is qualified by the complete automated suite, branch-aware coverage, lint,
typing, documentation drift checks, deterministic core and full evals, security and
dependency audits, local performance budgets, build metadata, clean-wheel acceptance, and
sanitized supply-chain evidence. Exact results and artifact hashes are generated during the
release run.

The local acceptance matrix accounts for 841 passing tests at 68.67% combined branch-aware
coverage. The deterministic full profile passes 32/32 tasks and 20/20 artifact tasks. A clean
base wheel with no document, presentation, spreadsheet, or media extras passes the 28/28
core profile and 16/16 core artifact tasks, with all four skips named in its report. The
release performance profile passes every budget, including 10,000 durable batched events at
10,599 events/second on the qualification host. The memory-quality and deterministic
security-assurance gates pass, and a live Nous Portal/DeepSeek V4 Flash smoke creates and
validates its requested file through the native tool loop.

This release does not claim the remaining 1.0 external gates: multi-week soak evidence,
complete live qualification for every provider/model combination, local-only Ollama or LM
Studio qualification, or maintainer-backed cryptographic signing.

## Compatibility

The 0.90 stable-candidate contracts remain frozen. Provider aliases normalize common names,
while a non-catalog provider is accepted only when it has an explicit custom base URL.
State rollback restores migration-managed state; private backups and migration audit history
are intentionally retained.
