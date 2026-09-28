# MagAgent 1.4.0

Release notes, September 28, 2026.

Requires `agent-approval-interchange>=0.2.0,<0.3` (AAIS 0.2.0). The full list of changes, with
issue ids, is in the [CHANGELOG](../CHANGELOG.md#140-2026-09-28).

## Highlights

- Approvals now use the shared AAIS 0.2 file store: whole-transaction cross-process locking,
  owner identity that survives PID reuse, bounded retention with an explicit replay gap on
  `/api/approvals/events`, and quarantine of corrupt files. Existing
  `workbench/aais_approvals.json` state, grants included, is imported once.
- Grants have a lifecycle: "always allow" grants expire, terminal "always" answers become grants,
  and waiting processes and the Web UI are woken by pushed notifications instead of polling.
- Every turn records which MagGraph memory nodes were recalled (per-run memory evidence).
- New commands and options: `magent provider ping`, `magent auth add <provider> --api-key-stdin`,
  `magent ask --prompt-file PATH`, `magent eval edit-quality`, and an offline `mock` provider for
  first-run demos and CI (experimental).
- Parallel execution of read-only tool calls requested in one model response, ordered correctly
  against earlier writes and denials.
- Phase 6 previews: team memory with review-gated merge, graph nodes run by MCP tools or A2A
  agents plus a graph gallery (experimental), signed plugins and static registries, a remote
  JSON-RPC gateway (`magent serve --rpc`, experimental), and a minimal VS Code bridge
  (unpublished).
- Web UI: a real first run (no provider is claimed until you pick one, with an offline option),
  grouped provider picker, a fixed one-viewport shell, a phone tab bar, and self-hosted Inter and
  Source Serif 4 fonts. `magent ui` prints a plain line; `--json` keeps a machine-readable line.

## Behavior changes

- **OAP `permissions.shell: ask` asks for every shell command**, plus `run_python` and
  `install_package`, in every permission mode including `silent` and `yolo`. `shell: deny` removes
  the shell tools. Without a profile, read-only commands are still auto-allowed; set
  `permissions.read_only_shell_auto_allow = false` to ask for everything.
- **`magent agent import` copies the profile byte for byte**, preserving revision, history, state
  and digests. It never overwrites an existing profile. `--scope portable` imports into `.agents/`.
- **`magent plan <sub>`** replaces the nine `plan-*` verbs. The old spellings remain as hidden
  aliases.
- **`magent ask --json` stdout carries machine output only.** Status text moved to stderr.
- **The shell tool uses `bash --noprofile --norc -c`** instead of a login shell, so your profile is
  no longer re-sourced per command. `PATH` and the rest of MagAgent's environment are still
  inherited.
- **User names are validated everywhere** (1 to 64 letters, digits, `.`, `_` or `-`). An invalid
  stored active user is refused until repaired with `magent user switch <name>`.
- **Graph resume no longer reuses redacted secrets.** Supply them with `--param`, `--params` or
  `--param-file`, or answer the hidden prompt in a terminal.

## Fixes

- `edit_file` preserves CRLF line endings and refuses non-UTF-8 files instead of corrupting them.
- `magent agent export` keeps numeric `*_tokens` fields and writes the format its file extension
  names.
- One-shot model calls no longer hang draining LiteLLM's logging queue.
- `magent recipe list --json` prints JSON; `magent auth remove` also clears a key in
  `config.toml`.

## Security

A pre-release self-review (SEC-1) fixed issues in the RPC gateway, approval doorbells, team
memory, plugin signing and install, graph A2A executors, parallel read ordering, session grants,
`ask --prompt-file`, key storage, graph resume, user-name path containment, and the VS Code
extension's workspace settings. Each has a regression test. `magent docs show threat-model` has
the per-surface model.

AGS, OAP and AAIS document and wire formats are unchanged. Conformance results are recorded in
`docs/ags-conformance.json` and `docs/oap-conformance.json`.
