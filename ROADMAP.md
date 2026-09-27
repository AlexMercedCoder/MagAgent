# MagAgent Roadmap

> Last reviewed: 2026-09-27
> Current release: `1.3.0` (2026-09-12). Next release: `1.4.0`, in progress.
> The pre-1.0 plan, now fully shipped, is archived in [docs/ROADMAP_TO_1.0.md](docs/ROADMAP_TO_1.0.md).

## Position

MagAgent is the memory-first personal agent: it remembers you across sessions, in Git-backed
Markdown you can review. After 1.0 the goal is to make that memory visible and trustworthy in
every run, to close the remaining authority and audit gaps, and to promote existing features from
experimental to stable before adding new families.

Related projects own the neighbouring jobs: [Loro](https://github.com/alexmerced-oss/loro) for
governed team and data-platform agents, [Mag Command Center](https://github.com/AlexMercedCoder/MagCommandCenter)
for the desktop, and [Merced AI](https://github.com/AlexMercedCoder/merced-ai) for one identity
across other harnesses.

## Principles

- Show the work: every run should be able to say which memories and approvals it used.
- Measure real task completion, not command count.
- Keep state local, inspectable, exportable and recoverable.
- Fail closed at command, network, path, credential, gateway and plugin boundaries.
- Qualify provider and model combinations instead of implying that catalog presence equals support.
- Ratchet tests, typing, security checks and performance budgets upward.
- The 1.x compatibility promise from 1.0 holds: task, event, plugin, configuration, memory and
  desktop contracts stay backward compatible except for urgent security fixes with migration notes.

## Released since 1.0

| Release | Date | Highlights |
| --- | --- | --- |
| 1.0.0 | 2026-08-29 | Supported local agent platform; Web UI project context, run center and extensions |
| 1.1.x | 2026-08-30 to 08-31 | Web UI lifecycle controls, Graph Kanban repairs, OAP profile generation; shell-validation and graph fixes |
| 1.2.0 | 2026-09-06 | WebMCP origin allowlist and governed WebMCP tools |
| 1.3.0 | 2026-09-12 | Approval broker hardening, stdio decision validation, run-center recovery evidence ([notes](docs/RELEASE_NOTES_1.3.0.md)) |

## 1.4.0: Visible memory, closed audit gaps, and the Phase 4-6 work (in progress)

Work lands on `claude/next-release`; the CHANGELOG `Unreleased` section is the detailed record.
Release prerequisite: `agent-approval-interchange` 0.2.0 must be on PyPI first.

| ID | Item | Status |
| --- | --- | --- |
| G-3 | Per-run memory evidence, `/why last`, `magent memory evidence`, Web UI "Memory used" panel, desktop API | Done |
| G-1 | Approval grants: 30-day default expiry, legacy grants flagged, `permission grants list/revoke`, receipts on every grant hit | Done |
| G-12 | Terminal and gateway "always" approvals become the same expiring, receipted, revocable grants | Done |
| A-3 | Approval state on the shared AAIS 0.2 file store (cross-process locks, PID-reuse-safe owners, replay gaps, quarantine), legacy state imported | Done |
| G-7 | Pushed approval notifications (doorbells, `/api/approvals/stream`) instead of polling | Done |
| G-4 | `magent auth add <provider> --api-key-stdin` | Done |
| G-13 | Keyring as the optional `mag-agent[keyring]` extra with clear hints | Done |
| G-5 | Offline `mock` provider (experimental), with a scripted mode for fixtures | Done |
| G-11 | `magent ask --prompt-file`; `--json` stdout reserved for machine output | Done |
| G-6 | `magent serve --rpc` (`magent.rpc.v1`, experimental) for Mag Command Center's remote runtime | Done |
| G-8 | Offline workflow fixtures: edit, test, artifact, approvals in graphs and subagents, cancel mid-tool | Done |
| G-9 | `magent provider ping`; OpenAI and Anthropic connectivity evidence refreshed (tiers unchanged) | Done |
| G-10 | Parallel read-only tool calls; offline edit-quality benchmark (found and fixed two `edit_file` bugs) | Done |
| S-2 | CLI contract snapshot, `cli/main.py` split into command modules, `magent plan <sub>` with hidden aliases, `cli.main` and `workbench` type-checked | Done |
| H-1, H-2, H-5 | Drift fixes, release-metadata check, slow-test job and flake root cause | Done |
| Team memory | Shared MagGraph via Git with review-gated merge, CLI and Web UI review inbox, team recall | Done (Phase 6) |
| Graph executors | AGS task nodes run by MCP tools or A2A agents (`x-magagent-executor`, experimental); graph gallery | Done (Phase 6) |
| Signed plugins | Ed25519 signatures, trust store, static registries, `plugin search/install/verify` | Done (Phase 6) |
| VS Code bridge | Minimal extension in `editors/vscode` over the machine API (preview, unpublished) | Done (Phase 6) |
| SEC-1 | Security self-review of everything above: 30 fixes with regression tests, per-surface threat model | Done |
| S-6 | AGS executor convergence design note (`docs/design/ags-executor-convergence.md`) | Done |
| G-14 | `graph resume` asks for redacted secret parameters instead of passing `[REDACTED]` | Done |

Exit gates: full suite, slow job and coverage floor green; mypy clean; release-metadata check
strict-clean; Web UI bundle current; VS Code extension tests green; AAIS 0.2.0 published.

## Next

- **AGS convergence (from S-6):** propose an AGX evaluator for the `ags` support library,
  behavioural conformance fixtures (resume, retries, gate timeouts), an uncertain-node resume
  guard.
- **G-9 follow-up:** full qualification runs (tools, streaming) for OpenAI, Anthropic and Ollama,
  so their tier can move beyond `compatible`. This needs a spending decision.
- **Promote experimental features** once used: the RPC gateway (after Mag Command Center's
  remote mode ships against it), graph executors, the mock provider's scripted mode.
- **VS Code bridge:** decide whether to publish it, and add inline diff review.

## Known gaps being tracked

- Grants are exact to the action and, for shell commands, to the project directory; there is no
  pattern-based grant by design.
- Team memory identity is the MagAgent user name written as the Git author, not an
  authenticated identity; access to the Git remote is the real control.
- Memory evidence token counts are estimates (about four characters per token).
- A2A executors cannot answer an agent's follow-up questions (`input-required` fails the node).

## Scope held

- A hosted account, synchronization service or cloud control plane.
- A public executable-plugin marketplace before signing and trust are enforced.
- Editor extensions that bypass the stable machine API.
- Autonomous durable-memory changes without review, provenance and undo.
- Experimental upstream protocols presented as stable support.
