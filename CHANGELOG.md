# Changelog

## Unreleased

- Fixed accessibility defects found by an audit pass over every view in both themes. Small muted
  text sat between 2.8:1 and 4.4:1 against its real background, below the 4.5:1 AA threshold for
  text that size; the tokens are recomputed to clear it in both themes. `.ghost-button` was used in
  three views and never defined, so those buttons fell back to the user agent's default: 21px tall,
  under the 24px pointer-target minimum, and painted with the browser's grey rather than the
  theme's. The theme toggle tied with the rail hover rule on specificity and came later, so hovering
  it applied the hover background but kept the resting colour, leaving it at 1.34:1 in every theme.
  Each page also carried two `<h1>` elements, the sidebar brand and the page title, while the chat
  view had none at all.

- Fixed configuration leaking into the process-wide default. `load_global_config` shallow-copied
  `DEFAULT_GLOBAL_CONFIG`, so every nested container a caller did not replace pointed straight at
  the module-level dict, and `_deep_merge` aliased it the same way. Writing to `cfg["providers"]`
  therefore edited the default for the whole process, and a later load — for a different user or a
  different workspace — inherited that provider entry, including an inline `api_key`. Every
  `configure_*` path mutates a loaded config, so all of them were affected. Both paths now deep-copy.

- Let the Web UI answer tool approvals. Its sessions ran with terminal permission prompts switched
  off and no alternative, so every tool above the mode's auto-approve threshold was refused
  outright: the agent could not do real work and never explained why. `check_permission` now takes
  an optional callback for a front end that has a user but no console, and a run uses it to publish
  the request into its event log and park until the browser answers. Unanswered times out as a
  denial, and cancelling releases a turn waiting on one.

- Made a Web UI turn survive the browser that asked for it. A turn ran on the HTTP request thread
  that started it, so closing the tab mid-reply killed the work: the answer was never recorded and
  the conversation kept a question with no response. A turn is now a run on its own thread with an
  append-only event log, and it finishes whether or not anyone is watching.
- Added reattachment. Streams read the log from a cursor and `/api/runs?conversation_id=…` finds the
  run a reloading tab lost, so reconnecting replays what was missed instead of losing it. Only a
  still-running run is resumed; a finished one already wrote its reply, and replaying it would show
  the answer twice.
- Made Stop actually stop. It cancelled only the socket, leaving the turn running on the server and
  still spending tokens; it now cancels the run, which is checked between chunks and between group
  participants so a long reply is interrupted partway. Whatever was already said is kept and marked
  cancelled rather than vanishing from the screen.

- Added a Memory view to the Web UI. MagAgent's memory is a linked graph of notes the agent wrote
  about you and your projects and it shapes every reply, but the browser could only see the
  promotion inbox, so the memory already in force was invisible. The view reports graph size, link
  count, disk usage, duplicate groups and suppressed notes, lists the notes, searches them in
  keyword, hybrid or semantic mode, and opens any note with its full text and the notes that link
  to and from it. It is read-only: editing, merging and deletion stay in the CLI, where the
  destructive commands already have their confirmations. The roster and each note body are bounded,
  because a memory graph grows without limit.
- Added first-run setup to the Web UI. The browser assumed a provider was already configured, so
  opening `magent ui` on a machine that never ran `magent setup` produced a workspace whose first
  message failed with a credential error. Readiness is now checked before the shell renders, and a
  setup panel reports the same checks the CLI does and lets a provider and model be chosen.
  Credentials are never accepted through the form: `set_default_provider` can persist an inline key
  into the global config file, so that argument is never passed from this path.
- Fixed readiness for the shipped default provider. `ollama` needs no key, so `provider_readiness`
  called it ready on machines where Ollama had never been installed; the first message then failed
  with a connection error. The local runtime is now probed directly, with a short timeout.
- Stopped `test_running_daemon_process_observes_durable_cancellation` failing on machine load. Two
  timing assumptions were too tight and neither concerned cancellation: the wait for the child to
  reach `running` was capped at ten seconds, and the budget allowed five seconds against a child
  that slept ten.

- Rendered assistant markdown in the local Web UI: headings, lists, blockquotes, rules, inline and
  fenced code with a copy button, emphasis, and links. Replies previously showed their own `**`
  markers and backticks because content was escaped straight into a text node.
- Treated model output as untrusted in that renderer. Text is escaped before any markup is
  introduced, raw HTML never becomes elements, and `javascript:` and `data:` URLs never become
  anchors. Covered by Node-backed formatting and injection tests.
- Fixed `magent dashboard --serve`, which bound its socket and then aborted with
  `TypeError: Object of type ThreadingHTTPServer is not JSON serializable` because the command
  rendered the live server handle as part of its JSON result.
- Added an `aria-live` transcript, a visible focus ring, and a `prefers-reduced-motion` query to the
  Web UI; streaming output was previously silent to assistive technology.
- Added light and dark themes to the Web UI. All 115 colours were literals, so the OS setting had no
  effect; they are now tokens, with a rail control cycling system, light, and dark. Fixed the
  composer, which set no background or colour and so rendered as a white box in dark mode.
- Added a keyboard model: focus the composer, search, start a chat, switch any of the seven views,
  close dialogs, and a shortcuts sheet on `/`. Unmodified keys never fire while typing.
- Added profile portability to the Web UI: export an Open Agent Profile as a portable document and
  import one from a file. Secrets never leave, runtime state and history are stripped both ways, and
  an imported profile starts this workspace's revision history at 1. A malformed upload reports the
  problem instead of failing the request.
- Made the Bots view a roster: chat with one profile, or pick two to five and start a group.
- Reworked the Graph Kanban lanes to Pending, In progress and Complete, and added blank-board
  authoring, *Add card*, and graph export alongside the existing file loading and AI drafting.
- Rebuilt the local Web UI as a React and TypeScript application under `webui/`, compiled by Vite
  into `src/magent/webui/static/`. The interface was previously 30 KB of hand-minified JavaScript
  across six views with no build step, which could not be reviewed in a diff or tested. All six
  views are ported; the loopback token, CSRF header, Host and Origin checks, CSP, and `no-store`
  policy are unchanged.
- Added a `Web UI` workflow that installs from the lockfile, runs the unit tests, rebuilds, and
  fails when the committed bundle drifts from its source, plus a smoke job that serves a temporary
  workspace and asserts the token gate.
- Fixed `GET /api/conversations`, which always returned 405. The blanket "mutating paths refuse GET"
  guard also caught the list branch, leaving it unreachable. Write-only paths still refuse GET.
- Replaced raw exception text in the transcript with named failures that state the recovery step,
  covering credentials, rate limits, timeouts, unreachable providers, permission denials, budget
  overflow, unavailable models, cancellation, and profile problems.

## 0.97.0 (2026-08-22)

- Rebuilt `magent ui` as a bundled local chat workspace with durable traditional,
  profile-backed bot, and bounded multi-bot group conversations with streamed responses.
- Added guided Open Agent Profile creation, effective-authority inspection, and safe default
  settings without exposing secret-bearing configuration to the browser.
- Added a fixed three-column Graph Kanban that validates and runs native Agentic Graphs through
  the durable executor while retaining dependencies, profile routing, gates, changed files, and
  per-card success or failure summaries.
- Added blank graph authoring and review-only AI graph generation from a goal, including editable
  task cards, profile assignment, dependency wiring, project-confined saves, strict validation,
  and optimistic digest conflict detection.
- Hardened the loopback UI with per-launch authorization, CSRF enforcement, POST-only mutations,
  bounded JSON bodies, Origin and Host checks, CSP, and no-store response policy.

## 0.96.0 (2026-08-22)

- Added the `magent.agentic-graph-authoring.v2`, `magent.graph-plan.v2`,
  `magent.graph-event.v1`, `magent.graph-result.v1`, and `magent.graph-status.v1` machine
  contracts for a complete desktop Graph Board.
- Added reference-aware graph edits, review-only model generation, selective gate approval,
  durable attach, pause, cancellation, resume, snapshot retention, and selective downstream retry.

## 0.95.0 (2026-08-19)

- Added the versioned `magent.oap-profile.v1` desktop authoring contract with schema and
  local-choice discovery, previewed effective authority, JSON-stdin apply, import/export,
  clone/delete, optimistic concurrency, and secret-safe portable exports.
- Added durable authoring checkpoints and digest-guarded profile revision restoration while
  preserving runtime-owned profile state and proposals across behavior edits.
- Extended OAP selection to project-scoped deep research, recipe plans, and Agentic Graph
  agent nodes so desktop profile choices remain operational rather than decorative.
- Regenerated the built-in command reference and expanded agent and desktop integration docs.

## 0.94.0

- Added `magent get-started` with an accessible terminal guide and machine-readable JSON covering setup, sessions, permissions, profiles, research, memory, and larger workflows.
- Added complete interactive Open Agent Profile authoring, the managed `magagent` default personality, user/global default-profile commands, and explicit per-profile network access narrowing.
- Added provider-aware live and cached model discovery to setup and provider wizards, model search and ranking, role guidance, and clearer setup explanations across profile, memory, subagent, gateway, and project flows.
- Clarified that web-enabled profiles need both an allowed web tool and `network: read` or `full`; `read` supports search and inspection without arbitrary HTTP writes.
- Added a generated-graph regression that executes through the real scheduler, plus CLI generation, strict validation, planning, and dry-run qualification.
- Updated packaged, repository, generated command, configuration, architecture, testing, and quick-start documentation for the new workflows.

## 0.93.0

- Completed MagAgent's provisional Open Agent Profile v1 Level 3 harness support with deterministic `extends` composition, inherited policy narrowing, and resolution digests.
- Added profile-scoped MCP server and skill selection, declared OAP and MagGraph memory stores, and read/write enforcement for state injection, recall, learning, and summaries.
- Added constrained subagent delegation with parent capability intersection, profile/model routing, delegation depth and concurrency ceilings, manual `/spawn @profile`, and profile continuity across goals, daemon work, and gateways.
- Added conflict-safe state-delta rebasing for unrelated concurrent edits while preserving fail-closed same-target conflicts.
- Added packaged offline Level 3 conformance fixtures and `magent agent conformance`, plus machine API conformance reporting and focused inheritance, runtime, daemon, gateway, and security regression tests.
- Updated repository and in-app documentation for Level 3 authoring, operation, diagnostics, and the remaining upstream-certification caveat.

## 0.92.0

- Added Open Agent Profile v1 Level 2 support with YAML, JSON, and Markdown encodings, vendored offline schema validation, safe YAML loading, canonical profile/spec digests, and in-memory legacy conversion.
- Added deterministic managed, user, project, portable, and plugin profile discovery with root-derived trust, explicit collision reporting, duplicate rejection, and OAP-native built-in agents.
- Enforced effective-profile narrowing for tools, permissions, model-round limits, state budgets, and writeback policy; profiles cannot grant capabilities disabled by MagAgent policy.
- Added `--agent`, turn-scoped `@agent` activation, stable-prompt role assembly, untrusted bounded profile state, model/provider preferences, and profile identity records.
- Added reviewable profile state deltas with secret scrubbing, `/state`-only operations, revision and digest conflict checks, atomic writes, history, named local hooks, and an inbox accept/reject flow.
- Expanded `magent agent` with `explain`, `validate`, `convert`, `state`, `history`, `forget`, `inbox`, `accept`, `reject`, and `digest`, while retaining legacy definitions and existing invocation commands.
- Added OAP conformance, security, runtime, CLI, and compatibility tests plus repository and in-app documentation.

## 0.91.0

- Fixed false-positive provider qualification: bracketed provider errors now fail agent evals and tool smokes even when stale artifacts exist.
- Added canonical provider aliases and fail-fast diagnostics for unknown provider IDs while preserving explicitly configured custom OpenAI-compatible providers.
- Added `core` and `full` offline eval profiles so a clean base wheel can prove its supported contract without importing optional document/media dependencies; full qualification still exercises all 32 tasks.
- Reworked durable task event writes around bounded, transactional batches, preserving WAL and full synchronization while making the 10,000-event release budget practical on normal developer hardware.
- Hardened LiteLLM one-shot lifecycle cleanup to avoid leaked logging coroutines after provider smokes and evals.
- Expanded branch coverage for task persistence, workbench durability, permissions, shell policy, provider routing, eval failure handling, and batch limits.
- Clarified that state rollback restores migration-managed state while intentionally retaining private backups and migration audit history.

## 0.90.0

- Froze the proposed 1.0 contract candidate with a machine-readable inventory covering public imports, CLI commands, config keys, task/event schemas, plugins, memory, MCP, and desktop APIs.
- Added backup-first persistent-state migrations, private archives, migration history, migration-state rollback, archive containment, and actionable refusal when an older runtime encounters newer state.
- Added `magent system compatibility`, `magent system migrate`, and `magent system rollback` for upgrade and recovery without manual config editing.
- Added project dependency auditing, tracked-file secret scanning, CycloneDX 1.6 SBOMs, SHA-256 manifests, and in-toto/SLSA-shaped provenance through `magent release supply-chain`.
- Upgraded release evidence to `magent.release-evidence.v2`, requiring contract, migration, memory, performance, security, supply-chain, artifact, test, coverage, and CI evidence.
- Expanded CI with migration acceptance, contract inventory, dependency audit, supply-chain generation, and uploaded release-candidate evidence.

## 0.80.0

- Added thresholded `magent.memory-eval.v2` retrieval evaluations for ranking, stale and contradictory facts, project scope, provenance, backlinks, explanations, and context budgets, plus a reproducible checked-in MagGraph fixture.
- Preserved node scope and provenance in hybrid, native, and semantic search results and added backlink-aware `/why` and `magent.memory-recall.v2` desktop packets.
- Added `magent performance budget` with quick and release profiles covering cold imports, project inspection, memory search, 10,000-event throughput, ordered reads, and four concurrent task writers.
- Added periodic model/tool liveness heartbeats and stable start, progress, and finish events so common operations no longer appear hung.
- Added interactive `/tasks`, `/task`, `/budget`, and `/why` controls for recovery, spend visibility, and recall diagnostics without leaving the session.
- Updated the CLI, machine contracts, packaged documentation, roadmap, test corpus, and release evidence for daily-driver quality.

## 0.70.0

- Added TrustedRouter and Prime Intellect as first-class OpenAI-compatible providers, including support tiers, dated evidence, credential aliases, Prime team routing, setup flows, machine-readable matrices, and generated documentation.
- Added a deterministic `magent system security-report` covering command-policy bypass probes, SSRF controls, path containment, fail-closed gateways, secret handling, and atomic persistence; release evidence now embeds its result.
- Expanded security and durability regression coverage across shell parsing, redirects, response limits, gateway authorization and lifecycle, graph containment, provider error redaction, and workbench recovery.
- Added public-wheel acceptance on Linux, macOS, and Windows and generalized the credentialed provider-qualification workflow for all primary providers.
- Published the current threat model, provider support semantics, known limitations, and 0.70 release evidence while consolidating the remaining path to 1.0 into one roadmap.

## 0.60.0

- Split the agent runtime into typed context, tool-loop, lifecycle, and support modules while preserving `AgentSession` compatibility.
- Enabled `check_untyped_defs`, removed core runtime exemptions, and added typed boundary records plus stable contract fixtures.
- Added a real local JSON-RPC LSP client for Python, TypeScript/JavaScript, Rust, and Go with capability-aware symbols, diagnostics, definitions, references, hover, rename, cancellation, restart, and clean shutdown.
- Added bounded AST/text fallbacks, real Python and TypeScript LSP integration tests, and diagnostics integration with existing review and repair workflows.
- Split optional document, media, desktop, browser, gateway, MCP, and LSP dependencies from the core install; added `full`, readiness diagnostics, install-shape measurements, and a fresh core-wheel CI smoke test.
- Added dependency-direction and module-size architecture tests, extracted-runtime branch coverage above 85%, and documented compatibility-facade exceptions.
- Avoided unnecessary hook thread executors when projects have no configured hooks.

## 0.50.0

- Added `magent.agent-eval.v1`, an isolated real-AgentSession evaluation harness with
  independent validators, task-level crash containment, lifecycle evidence, usage metrics,
  artifact verification, atomic reports, and baseline comparison support.
- Added a 32-task deterministic reliability corpus spanning coding, test repair, multi-file
  work, research, document, spreadsheet, and visual artifacts, malformed tool calls,
  permissions, path containment, and data tools; the release baseline passes 32/32 and 20/20
  artifact tasks.
- Added a low-cost live provider suite and scheduled/manual qualification workflow. Nous Portal
  with DeepSeek V4 Flash passes the release baseline at 5/5 tasks and 4/4 artifacts.
- Added `magent release evidence` for source revision, docs/provider contracts, evals, tests,
  coverage, CI links, artifact hashes, and explicit release exceptions.
- Expanded documentation drift detection to package and MagGraph versions, Python support,
  machine contracts, provider defaults, and generated references.
- Added public release severity and known-limitations policies, MCP integration tests and the
  MCP extra to CI, deterministic agent evals on pull requests, and uploaded eval evidence.
- Added focused harness, validator, drift, evidence, and fault-containment tests while retaining
  the existing branch-coverage floor. Raising overall branch coverage from the measured 64.9%
  to the roadmap's 72% target remains follow-up work centered on the legacy CLI entrypoint.

## 0.35.1

- Rebuilt shell classification around a structural parser so substitutions, redirects,
  destructive read-command flags, network upload flags, executable prefixes, and saved trust
  patterns cannot bypass permission policy.
- Added shared outbound network policy with SSRF protection, bounded responses, redirect
  validation, and confirmation for mutating HTTP methods; protected local HTTP surfaces with
  launch tokens, host checks, POST-only mutations, and scoped dashboard serving.
- Hardened remote gateways with fail-closed allowlists, explicit public-access opt-in,
  mention enforcement, channel serialization, session-only approvals by default, lifecycle
  fixes, and redacted external errors.
- Added atomic, locked, recoverable workbench storage; durable daemon claims; safer session
  messaging runtime paths; plugin path containment; read-only SQLite enforcement; and
  subprocess timeout cleanup.
- Fixed completed-subagent cap accounting, parallel task batching, `magent run`, duplicate CLI
  registrations, streaming error history, provider request merging, MCP response handling,
  semantic-memory index consistency, and graph retry/isolation edge cases.
- Added resumable chat transcripts, enforced spend budgets, shell sandbox profiles, memory
  hygiene, provider conformance checks, gateway administration, permission diagnostics,
  secret hygiene checks, and reusable release eval suites.
- Extracted memory commands and terminal renderers from the main CLI, consolidated the agent
  tool loop, centralized subprocess and safe-name handling, and restored a passing mypy gate.
- Expanded the unit suite from 478 to 715 tests and raised the branch-coverage floor to 64%.
- Updated CI to current checkout/setup actions and made CLI option-contract tests independent
  of terminal-width-specific Rich help rendering.

## 0.35.0

- Added safe Pi package compatibility: native Agent Skill and prompt-template conversion, context and MCP import, manifest detection, quarantined extension/theme inventory, and an explicitly granted Pi-runtime bridge.
- Added Agentic Graph Specification 1.0 conformance level 3 with strict validation, deterministic planning, typed expressions, model-tier routing, harness-owned criteria, human gates, branching, retries, budgets, parallel execution, loops, maps, subgraphs, compensation, resume, and portable run records.
- Added `magent graph validate`, `plan`, `add/list/show`, `generate`, `run/status/resume`, plan and recipe export, and native plugin-pack export commands.
- Retargeted orchestrated goals onto the Agentic Graph executor and added graph execution to the daemon, gateways, desktop machine API, task runtime, tool policy, and sandbox boundaries.
- Added project-aware graph generation, canonical schemas and examples, an offline authoring guide, a bundled AGS skill, generation evals, conformance fixtures, and provider-free structural execution tests for every packaged YAML example.
- Added machine-readable AGS capability, tier, and logical-tool mappings through `magent system info`.
- Updated architecture, command, plugin, testing, support, roadmap, and repository documentation for portable graph workflows.

## 0.34.0

- Added a unified durable task runtime for interactive, one-shot, goal, daemon, gateway, and desktop execution with versioned task and event contracts.
- Added cancellation, parent/child work, artifact tracking, checkpoint-aware recovery, and preattached desktop task execution.
- Integrated MagGraph 0.4 hybrid retrieval, global/project recall, backlink explanations, provenance, and crash-safe reviewed memory batches.
- Added `magent system ecosystem-report` for deterministic local contract, documentation, graph, provider-catalog, and desktop readiness evidence with external gates reported separately.
- Expanded MCP compatibility, session coordination, plugin, provider, and desktop machine contracts while keeping terminal and JSON/JSONL behavior aligned.
- Updated the roadmap, architecture, testing, memory, configuration, desktop integration, command, and built-in documentation for the coordinated ecosystem release.

## 0.33.0

- Added dual-era MCP SDK v2 support for classic protocol revisions through `2025-11-25` and modern `2026-07-28` servers over stdio and Streamable HTTP.
- Added MCP prompt, resource, template, completion, cache, subscription, structured-content, and consent-gated MRTR support with redacted diagnostics and explicit trust boundaries.
- Added authenticated local session-to-session messaging with peer discovery, receiving policies, durable queues, delivery receipts, retry, CLI and agent tools, safe turn-boundary injection, and a Command Center machine facade.
- Split the former tool executor monolith into focused file, shell, web, data, system, artifact, and messaging capability modules while retaining the stable `ToolExecutor` facade.
- Hardened checkout test isolation, resource-warning handling, SQLite cleanup, semantic-memory connection lifecycle, archive extraction, shell safety, and desktop API coverage.
- Updated the README, roadmap, architecture, CLI reference, configuration, desktop integration, MCP, messaging, testing, and TUI documentation.

## 0.32.14

- Added provider environment aliases for common gateway setups: `NOUS_KEY`, `OPENROUTER_KEY`, `OPENCODE_KEY`, and `OPENCODE_ZEN_API_KEY`.
- Fixed live request compatibility for newer OpenAI GPT-5.x models and Anthropic Sonnet 5 models that only accept default temperature.
- Updated Anthropic and Gemini defaults to live-tested current models: `claude-sonnet-5` and `gemini-3.6-flash`.
- Increased provider ping resilience for providers that need more than a tiny 10-token response budget.
- Refreshed provider docs and tests around model defaults, credential aliases, and request-parameter compatibility.

## 0.32.13

- Added staged goal orchestration behind the feature flag so MagAgent can cache a high-level plan, execute step plans through subagents, and validate progress incrementally.
- Updated CLI and desktop-facing documentation for the orchestrated goal workflow.
- Prepared the desktop API surface for Command Center to inspect staged goal state.

## 0.32.12

- Fixed the CI coverage gate so it uses a ratcheted floor matching the current measured unit-suite coverage instead of the stale 75% threshold that kept recent pushes red.
- Refreshed package metadata and built-in testing/config documentation for the patch release.

## 0.32.11

- Refreshed GitHub and packaged documentation after the `0.32.10` file-write recovery release.
- Updated the README test badge to match the current unit suite.
- Clarified troubleshooting guidance for immediate missing-content `write_file` recovery.

## 0.32.10

- Fixed interactive file-generation turns that stopped after repeated malformed `write_file` calls.
- Missing-`content` recovery now runs immediately after the first `write_file` validation failure when a path is known, before the same-tool failure guard can end the turn.
- Updated tests to cover early artifact recovery for generated HTML/game-style scaffolds.

## 0.32.9

- Added direct `magent goal --run` execution with stronger verifier/reviewer goal-loop instructions.
- Fixed missing-`content` artifact recovery for pluralized `write_file` validation errors.
- Added `/retry`, `/undo`, `/usage`, and `/insights` interactive session commands.
- Improved permission UX for safe read-only shell pipelines and added `magent permission trust-list/trust-clear`.
- Added tool backend readiness commands, local skill browsing commands, and a conservative `magent update` helper.
- Updated README, built-in command docs, TUI docs, tool docs, and tests for the new daily-driver UX.

## 0.32.8

- Added startup version visibility in the TUI banner so local installs are easier to verify.
- Added `magent auth list/add/remove` for optional OS keyring-backed provider credentials.
- Added the `image_maker` model role, `magent model image-wizard`, model capability summaries, and the AI-backed `generate_image` tool.
- Added config validation, ambient instruction sources, provider rate-limit cooldown tracking, and gateway approval commands.
- Tightened tool argument validation, long-running/cancel behavior, and generated-artifact cleanup.
- Updated README, GitHub docs, packaged docs, and generated command/config references for the expanded CLI surface.

## 0.32.7

- Added native `create_svg`, `create_diagram`, and `create_image` tools for local SVG, Mermaid, PNG, and JPEG artifact creation.
- Added visual artifact tools to selective tool loading, file mutation tracking, and the files capability pack.
- Updated agent guidance and built-in docs so diagram/image/SVG requests use native tools instead of generated scripts or shell pipelines.

## 0.32.6

- Added native `create_docx` and `create_pptx` tools so Word documents and PowerPoint decks can be generated directly instead of by writing/debugging temporary Python scripts.
- Added `python-pptx` as an installed dependency so presentation generation works out of the box on fresh installs.
- Included Office artifact tools in file mutation tracking, selective tool loading, and the files capability pack.
- Shortened the streamed max-round stop diagnostic so terminal output does not duplicate the same loop-stop message.

## 0.32.5

- Added bounded artifact recovery for providers that repeatedly call `write_file` with `path` but no `content`: MagAgent now asks once for the raw artifact body with tools disabled, then writes it through the native file tool.
- Rejected filename-only recovered artifacts so a failed HTML generation cannot create a file containing only `cheese.html` or `oranges.html`.
- Reduced duplicate terminal noise when the loop guard stops a turn: the inline `stop` diagnostic stays short while the full verifier details are returned once.

## 0.32.4

- Fixed file mutation verification so a later successful absolute-path write clears an earlier relative-path failure for the same file.
- Suppressed noisy LiteLLM remote cost-map network warnings in interactive sessions.
- Tightened missing-`content` recovery guidance for `write_file` so artifact recovery avoids unnecessary research/read loops.

## 0.32.3

- Added Hermes/OpenCode-inspired model-specific tool-use enforcement for tool-sensitive model families such as DeepSeek, Qwen, Gemini, GPT/Codex, Grok, and GLM.
- Added configurable agent loop controls for max model rounds, max tool calls, repeated identical tool calls, same-tool failures, doom-loop policy, and file mutation verification.
- Added targeted corrective steering for failed tool calls, including `write_file` calls missing the required `content` argument.
- Added turn-end file mutation verification so unresolved failed writes are surfaced in the final response instead of being accidentally summarized as complete.
- Improved failed tool timing labels so interactive output includes the failure reason inline.

## 0.32.2

- Added interactive timing markers for model rounds and tool completions so slow research/file-writing turns are easier to diagnose from the terminal.
- Added JSONL timing events for model calls, tool calls, and stopped tool loops.
- Added a repeated-tool guard that stops identical tool requests after three attempts instead of rewriting the same file path indefinitely.
- Added a `write_file` content guard that rejects obvious placeholder payloads such as writing `cheese.html` into `cheese.html`.

## 0.32.1

- Fixed OpenCode Go / DeepSeek-style DSML pseudo tool calls being printed as assistant text instead of executed as real MagAgent tool calls.
- Added retry handling for truncated DSML tool markup so interactive sessions do not dump partial generated files into the terminal.
- Added regression coverage for streamed and non-streamed pseudo `write_file` tool calls.

## 0.32.0

- Added `magent goal` and `/goal` for measurable implement/verify/review goal loops with durable plan records and optional daemon queueing.
- Added `magent jobs`, `/jobs`, `magent statusline`, and `/statusline` for daily-driver background task and statusline UX.
- Added `magent context audit`, `/context`, and `magent config ux`/`/config` control-center summaries for context hygiene and CLI-first configuration.
- Added built-in `verify-and-review` and `context-hygiene` recipes.
- Added Gemini CLI-style plugin import support with `magent plugin import gemini <path>`.
- Updated README and built-in docs for goal loops, context hygiene, statusline, jobs, and Gemini migration.

## 0.31.2

- Refused shell-based file writes such as heredocs, redirection, `tee`, `touch`, and Python write snippets with clear guidance to use `write_file`/`edit_file`.
- Strengthened agent and tool descriptions so generated files are written through native file tools instead of permission-heavy shell workarounds.
- Added periodic `Still running <tool>...` feedback for long-running tool calls in interactive sessions.
- Allowed harmless `python3 -c 'print(...)'` probes without prompting while keeping arbitrary Python execution gated.

## 0.31.1

- Auto-approved read-only `curl`/`wget` inspection pipelines while keeping uploads, downloads, and mutating HTTP methods confirmation-gated.
- Made shell approval prompts visibly acknowledge approved commands and report completion for confirmed shell actions.
- Added macOS shell normalization so ambiguous `pip ...` and `python ...` commands run as `python3 -m pip ...` and `python3 ...`.
- Documented the Python interpreter mismatch behind `pip install --upgrade mag-agent` failures on Macs.

## 0.31.0

- Added provider-aware prompt caching support with stable prompt prefixes, cache request hints, cache telemetry normalization, and `magent cache doctor/status`.
- Added reliable multiline prompt composition with `/compose` plus prompt-toolkit support for newline bindings when terminals support them.
- Improved tool-call robustness by normalizing common argument aliases such as `file_path`/`contents`, preventing raw `KeyError('path')` failures.
- Removed the extra finalizing model call that could emit pseudo tool-call markup without actually writing files.
- Improved shell permission UX with scoped approvals, read-only shell pipeline classification, trusted exact-command patterns, and stop-after-denial behavior.
- Made `magent ask` show progress in human-readable mode while keeping `--json` clean for scripts.
- Made `magent research` render readable terminal output by default, with `--json` for scripts and `--write/--out` for Markdown reports.
- Made `magent plan` project-aware, less generic, and directly saveable into draft or executable plan workflows.
- Organized `magent --help` into useful Rich help panels with prominent Start Here commands.
- Made `magent context map` render a readable terminal briefing by default, with `--json` for the full structured payload, and filtered low-value draft plans from memory promotion candidates.
- Updated README, built-in docs, and regression coverage for the new CLI UX.

## 0.30.2

- Fixed `magent configure` provider smoke tests on Python 3.14 by using `asyncio.run()` instead of looking up a non-existent default event loop.
- Updated web search to prefer the modern `ddgs` package, suppress the old `duckduckgo_search` rename warning when falling back, and filter low-relevance search results before the agent fetches pages.
- Made interactive Ctrl-C shutdown avoid re-entering an already-running event loop.

## 0.30.1

- Raised the MagGraph dependency floor to `maggraph>=0.2.5`, which ships Python 3.14-compatible PyO3 bindings, abi3 wheels, and a fixed Intel macOS wheel publish path.
- Added Python 3.13 and 3.14 package classifiers so supported interpreter versions are clearer on PyPI.

## 0.29.0

- Added desktop integration APIs for Mag Command Center and other local app wrappers.
- Added `magent system info` for machine-readable installation, platform, config path, executable, and user status.
- Added `magent ask --json` with response, session ID, audit, files touched, commands run, and permission failures.
- Added `magent config get` and `magent config set` for redacted machine-readable config inspection and safe dot-path updates.
- Added `magent memory graph` and `magent memory node` for compact JSON memory graph browsing.
- Added `magent data sqlite-list`, `sqlite-tables`, `sqlite-schema`, and `sqlite-query` for safe SQLite database exploration.
- Added tests for desktop API helpers and CLI integration command payloads.

## 0.28.0

- Added provider model discovery and caching with `magent provider models <provider> --refresh` for OpenAI-compatible `/models` endpoints.
- Added model recommendations from live health observations and catalog hints with `magent provider recommend-model` and `magent model recommend`.
- Added durable model health records for provider/model/task outcomes, including latency and tool-use smoke results.
- Extracted provider tool smokes into reusable domain logic and added `magent provider smoke-all`.
- Added explicit provider smoke timeouts so slow or stuck model/tool loops fail cleanly.
- Added `magent readiness` for one concise setup, docs, project, provider, and model readiness report, with optional live smoke.
- Added `magent ask --repair-attempts` and `--strict-audit` so one-shot runs can retry obvious incomplete file tasks and fail CI when audits remain bad.
- Expanded the local UI with readiness, model health, and provider smoke action endpoints.
- Updated tests and docs for provider discovery, model health, readiness, ask repair, and UI cockpit actions.

## 0.27.0

- Made one-shot `magent ask` runs permission-safe by returning structured `permission_required` tool results instead of prompting in non-interactive contexts.
- Added per-run `magent ask --permission-mode` and `magent ask --yes` overrides without persisting config changes.
- Added lightweight one-shot task audits that flag missing requested files and permission-required tool calls after a run.
- Added `magent provider tool-smoke` to run a tiny live provider tool-use smoke test against `write_file`.
- Updated the Nous Portal default model to `deepseek/deepseek-v4-flash` after live smokes showed Hermes aliases need explicit model selection and are less suitable for cheap tool-use checks.
- Added regression coverage for ask audits, non-interactive permission denials, and provider tool-smoke CLI plumbing.
- Updated reliability docs for provider pings, tool smokes, and one-shot audit warnings.

## 0.26.1

- Fixed strict OpenAI-compatible provider loops by stripping SDK/provider-only message fields before sending conversation history back to LiteLLM.
- Added regression coverage for tool-call history sanitization after OpenCode Go rejected `provider_specific_fields`.
- Improved provider readiness diagnostics so inline API keys count as configured without printing secret values.
- Fixed OpenCode Go doctor readiness to reflect subscription credentials instead of reporting a false action item.
- Redacted API keys, tokens, secrets, and passwords from `magent config show` and provider setup return payloads.

## 0.26.0

- Bumped the MagGraph dependency to `maggraph>=0.2.0`.
- Replaced MagAgent's keyword memory scans with MagGraph's native structured search API while keeping the optional semantic sidecar for semantic and hybrid modes.
- Switched memory recall context to MagGraph recall bundles with compact excerpts, links, backlinks, and explicit relevance reasons.
- Routed new memory writes through MagGraph memory-node helpers for consistent `preference`, `project_fact`, `decision`, `task`, `session_summary`, `bookmark`, and `tool_failure` schemas.
- Routed memory merge, suppress, and unsuppress operations through MagGraph's durable quality primitives.
- Added single-file index refresh and change-feed use after memory writes, inbox acceptance, and promotion.
- Updated memory docs and tests for graph-native search, recall provenance, backlinks, and change tracking.

## 0.25.0

- Added MCP-first plugin imports with `magent plugin mcp import` and safe config application through `magent plugin mcp apply`.
- Added compatibility importers for OpenCode, Claude, and Codex-style `SKILL.md` packs.
- Added manifest adapters for native MagAgent manifests, `plugin.json`, `package.json`, `AGENTS.md`, `CLAUDE.md`, `SKILL.md`, and MCP config files.
- Added normalized plugin registry metadata including source URL, compatibility tags, capabilities, permissions, and trust.
- Enabled plugin MCP servers to contribute to runtime config at load time with collision-safe names.
- Updated plugin compatibility docs, generated references, and release coverage.

## 0.24.0

- Added Markdown agent definitions from `.magent/agents/*.md`, user config agents, built-ins, and enabled plugin agent packs.
- Added manual agent invocation with `@review`, `@explore`, `@docs`, and custom agent names.
- Added project hook automation for pre/post tool calls, post-edit events, command failures, memory candidates, and release checks.
- Added LSP-aware code intelligence commands for status, symbols, diagnostics, definitions, and references, with bounded local fallbacks.
- Added a durable local background queue with `magent daemon` for asks, recipes, plans, shell tasks, followups, and gateway background work.
- Added local plugin packaging commands for installable packs containing agents, recipes, skills, tools, and MCP configuration.
- Updated packaged docs, repo docs, architecture docs, generated references, and release tests for the new extension systems.

## 0.21.0

- Added provider UX commands: `magent provider matrix`, `explain`, `env`, `recommend`, and `catalog-doctor`.
- Added generated provider reference docs with `magent docs generate-providers`.
- Added config safety commands: `magent config show`, `backup`, `list-backups`, `diff`, and `restore`.
- Improved project command inference for uv, Poetry, tox, nox, pnpm, bun, and Deno projects.
- Began CLI command extraction with focused provider and config command registration modules.
- Added provider catalog validation and tests to prevent provider metadata drift.

## 0.20.0

- Added first-class setup/UX support for LM Studio, AWS Bedrock, Mistral AI, DeepSeek, xAI, Perplexity, Cerebras, Together AI, Fireworks AI, and DeepInfra.
- Added a shared provider catalog so setup choices, default models, environment variables, access modes, display names, base URLs, and runtime prefixes stay in sync.
- Expanded LiteLLM runtime routing for `mistral`, `deepseek`, `xai`, `perplexity`, `cerebras`, `together_ai`, `fireworks_ai`, and `deepinfra`.
- Updated provider docs, PRD provider tables, and tests for the expanded provider surface.

## 0.19.0

- Added guided UX flows: `magent onboard`, `magent next`, `magent doctor --fix`, `magent doctor --json`, and profile presets.
- Added provider/model/memory/subagent wizard commands for interactive CLI-first setup.
- Added `magent project init` and `magent project wizard` to bootstrap `.magent/config.toml` and `.magent/playbook.toml`.
- Added explicit provider access modes so OpenAI API, OpenAI Codex via ChatGPT plan, OpenCode Zen pay-as-you-go, and OpenCode Go subscription are distinct in setup and diagnostics.
- Updated OpenCode Go defaults to use the Go subscription endpoint and environment variable.

## 0.18.0

- Added CLI-first configuration commands for providers, model roles, memory behavior, gateway tokens, and sub-agent caps.
- Added `magent configure` as a friendlier alias for the first-run setup wizard.
- Added provider/model/gateway/subagent doctor surfaces so users can inspect readiness without hand-editing TOML.
- Made sub-agent orchestration limits configurable and enforced by the sub-agent runner.
- Updated packaged and repository docs for provider, memory, gateway, model-role, and sub-agent setup flows.

## 0.16.0

- Added sandboxed plan and recipe execution with worktree, copy, and Docker container modes.
- Added local eval suite scaffolding and reports with `magent eval`.
- Added optional Playwright browser snapshot and screenshot commands plus agent tools.
- Added GitHub issue, PR, and checks commands backed by the authenticated `gh` CLI.
- Upgraded the local UI into a cockpit view with pending plans, memory inbox, recipes, sandbox runs, failed commands, and release checks.
- Added comparison docs, sandbox/eval/browser/GitHub docs, repo screenshot/demo assets, and recipe examples.
- Continued modularization with sandbox, eval, browser, GitHub, cockpit, and tool capability helper modules.

## 0.15.0

- Added workflow recipes with `magent recipe list/show/save/run`, including built-in release prep, bug triage, docs audit, dependency upgrade, and test repair routines.
- Added `.magent/playbook.toml` support plus `magent project playbook` for project-specific command routines, release checklists, review rules, and context defaults.
- Added `magent memory inbox` to review, accept, reject, and edit memory candidates before writing to MagGraph.
- Added tool capability packs with `magent tools list/explain/enable/disable` and runtime filtering for files, shell, web, data, db, and desktop tools.
- Added actionable local UI endpoints and controls for memory promotion, release checks, patch previews, and checkpoint diffs.
- Updated architecture documentation to explain recipes, playbooks, tool packs, memory inbox, and shared UI action handlers.

## 0.14.3

- Added `magent.cli.command_context` as the shared helper surface for future CLI command modules.
- Added workbench domain modules for plans, patches, checkpoints, project helpers, code/test intelligence, and release/workspace helpers.
- Added tool helper modules for shared tool result types, budgets, schema building, and archive extraction safety.
- Added typed record helpers for tasks, plans, and memory-promotion candidates.
- Updated context promotion to write through the typed promotion candidate record.
- Expanded architecture and compatibility tests for command context, workbench domains, tool helpers, and typed records.

## 0.14.2

- Extracted Typer app and command-group composition into `magent.cli.app` while preserving `magent.cli.main:app`.
- Added compatibility coverage for the shared CLI app object and registered command groups.
- Updated architecture documentation to reflect CLI app composition as a separate boundary.

## 0.14.1

- Moved the tool executor implementation into `magent.tools.executor` while preserving `from magent.tools import ToolExecutor`.
- Extracted JSON-backed workbench storage primitives into `magent.workbench_store` while preserving `from magent.workbench import WorkbenchStore`.
- Added packaged architecture documentation for memory, workbench, context, tools, CLI/TUI, and compatibility boundaries.
- Added compatibility tests for public tool and workbench imports.

## 0.14.0

- Added `magent context map` to show memory, workbench, project doctor, command-role, and promotion-candidate state together.
- Added `magent memory promote` to list or promote workbench facts into durable MagGraph memory.
- Added promotion candidates for project command profiles, open tasks, pending/failed plans, command failures, and review findings.
- Added packaged context-map documentation and tests for context aggregation, promotion, and CLI flows.

## 0.13.0

- Polished the Rich terminal UI with a compact adaptive startup banner and shared `TuiTheme` styles.
- Added reusable status and error line renderers for checkpoint, memory, command, and agent events.
- Updated response rendering to display non-streamed answers in a `MagAgent` Markdown panel.
- Changed streaming output to avoid duplicating the final answer by default while retaining an opt-in final Markdown render.
- Added packaged terminal UI documentation and capture-based TUI tests.

## 0.12.0

- Added `magent ui`, a live local operations dashboard served on `127.0.0.1`.
- Added read-only UI endpoints for workspace state, docs search/topic reads, release checks, and release notes.
- Added packaged `ui` documentation and updated command docs, tutorial, workbench docs, and README references.
- Added unit coverage for UI state aggregation, rendered HTML, local HTTP serving, and CLI startup behavior.

## 0.11.0

- Added patch-first workflow commands: `magent patch preview` and `magent patch explain`.
- Added project command roles and `magent project doctor`.
- Added `magent workspace status` and `magent workspace clean-report`.
- Added `magent release check` and `magent release notes`.
- Added `magent review --fail-on <priority>` for scriptable review gates.
- Added packaged patch workflow documentation.
- Improved review summaries with scriptable failure thresholds.

## 0.10.0

- Added reliability-focused test coverage for the agent loop, CLI smokes, config, providers, DB tools, logging, memory quality controls, and tool behavior.
- Improved `magent plan-apply` with `--dry-run`, saved stdout/stderr excerpts, and failed status reporting when operations or checks fail.
- Expanded test intelligence to cover `*_test.py`, JS/TS `.test.*`, Go `_test.go`, and Rust `_test.rs` patterns.
- Added `magent test explain <file>` to show why related tests were selected.
- Added project-local `{tests}` command template support for targeted test runs.
- Added `magent memory merge --preview` and `magent memory unsuppress`.
- Fixed related-code/test lookups for absolute paths inside the project.
- Fixed SQLite table listing so user tables are no longer hidden by SQL wildcard behavior.

## 0.9.0

- Added code intelligence index commands.
- Added test mapping and related-test commands.
- Added memory quality controls.
- Added provider role config and built-in tutorial documentation.
