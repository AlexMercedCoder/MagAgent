# Agent Definitions

MagAgent supports reusable agent definitions from Markdown files.

## Locations

- built-in agents: `review`, `explore`, and `docs`
- user agents: `~/.config/magent/agents/*.md`
- project agents: `.magent/agents/*.md`
- enabled plugin agents: `<plugin>/agents/*.md`

Project agents override user agents with the same name, and user agents override built-ins.

## Format

Agent files use YAML front matter plus a Markdown prompt body:

```markdown
---
description: Reviews code for regressions and missing tests
mode: subagent
provider: openai
model: gpt-5
tools:
  - files
  - shell
permission_mode: on-request
memory_mode: read
max_turns: 8
---

You are a focused reviewer. Prioritize correctness, tests, and maintainability.
```

## CLI

- `magent agent list`
- `magent agent show review`
- `magent agent create docs --description "Documentation specialist"`
- `magent agent run review "inspect the current diff"`

## Manual Invocation

In chat or one-shot prompts, start a task with an agent mention:

```bash
magent ask "@review inspect this diff for regressions"
magent ask "@explore map the auth module"
magent ask "@docs update the README for the new CLI"
```

The invocation expands into the selected agent's prompt and task. Agent metadata is also placed in scratchpad state so later runtime layers can reason about the active agent.

## Primary Agents And Subagents

Use `mode: primary` for a main persona and `mode: subagent` for focused specialists. Per-agent fields can specify provider/model preferences, tool capability names, permission mode, memory mode, and max turns. The current runtime treats those settings as explicit metadata and prompt constraints; provider/tool enforcement can be tightened further as the orchestration layer grows.
