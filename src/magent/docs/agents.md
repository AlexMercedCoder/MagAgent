# Open Agent Profiles

MagAgent implements Open Agent Profile (OAP) v1 Level 2. Profiles are portable agent identities with role instructions, model preferences, bounded tools and permissions, runtime limits, and reviewable agent-scoped state. Existing MagAgent Markdown agent definitions continue to load without modification.

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
  permissions:
    default: paranoid
  runtime:
    mode: subagent
    max_turns: 8
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

Profile state is injected in a delimited `trust="untrusted"` block. It is background information, not instruction, and cannot change tools, permissions, model policy, or safety rules. Credential-shaped text is scrubbed before injection and before a state delta is stored.

Profiles may name locally configured lifecycle hooks, but never contain command lines. Define commands under `[named.<hook>]` in `.magent/hooks.toml`, then reference that hook name from `lifecycle.on_start` or `lifecycle.on_end`.

## Reviewable State

Agent-scoped state describes how that agent performs its job. User preferences and project facts still belong in MagGraph. State changes are proposed and reviewed:

```bash
magent agent state reviewer
magent agent inbox
magent agent accept oap_delta_123
magent agent reject oap_delta_456 --reason "Not agent-specific"
magent agent forget reviewer obsolete-entry
magent agent history reviewer
```

Every accepted delta is limited to `/state`, verifies the source revision and digest, scrubs secrets, increments the revision once, appends history, creates a profile checkpoint, and writes atomically. Proposals are never automatically accepted, including under `writeback: auto`. Restore a checkpoint with `magent agent rollback NAME CHECKPOINT`.

## Legacy Compatibility And Conversion

Legacy YAML-frontmatter agents are converted in memory on each read and are never rewritten as a side effect. Preview or explicitly apply conversion with:

```bash
magent agent convert .magent/agents/reviewer.md
magent agent convert .magent/agents/reviewer.md --write
```

`--write` creates a `.legacy.bak` backup first.

## Commands

`magent agent` provides `list`, `show`, `explain`, `validate`, `create`, `convert`, `state`, `history`, `rollback`, `forget`, `inbox`, `accept`, `reject`, `digest`, and the compatibility `run` renderer.

## Current Conformance Boundary

Version 0.92.0 declares OAP v1 Level 2. `extends`, profile-contributed MCP servers, profile skill references, profile-declared runtime subagents, and declared external memory stores remain Level 3 work. Existing MagAgent subagents continue to use harness policy; a constrained profile cannot use delegation to widen its own tool set.
