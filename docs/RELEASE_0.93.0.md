# MagAgent 0.93.0

MagAgent 0.93.0 completes provisional Open Agent Profile v1 Level 3 harness support.

## Highlights

- deterministic `extends` composition with cycle rejection and resolution digests
- inherited capability narrowing across tools, permissions, budgets, MCP servers, skills, memory stores, and subagents
- OAP-scoped MCP and skill loading without profile-driven installation or configuration writes
- separate `oap-state` and `maggraph` read/write enforcement
- constrained child profiles with parent intersection, depth, count, and parallel ceilings
- profile continuity across interactive work, asks, goals, daemon jobs, and gateways
- conflict-safe rebasing for unrelated concurrent state proposals
- packaged offline Level 3 conformance fixtures and `magent agent conformance`

## Compatibility

Legacy Markdown agents continue to load in memory without modification. Existing OAP Level 2 profiles remain valid. Omitted Level 3 fields preserve the prior harness behavior, while declared fields only narrow locally available authority.

## Conformance Note

The Level 3 declaration is provisional. The implementation follows the supplied OAP guide and ships offline schema and behavioral evidence, but the canonical upstream repository and reference fixture digest were not publicly discoverable during qualification. MagAgent does not claim formal upstream certification until that comparison is possible.

## Qualification

- 876 tests passed on Python 3.14.5
- 68.78% branch-aware coverage, above the 68% ratchet
- Ruff and MyPy passed across the repository
- 32/32 offline reliability tasks and 20/20 artifact tasks passed
- release performance, security assurance, docs drift, platform contract, and OAP Level 3 conformance gates passed
- the exact wheel passed metadata, clean-install, docs, conformance, and vulnerability checks
- wheel and source distribution passed secret scanning, SBOM, provenance, checksum, and dependency-audit gates
