# MagAgent 1.1.1

Released on 2026-08-31.

This release moves every interactive execution surface onto the Agent Approval Interchange
Specification (AAIS) 1.0. Chats, bot and group work, delegated subagents, graph tools, and graph
gates now remain operable from the Web UI without hidden terminal prompts. Third-party presenters
can use the digest-bound NDJSON standard-input/standard-output transport.
Each protected tool request binds the decision digest to the normalized tool name and complete
argument object; a changed action requires a new decision.

## Validation

- Full Python suite: 1,080 passed and 6 skipped; the 16 loopback socket tests were rerun outside
  the restricted sandbox and passed.
- Focused AAIS authority, Web run, graph, permission, and cancellation tests.
- Web UI unit suite and production build.
- Wheel and source archive build with Twine metadata validation.
