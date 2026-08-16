# MagAgent 0.94.0

MagAgent 0.94.0 makes first-run setup and profile authoring clearer while strengthening
Agentic Graph release evidence.

## Highlights

- `magent get-started` provides a plain-language orientation in terminal and JSON forms.
- `magent profile wizard` authors validated OAP profiles without hand-editing YAML, and the
  managed `magagent` profile supplies the default general-purpose personality.
- `magent profile default`, `set-default`, and `clear-default` manage user and installation
  defaults from the CLI.
- profile network policy explicitly distinguishes `none`, read-only research access, and full
  arbitrary HTTP access while remaining below MagAgent's harness policy.
- provider and setup wizards discover current model catalogs, rank useful coding choices, cache
  results, and retain direct model-ID entry when discovery is unavailable.
- generated Agentic Graphs now have a dedicated real-scheduler execution regression in addition
  to strict validation, planning, packaged fixture, and CLI dry-run coverage.

## Compatibility

Existing OAP documents remain valid. Profiles that omit `permissions.network` retain full
network-tool availability subject to their tool allowlist and the active MagAgent harness policy.
The new field only narrows authority. Existing provider configuration remains valid; dynamic model
discovery is an additive wizard and inspection feature.

## Qualification

- 897 tests passed on Python 3.14.5.
- 68.80% branch-aware coverage passed the 68% ratchet.
- Ruff and MyPy passed across the repository and 195 source files.
- 32/32 offline reliability tasks and 20/20 artifact tasks passed.
- generated graph execution, CLI graph generation, strict validation, planning, and dry-run
  execution passed.
- release readiness, docs drift, security assurance, release performance budgets, and OAP Level 3
  conformance passed.
- exact-wheel metadata, clean-install, and smoke results are recorded during publication.
