# MagAgent 1.3.0

Release candidate preparation — September 12, 2026. Not published.

- External approval decisions now wake the issuing broker; request creation and decisions share full storage transactions. Corruption and lock timeout fail closed. Windows locking uses an actual byte lock.
- Stdio decisions validate their AAIS envelope and reviewed digest. The Web UI reports the authority outcome, retains dialog focus, and shows origin and expiry.
- `magent capabilities --json` reports installed WebMCP prerequisites without a model call; the existing `magent tools doctor` remains available.
- Run center exposes recorded file changes, checkpoints and final audit evidence before recovery, and recognizes the runtime's waiting state. Task status changes are explicitly distinguished from restarting a stopped harness.
- Config safety and workbench maintenance now pass the type checker and were removed from its exclusion list.

Approval and task records remain local to their existing authority. Inspect uncertain external effects before retrying; changing a task status is not a guarantee of execution resumption.

AGS, OAP and AAIS document/wire formats remain unchanged. Local validation evidence and remaining platform gates are recorded in the ecosystem release report.
