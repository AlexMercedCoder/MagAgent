# MagAgent 0.95.0

Status: released 2026-08-19.

MagAgent 0.95.0 adds the machine contract required for complete Open Agent Profile management
from Mag Command Center and other desktop clients. It provides schema-driven creation,
effective-authority preview, conflict-safe edits, lifecycle operations, and restorable revision
history without making a desktop client parse or rewrite profile files itself.

Profiles selected by clients now apply consistently to asks, goals, deep research, recipes,
graph agent nodes, daemon tasks, subagents, and gateways. Profile JSON is accepted over stdin so
role instructions do not appear in process arguments or command logs.

Release validation included the full unit suite, generated documentation check, lint,
type checking, package build, wheel smoke test, and the existing external provider/release gates.

## Release Validation

- 903 tests passed; the two warnings are expected non-interactive `getpass` warnings from wizard
  tests.
- Ruff, mypy, generated command reference, docs doctor, and diff checks passed.
- Wheel and source distribution built as 0.95.0 and passed Twine metadata checks.
- A clean virtual environment installed the wheel and passed version, OAP schema-contract, and
  consolidated profile-detail smoke tests.
- Live model discovery passed for Nous Portal, Prime Intellect, and TrustedRouter. A profile-aware
  Nous Portal request using DeepSeek V4 Flash completed a real file-writing task and passed its
  strict artifact audit.
- Release diff secret scanning found no provider keys or credentials.
