# MagAgent 0.97.0

Status: released 2026-08-22.

MagAgent 0.97.0 turns `magent ui` into a lightweight local alternative to Mag Command Center
while retaining the CLI's existing runtime, profile, graph, and operations contracts.

## Highlights

- durable traditional chat with multiple conversations
- profile-backed bot conversations and coordinated groups of two to five bots
- browser-based Open Agent Profile creation and effective-authority inspection
- schema-guided non-secret defaults and settings
- a fixed **To do**, **Current work**, and **Done** Graph Kanban
- blank graph creation with editable task cards, profiles, and dependencies
- review-only graph generation from a natural-language goal using the configured planning model
- strict native `.agraph` validation, project-confined saving, and digest conflict protection
- real background execution through `GraphExecutor` with gate review and terminal card summaries

AI-generated graphs remain proposals until the user reviews, saves, validates, and explicitly
runs them. The UI does not introduce a second graph format or bypass MagAgent's task, profile,
permission, event, and run-record contracts.

## Security

The Web UI binds only to loopback. Each launch creates a random authorization token, mutation
requests require the matching CSRF header, and state-changing or model-spending endpoints reject
GET. Host and Origin checks, bounded JSON requests, a restrictive content security policy,
clickjacking protection, no-store caching, and project path containment protect the local surface.
Secret-bearing settings are not returned to the browser.

## Validation

- The sandboxed full suite completed with 912 passes, one loopback-dependent skip, and 11
  session-messaging failures caused exclusively by sandbox denial of `socket.socket` before
  application code ran. The complete socket-dependent messaging and live Web UI set then passed
  22/22 with loopback permission.
- Ruff passed across `src` and `tests`; MyPy passed across 202 source files; documentation drift,
  generated command references, JavaScript syntax, version consistency, and diff checks passed.
- The source distribution and wheel built as `0.97.0` and passed Twine metadata validation. Wheel
  inspection found all required Python modules, Web UI assets, and packaged documentation.
- A clean virtual environment installed the wheel with its declared dependencies and passed CLI
  version, packaged docs, packaged-asset, rendered-control, and strict graph smoke checks.
- The credential-free security report passed command policy, SSRF/network policy, path
  containment, fail-closed gateway defaults, and atomic persistence probes.
- live browser authoring of a three-card graph with three profiles and chained dependencies
- strict inspection of the saved graph, including generated dependency inputs and final outputs

Screenshots are recorded under [`docs/screenshots/webui`](screenshots/webui/).
