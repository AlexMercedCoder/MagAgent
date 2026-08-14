# MagAgent 0.92.0 Release Record

MagAgent 0.92.0 introduces Open Agent Profile v1 Level 2 as a deliberate pre-1.0 interoperability release. It preserves legacy agent definitions while adding portable agent identity, policy narrowing, bounded state, and reviewed state evolution.

## Release Scope

- safe OAP v1 YAML, JSON, and Markdown document loading with offline schema validation
- canonical full-profile and spec-only SHA-256 digests
- root-derived managed, user, project, portable, and plugin trust
- deterministic precedence, collision visibility, and duplicate rejection
- OAP-native `review`, `explore`, and `docs` built-ins
- effective tool, permission, turn, output, state, spend, and writeback narrowing
- `--agent` sessions and turn-scoped `@agent` invocation
- stable-prompt role assembly and bounded, scrubbed, untrusted profile state
- `/state`-only reviewed deltas with conflict checks, history, atomic writes, and checkpoints
- named locally owned lifecycle hooks, never profile-supplied command text
- expanded CLI, desktop machine contracts, in-app docs, and conformance declaration

## Qualification

- 864 unit and integration tests pass on Python 3.14.5.
- Combined branch-aware coverage is 68.55%, above the enforced 68% floor.
- The focused OAP, legacy, runtime, desktop, performance, contract, and architecture suites pass.
- Ruff, mypy, documentation doctor, generated references, and diff checks pass.
- Loopback session-messaging tests pass 16/16 outside the filesystem/network sandbox.
- The integration suite passes 5/5.

Exact-wheel installation and CLI acceptance are performed from the built release artifact before publication.

## Compatibility And Limits

Existing `.magent/agents/*.md` definitions continue to load without being rewritten. Explicit conversion is preview-only unless `--write` is supplied, and creates a backup first.

This release declares OAP v1 Level 2. `extends`, profile-contributed MCP servers, profile skill references, profile-declared subagent topology, and declared external memory stores remain unimplemented Level 3 surfaces. The upstream repository named by the supplied implementation guide was not publicly discoverable during development, so the vendored schema records that provenance instead of claiming an unverifiable source commit.
