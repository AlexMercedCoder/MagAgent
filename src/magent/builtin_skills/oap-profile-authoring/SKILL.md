---
name: oap-profile-authoring
description: Generate, validate, review, and safely activate portable Open Agent Profile 1.0 specialists.
version: 1.0.0
tools-required: create_agent_profile
trigger-keywords: ["profile", "specialist", "subagent", "agent identity", "OAP"]
---

# OAP profile authoring

Use `create_agent_profile` when the user asks for a reusable specialist or when a bounded
subagent identity would materially improve the task.

- Describe the role precisely and request only locally available capabilities.
- Never invent tools, skills, MCP servers, commands, credentials, or state.
- A self-directed call must create a reviewable proposal. Do not set `save` merely because the
  model believes saving is useful.
- When the user explicitly asks to create and save a profile, set `save: true`; the normal
  permission boundary still decides whether persistence is allowed.
- Keep `lifecycle.writeback` at `propose` and preserve harness policy as the authority ceiling.

Portable user profiles may be placed in `~/.agentprofiles`; project profiles remain the safest
default because their intended workspace is explicit.
