# MagAgent 1.1.0 — Release Record

Released on 2026-08-30.

MagAgent 1.1.0 completes the profile-authoring, graph-observability, provider-onboarding, and
extension-management pass begun after 1.0. It adds portable prompt-generated OAP specialists,
universal profile discovery at `~/.agentprofiles`, and native alexmerced.app WebMCP tools.

The local UI now preserves graph drafts and active runs across navigation, exposes bounded planning
and execution activity, edits every card capability, explains validation/runtime failures, and
provides reviewed lifecycle controls for profiles, memory, plugins, skills, MCP servers, providers,
and credentials. Managed profiles remain read-only and all generated profiles pass the same OAP
validation and authority boundary as hand-authored documents.

Validation requires Ruff formatting/lint, mypy, the complete Python suite, the React suite and
production build, package build, Twine metadata validation, and an installed-wheel smoke test.
