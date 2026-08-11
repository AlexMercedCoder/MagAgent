# MagAgent 0.90.0 Release Record

MagAgent 0.90.0 is the contract-freeze release candidate for 1.0. It adds a canonical
stability inventory, backup-first state migrations, downgrade refusal, rollback, and
reproducible supply-chain evidence.

## Release scope

- proposed 1.0 stable, beta, and experimental contract inventory
- migration previews, private backups, migration-state rollback, and malicious-archive rejection
- persistent-state schema marker and refusal of unsafe downgrades
- dependency audit, secret scan, CycloneDX SBOM, SHA-256 manifest, and in-toto provenance
- `magent.release-evidence.v2` and expanded hosted release-candidate gates

## Qualification boundary

The release automates the evidence that can be reproduced in one qualification run. It does
not reinterpret a short test cycle as a multi-week soak, claim cryptographic signing without
maintainer keys, or claim the roadmap's 80% coverage gate before the measured suite reaches
it. Those items remain explicit inputs to the 1.0 decision.

The source acceptance baseline for this candidate is 801 passing tests and 68.16%
branch-aware coverage, with the CI regression floor raised to 68%.

## Compatibility

Stable candidate contracts are frozen after this release except for urgent security or data
loss fixes with migration guidance. Legacy state remains readable and can be upgraded with a
private backup. State created by an unsupported newer schema is refused.

Rollback restores migration-managed files from the selected backup and removes a schema
marker introduced by that migration. Private backup archives and migration audit history
remain available for recovery and traceability.
