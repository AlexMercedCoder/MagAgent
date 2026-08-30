# Open Agent Profiles

MagAgent `0.99.0` implements Open Agent Profile (OAP) 1.0 Level 3 harness support using
`open-agent-profile>=1.0.1,<2`. Profiles are portable agent identities with composition, role
instructions, model preferences, bounded tools, MCP servers, skills, memory stores, delegated
agents, runtime limits, and reviewable agent-scoped state. Existing MagAgent Markdown agent
definitions continue to load through the compatibility boundary without modification.

## Start Here

```bash
magent profile wizard
magent profile default
magent profile set-default reviewer
magent agent create reviewer --description "Project reviewer"
magent agent list
magent agent explain reviewer
magent agent schema
magent --agent reviewer
magent ask --agent reviewer "Review the current diff"
```

`magent profile wizard` is the recommended authoring path. It creates a validated OAP
document and guides you through the profile name, description, annotations, role instructions,
persona, objectives, constraints, inheritance, provider and model, tools, MCP servers, skills,
permission mode, network access, memory stores, runtime role, subagent limits, context budget,
lifecycle hooks, and state writeback. Profiles can be stored for the current user, in
`.magent/agents/`, or in the portable `.agents/` directory. The final prompt optionally makes
the new profile the default.

Desktop editors and other machine clients use the versioned
`magent.oap-profile.v1` contract instead of rewriting Markdown or YAML directly:

```bash
magent agent schema --project .
magent agent preview --input profile.json --project .
magent agent apply --input profile.json --scope project --project .
magent agent revisions reviewer --project .
magent agent detail reviewer --project .
magent agent restore-revision reviewer CHECKPOINT --expected-digest DIGEST --project . --yes
magent agent clone reviewer reviewer-copy --scope user --project .
magent agent export reviewer --output reviewer.md --project .
```

`preview` shows inherited and effective authority plus missing local skills, MCP servers,
tools, and subagents. Updates require the digest returned when the profile was opened.
Behavior edits preserve runtime-owned state and proposals, append revision history, and
create a rollback checkpoint before writing atomically. Import and export never include
secret-like extension fields.

Web access has two independent profile checks. `spec.tools.allow` must include `web` or the
specific web tools, and `spec.permissions.network` must be `read` or `full`. Use `read` for web
search, deep research, page fetching, and browser inspection. Use `full` only when the profile
must make arbitrary HTTP requests or network writes. `none` removes all network tools even when
the tool allowlist contains `web`. This `network` field is a MagAgent OAP extension and remains
bounded by the active harness permission mode and enabled capability packs.

```yaml
spec:
  tools:
    allow: [read, search, web]
  permissions:
    default: balanced
    network: read
```

Every installation includes a managed `magagent` profile, and it is the out-of-box default. Its
general coding and productivity personality is injected into ordinary REPL and `ask` sessions.
`magent profile set-default NAME` changes the active user's default; add `--global` to change the
installation fallback. `magent profile clear-default` removes a user override. An explicit
`--agent NAME` wins for one session, while `--agent none` temporarily disables profile injection.

The older `magent profile list` and `magent profile apply NAME` commands remain configuration
preset shortcuts for provider, memory, and subagent settings. OAP inspection and state commands
remain under `magent agent`.

Inside an ordinary interactive session, `@review task` activates that profile for one turn and restores the prior session policy afterwards.

## Discovery And Trust

Profiles resolve by precedence: project profiles in `.magent/agents/`, portable project profiles in
`.agents/`, native user profiles in `~/.config/magent/agents/`, universal user profiles in
`~/.agentprofiles/`, enabled plugin `agents/` directories, then managed built-ins. Earlier entries
win and collisions are reported. Duplicate names in one root are errors. Trust is derived from the
root, so a project file cannot become managed by declaring `metadata.trust`.

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

Authoring revisions are separate from state-delta history. Use `agent revisions` to list
editor checkpoints and `agent restore-revision` for digest-guarded restoration. The older
`agent rollback` remains the low-level state-checkpoint command.

## Legacy Compatibility And Conversion

Legacy YAML-frontmatter agents are converted in memory on each read and are never rewritten as a side effect. Preview or explicitly apply conversion with:

```bash
magent agent convert .magent/agents/reviewer.md
magent agent convert .magent/agents/reviewer.md --write
```

`--write` creates a `.legacy.bak` backup first.

## Commands

`magent profile` provides `wizard`, `default`, `set-default`, and `clear-default` for OAP setup,
plus `list` and `apply` for guided configuration presets. `magent agent` provides `list`, `show`,
`schema`, `preview`, `apply`, `clone`, `import`, `export`, `delete`, `detail`, `revisions`,
`restore-revision`, `explain`, `validate`, `create`, `convert`, `state`, `history`, `rollback`, `forget`, `inbox`,
`accept`, `reject`, `digest`, `conformance`, and the compatibility `run` renderer. Run
`magent agent conformance` offline to inspect packaged Level 3 behavioral evidence.

## Current Conformance Boundary

Version 0.99.0 enforces the Level 3 surface in interactive sessions, asks, research, recipes,
graph agent nodes, subagents, goals, daemon work, and gateways. CI pins the canonical upstream OAP
repository at commit `7fb633a1a59dd7636ffb0030d254f2f58934f74a`, validates its examples, and runs
MagAgent's behavioral profile suite. Canonical documents and `AgentStateDelta` records use the
1.0 schemas and RFC 8785 digests; legacy MagAgent definitions are converted at the compatibility
boundary. See the [machine-readable result](https://github.com/AlexMercedCoder/MagAgent/blob/main/docs/oap-conformance.json). Optional
requirements L2-A14 and L3-M2 are not claimed. This is implementation evidence, not third-party
certification.
