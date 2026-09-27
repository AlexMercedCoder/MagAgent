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

## 1.4.0: Visible memory and closed audit gaps (in progress)

Work lands on `claude/next-release`; the CHANGELOG `Unreleased` section is the detailed record.

| ID | Item | Status |
| --- | --- | --- |
| G-3 | Per-run memory evidence: node ids, scores, token cost and truncation in the run record; `/why last`; `magent memory evidence`; Web UI "Memory used" panel; desktop API for Mag Command Center | Done |
| G-1 | Approval grants: 30-day default expiry (configurable), legacy grants grandfathered and flagged, `permission grants list/revoke`, an AAIS receipt and event for every grant hit | Done |
| G-4 | `magent auth add <provider> --api-key-stdin` so desktop apps never pass keys in argv | Done |
| G-5 | Offline `mock` provider for first runs, demos and CI (experimental) | Done |
| G-11 | `magent ask --prompt-file`, and `--json` stdout reserved for machine output | Done |
| H-1, H-2 | Version and count drift fixed; `scripts/check_release_metadata.py` in CI | Done |
| H-5 | Slow tests split into their own CI job; flaky shell test fixed at the root | Done |
| A-3 | Replace the approval store in `approval_broker.py` with the hardened store from `agent-approval-interchange` 0.2.0. Closes event-log truncation replay gaps and PID-only owner identity; the F01/F02 regression tests move to real separate processes | Waiting on the AAIS 0.2.0 library |
| G-0 | This roadmap and the PRD status refresh | Done |

Exit gates: full suite, slow job and coverage floor green; mypy clean; release-metadata check
strict-clean; Web UI bundle current; the memory evidence contract consumed by Mag Command Center.

## Next: structure and contracts (about one quarter)

Before any refactor, `--help` output and every `--json` shape are snapshotted as golden tests so a
split provably changes nothing.

- **S-2: split `cli/main.py`** (about 5,000 lines) into command modules, fold the nine `plan-*`
  verbs into `magent plan <sub>` with hidden aliases, and take `cli.main` off the mypy ignore list.
- **S-6: AGS executor convergence note.** A design note comparing the Loro and MagAgent Agentic
  Graph executors and whether a shared executor is worth it. No code.

## Then: differentiators (quarters 1 and 2)

Each item starts with a short design note for approval, because these are product bets.

- **G-6: remote JSON-RPC gateway.** `magent serve --rpc` implementing the contract Mag Command
  Center's remote client already speaks (run start, event subscription, decide, cancel). Token
  required, loopback by default, documented TLS reverse-proxy setup, lifecycle fixtures shared
  with Mag Command Center.
- **G-7: push-based approval notification** over the daemon event bus instead of 100 ms polling,
  with sequence compaction and an explicit gap signal.
- **G-8: workflow fixtures** for edit, test and artifact tasks, approvals inside a graph or a
  subagent, and cancel in the middle of a tool.
- **G-9: provider qualification.** Fresh live evals for OpenAI, Anthropic and Ollama so their
  support tiers are backed by dated evidence (today only Nous Portal is `qualified`).
- **G-10: parallel read-only tool calls** plus a diff-edit quality benchmark.

## Later (6+ months, to be re-planned)

- A team or shared MagGraph with review-gated merge.
- Agentic Graphs that call MCP and A2A agents, and a public graph gallery.
- Signed plugin trust and a plugin registry.
- A VS Code bridge that uses the stable machine API.

## Known gaps being tracked

- Terminal "always" approvals still save trusted shell patterns in the user profile with no
  expiry (`magent permission trust-list` / `trust-clear`). The new grant expiry applies to
  approvals made through the AAIS broker (Web UI, graphs, Mag Command Center, `--approval-stdio`).
- The approval event log keeps the newest 1,000 entries; replay across that window can skip
  events until A-3 lands.
- Memory evidence token counts are estimates (about four characters per token).

## Scope held

- A hosted account, synchronization service or cloud control plane.
- A public executable-plugin marketplace before signing and trust are enforced.
- Editor extensions that bypass the stable machine API.
- Autonomous durable-memory changes without review, provenance and undo.
- Experimental upstream protocols presented as stable support.
