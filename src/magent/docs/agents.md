# Open Agent Profiles

MagAgent implements provisional Open Agent Profile (OAP) v1 Level 3 harness support. Profiles are portable agent identities with composition, role instructions, model preferences, bounded tools, MCP servers, skills, memory stores, delegated agents, runtime limits, and reviewable agent-scoped state. Existing MagAgent Markdown agent definitions continue to load without modification.

## Start Here

```bash
magent agent create reviewer --description "Project reviewer"
magent agent list
magent agent explain reviewer
magent --agent reviewer
magent ask --agent reviewer "Review the current diff"
```

Inside an ordinary interactive session, `@review task` activates that profile for one turn and restores the prior session policy afterwards.

## Discovery And Trust

Profiles resolve in this order: user profiles in `~/.config/magent/agents/`, project profiles in `.magent/agents/`, portable profiles in `.agents/`, enabled plugin `agents/` directories, then managed built-ins. Higher entries win and collisions are reported. Duplicate names in one root are errors. Trust is derived from the root, so a project file cannot become managed by declaring `metadata.trust`.

## OAP Markdown Format

```markdown
---
oap: "1.0"
extends: base-reviewer
metadata:
  name: reviewer
  description: Reviews code for correctness and regressions
  revision: 1
spec:
  role:
    constraints:
      - Report correctness and security findings before style notes.
  model:
    provider: nous
    id: deepseek-v4-flash
  tools:
    allow: [read_file, read_file_range, outline_file, search_codebase]
    deny: [write_file, edit_file, delete_file, run_shell]
    mcp_servers: [github]
    skills: [review]
  permissions:
    default: paranoid
  runtime:
    mode: subagent
    max_turns: 8
    subagents:
      allow: [docs]
      max_subagents: 1
      max_parallel: 1
      max_depth: 1
  memory:
    stores:
      - {name: profile-state, kind: oap-state, mode: read_write}
      - {name: user-graph, kind: maggraph, mode: read}
  context:
    budget:
      max_state_tokens: 600
state: []
history: []
proposals: []
lifecycle:
  writeback: propose
---

You are a focused reviewer. Cite concrete files and explain impact.
```

JSON and YAML encodings are also accepted. Use `magent agent validate PATH` before sharing a profile.

## Security Model

Profiles only narrow authority. Tool allow and deny patterns are intersected with tools enabled by MagAgent. Permission modes and runtime budgets can become more restrictive but never less restrictive. Context paths escaping the active workspace are rejected after symlink resolution.

`extends` accepts one profile name or a list. Parents resolve before children, cycles and missing parents are rejected, and every inherited capability is intersected rather than merged. `magent agent show NAME` reports lineage and a resolution digest; `magent agent explain NAME` reports the final tools, MCP servers, skills, memory modes, delegation limits, and every adjustment.

MCP and skill references select only locally configured capabilities. A profile cannot install a server, skill, or plugin. Delegated profiles are intersected with the parent's already-effective authority, including tools, permissions, MCP, skills, memory, budgets, concurrency, and remaining depth.

Profile state is injected in a delimited `trust="untrusted"` block. It is background information, not instruction, and cannot change tools, permissions, model policy, or safety rules. Credential-shaped text is scrubbed before injection and before a state delta is stored.

Profiles may name locally configured lifecycle hooks, but never contain command lines. Define commands under `[named.<hook>]` in `.magent/hooks.toml`, then reference that hook name from `lifecycle.on_start` or `lifecycle.on_end`.

## Reviewable State

Agent-scoped state describes how that agent performs its job. User preferences and project facts still belong in MagGraph. State changes are proposed and reviewed:

```bash
magent agent state reviewer
magent agent inbox
magent agent accept oap_delta_123 --rebase
magent agent reject oap_delta_456 --reason "Not agent-specific"
magent agent forget reviewer obsolete-entry
magent agent history reviewer
```

Every accepted delta is limited to `/state`, verifies the source revision and digest, scrubs secrets, increments the revision once, appends history, creates a profile checkpoint, and writes atomically. `--rebase` accepts an unrelated concurrent state change but rejects edits to the same target. Proposals are never automatically accepted, including under `writeback: auto`. Restore a checkpoint with `magent agent rollback NAME CHECKPOINT`.

## Legacy Compatibility And Conversion

Legacy YAML-frontmatter agents are converted in memory on each read and are never rewritten as a side effect. Preview or explicitly apply conversion with:

```bash
magent agent convert .magent/agents/reviewer.md
magent agent convert .magent/agents/reviewer.md --write
```

`--write` creates a `.legacy.bak` backup first.

## Commands

`magent agent` provides `list`, `show`, `explain`, `validate`, `create`, `convert`, `state`, `history`, `rollback`, `forget`, `inbox`, `accept`, `reject`, `digest`, `conformance`, and the compatibility `run` renderer. Run `magent agent conformance` offline to inspect packaged Level 3 behavioral evidence.

## Current Conformance Boundary

Version 0.93.0 declares provisional OAP v1 Level 3 harness support. The complete supplied Level 3 surface is enforced in interactive sessions, asks, subagents, goals, daemon work, and gateways. The declaration remains provisional because the canonical upstream OAP repository and reference conformance corpus were not publicly discoverable when this release was prepared; MagAgent ships its offline schema and behavioral fixtures without claiming unverifiable upstream certification.
