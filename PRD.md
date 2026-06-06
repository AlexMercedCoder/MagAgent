# MagAgent — Product Requirements Document (PRD)

> **Decisions resolved:** 2026-06-05 — All open questions from §21 have been answered and folded into the spec.

> **Version:** 0.1 — Draft  
> **Date:** 2026-06-05  
> **Author:** AI Research (Antigravity)  
> **Status:** In Review

---

## 1. Executive Summary

**MagAgent** is an open-source, terminal-native AI coding agent that combines the best ideas from OpenCode and Hermes with a unique differentiator: a **persistent, per-user knowledge graph** powered by [MagGraph](https://github.com/AlexMercedCoder/MagGraph) — a Rust-powered, in-process graph database that stores memory as plain Markdown nodes in Git.

Unlike traditional agents that treat every session as stateless, MagAgent continuously writes what it learns about you, your projects, your preferences, and your patterns into a structured memory graph. Over time it becomes genuinely smarter about *your* workflow. The graph is human-readable, version-controlled, auditable, and lives entirely on your machine.

---

## 2. Problem Statement

| Pain Point | Status Quo | MagAgent Solution |
|---|---|---|
| No persistent memory across sessions | Every session starts cold | MagGraph stores structured knowledge indefinitely |
| Locked to one model/provider | Many agents favor one provider | Provider-agnostic layer; 10+ providers |
| Single-user assumption | Agents configured per-install | Multi-user profiles, each with isolated memory graph |
| Permission fatigue | Ask permission for every action | Risk-tiered automation model (silent / auto / confirm / block) |
| Opaque internal state | No insight into what agent "knows" | `magent memory stats` command: node/edge counts, disk usage |
| No extensibility | Skills require hacky workarounds | First-class SKILL.md skill system |
| No parallelism | Single-threaded reasoning | Sub-agent orchestration with isolated scopes |

---

## 3. Goals & Non-Goals

### Goals

- Build a **production-quality CLI agent** optimized for software development tasks.
- Use **MagGraph** as the sole memory backend — no external databases required.
- Support **multi-user** operation: each user has an isolated MagGraph directory.
- Support **all major AI providers** via an OpenAI-compatible interface abstraction, with first-class support for Nous Portal, OpenCode Zen, Ollama, OpenAI, Anthropic, Google, and more.
- Implement a **skill system** (SKILL.md files) for extending agent capabilities.
- Implement a **sub-agent system** for parallelizing complex tasks.
- Balance safety and ergonomics with a **risk-tiered permission model**.
- Provide **graph auditability**: stats, export, diff, and search commands.
- Be fully **local-first**: the agent runs without any cloud service beyond the chosen LLM provider.

### Non-Goals (v1)

- Web UI or GUI (terminal-only for v1)
- IDE extensions (VS Code, JetBrains) — v2
- Cloud-hosted memory sync — v2 (MagGraph's Git sync can be used manually)
- Real-time collaboration between users on a shared graph
- Training fine-tuned models from user memory

---

## 4. Target Users

| User Persona | Description |
|---|---|
| **Solo Developer** | Uses MagAgent as their primary AI coding assistant; values that it remembers their patterns and preferences across projects. |
| **Multi-Project Developer** | Switches between multiple projects and uses multiple user profiles per project context. |
| **Privacy-Conscious Developer** | Wants local-only AI with no telemetry; values that memory stays in plain Markdown on disk. |
| **AI Power User** | Wants to compose sub-agents, author custom skills, and audit the memory graph. |

---

## 5. Product Overview

### 5.1 Core Agent Loop

```
User Input
    │
    ▼
[Memory Recall] ← MagGraph traversal of relevant nodes
    │
    ▼
[Planning] → Task decomposition, mode selection
    │
    ├─► [Tool Execution] → File ops, shell, LSP, web search
    │       │
    │       └─► [Permission Gate] → risk-tiered approval
    │
    ├─► [Sub-Agent Dispatch] → isolated child agents
    │
    └─► [Memory Write] → create/update MagGraph nodes post-task
            │
            ▼
        Response to User
```

### 5.2 CLI Interface

MagAgent is invoked from the terminal:

```bash
# Interactive REPL (default)
magent

# One-shot task
magent ask "Refactor the auth module to use JWTs"

# Target a specific project
magent --project ~/code/myapp

# Switch user profile
magent user switch alice

# Show graph stats for current user
magent memory stats

# Run with a specific provider
magent --provider nous-portal --model hermes-4
```

The interactive mode presents a polished TUI built with **Rich** (Python) with:
- Multi-line input with syntax highlighting
- Streaming token output
- Slash-command palette (`/help`, `/memory`, `/skills`, `/model`, `/user`, `/mode`)
- Tool-call audit trail (collapsible)
- Permission prompts for risky actions (minimally interrupting)

---

## 6. Technical Architecture

### 6.1 Technology Stack

| Layer | Technology | Rationale |
|---|---|---|
| **Language** | Python 3.12+ | Fastest path to a great CLI agent; rich ecosystem; maggraph has native Python bindings |
| **CLI framework** | [Typer](https://typer.tiangolo.com/) + [Rich](https://rich.readthedocs.io/) | Modern, fast CLI + beautiful TUI output |
| **Memory backend** | [MagGraph](https://github.com/AlexMercedCoder/MagGraph) (`pip install maggraph`) | In-process, Rust-powered, Markdown-native graph DB |
| **LLM abstraction** | [LiteLLM](https://github.com/BerriAI/litellm) | OpenAI-compatible adapter for 100+ providers |
| **Sub-agent runner** | `asyncio` + `concurrent.futures` | Lightweight parallel agent execution |
| **Config** | TOML (`~/.config/magent/config.toml`) | Human-readable; per-user sections |
| **Skills** | SKILL.md files in `~/.config/magent/skills/` | Extensible without code changes |
| **Packaging** | `pip install magent` / standalone binary via PyInstaller | Zero friction installation |

### 6.2 Directory Structure

```
~/.config/magent/
├── config.toml              # Global config (providers, defaults)
├── users/
│   ├── current              # File containing active username
│   ├── alice/
│   │   ├── profile.toml     # User-specific settings
│   │   └── memory/          # MagGraph root for alice
│   │       ├── maggraph.toml
│   │       ├── preferences.md
│   │       ├── projects/
│   │       └── skills_learned/
│   └── bob/
│       ├── profile.toml
│       └── memory/
├── skills/                  # Global skills available to all users
│   ├── git-workflow/
│   │   └── SKILL.md
│   └── docker-debugging/
│       └── SKILL.md
└── logs/
    └── sessions/            # Append-only JSONL session logs
```

### 6.3 MagGraph Memory Integration

MagGraph is the core innovation in MagAgent's memory architecture. Each user's memory lives in a Git-tracked directory of Markdown files that form a knowledge graph.

#### Node Types Used by MagAgent

| Node Type | Purpose | Example ID |
|---|---|---|
| `preference` | User coding preferences (language, style, tools) | `prefers_typescript` |
| `project` | Project-level metadata (tech stack, conventions) | `project_myapp_backend` |
| `pattern` | Recurring code patterns the user likes/dislikes | `pattern_avoid_callbacks` |
| `skill_learned` | Skills the agent has internalized | `skill_docker_debugging` |
| `fact` | General facts the agent has learned | `fact_user_uses_neovim` |
| `session_summary` | Summary of a past session | `session_2026_06_05` |
| `error_pattern` | Recurring errors and their solutions | `error_jwt_expiry` |
| `contact` | People / team members mentioned by user | `contact_alice_infra` |
| `bookmark` | Useful URLs the agent found during tasks, for possible reuse | `bookmark_jwt_rfc` |

#### Memory Write Strategy (Post-Task)

Memory writes are triggered at two points:

1. **Every N user turns** (default: 5, configurable via `memory.write_every_n_turns`)
2. **At the end of every session** (always, regardless of turn count)

On each write trigger, the agent:

1. Runs a **memory extraction pass** — a lightweight LLM call (model is configurable; see §7.3) asking: *"What facts, preferences, patterns, project relationships, and useful URLs should be stored or updated in my memory graph?"*
2. Creates/updates the appropriate nodes via `index.create_node()` / `index.update_node()`.
3. Establishes edges via `[[wikilinks]]` in node bodies, with explicit project-linking (see §6.4).
4. Optionally commits the memory directory to Git (if `sync.auto_commit = true` in config).

The memory extraction model is configurable independently of the main agent model (e.g., a local 7B for extraction cost savings, a larger cloud model for main reasoning). See `memory.extraction_model` in §15.

#### Memory Read Strategy (Pre-Task)

Before processing a user request, the agent:

1. Identifies 1–3 **anchor nodes** most relevant to the request (via keyword matching against node IDs and body text).
2. Calls `index.traverse(anchor, depth=2, order="bfs")` to collect related memory nodes.
3. Injects compact node matches first, then a few budgeted node excerpts.
4. Caps injected memory at a configurable token budget (default: 4000 tokens).

### 6.4 Project Linking Convention

All memory uses a **flat user graph** (no separate per-project subgraph). However, the agent is instructed to consistently:

- Tag every node's body with a `Project: [[project_<slug>]]` wikilink when the node is clearly project-specific.
- Create a `project_<slug>` node as the canonical hub for each project.
- Prefer explicit `[[wikilinks]]` over frontmatter links so the graph naturally clusters around project hubs.

This keeps the structure simple while making project-scoped traversal (`magent memory traverse project_myapp --depth 3`) immediately useful.

### 6.5 Bookmark Nodes

When the agent fetches or references a URL that proves useful for a task that is likely to recur, it creates a `bookmark` node:

```markdown
---
id: "bookmark_jwt_rfc"
type: "bookmark"
links: ["error_jwt_expiry", "project_myapp_backend"]
url: "https://www.rfc-editor.org/rfc/rfc7519"
tags: ["jwt", "auth", "rfc"]
---
# JWT RFC 7519

Official JWT specification. Useful when debugging token expiry or claims issues.
See also [[error_jwt_expiry]] and [[project_myapp_backend]].
```

Bookmarks are injected into context when a task involves the same tags or linked nodes.

---

## 7. Provider Support

### 7.1 Provider Abstraction

All providers are accessed via **LiteLLM**, which provides a unified OpenAI-compatible interface. Provider config lives in `~/.config/magent/config.toml`.

### 7.2 Supported Providers (v1)

| Provider | ID in Config | Notes |
|---|---|---|
| **Nous Portal** | `nous-portal` | First-class support; OpenAI-compatible at `https://inference-api.nousresearch.com/v1`; access to Hermes 4 series and 200+ models |
| **OpenCode Zen** | `opencode-zen` | Curated coding models; base URL `https://opencode.ai/zen/v1/`; pay-as-you-go |
| **Ollama** | `ollama` | Local models; zero cost; default URL `http://localhost:11434` |
| **OpenAI** | `openai` | GPT-4o, GPT-5 series |
| **Anthropic** | `anthropic` | Claude 3.5 / 4 series |
| **Google Gemini** | `google` | Gemini 1.5 / 2.0 Pro |
| **Groq** | `groq` | Fast inference for open-weight models |
| **OpenRouter** | `openrouter` | Aggregator for 200+ models |
| **AWS Bedrock** | `bedrock` | Enterprise deployments |
| **LM Studio** | `lmstudio` | Local models with GUI; OpenAI-compatible |
| **Custom** | `custom` | Any OpenAI-compatible endpoint |

### 7.3 Provider Configuration

```toml
# ~/.config/magent/config.toml

[providers.nous-portal]
base_url = "https://inference-api.nousresearch.com/v1"
api_key_env = "NOUS_API_KEY"
default_model = "nous-hermes-4"

[providers.opencode-zen]
base_url = "https://opencode.ai/zen/v1"
api_key_env = "OPENCODE_ZEN_KEY"
default_model = "gpt-5"

[providers.ollama]
base_url = "http://localhost:11434"
default_model = "qwen2.5-coder:32b"

[providers.openai]
api_key_env = "OPENAI_API_KEY"
default_model = "gpt-4o"

[defaults]
provider = "ollama"        # Default provider (local-first default)
model = "qwen2.5-coder:32b"

# Memory extraction model (can be cheaper/smaller than main model)
# If unset, falls back to defaults.provider / defaults.model
[memory]
extraction_provider = "ollama"
extraction_model = "qwen2.5:7b"
```

### 7.4 Model Switching

Models can be switched at any time without restarting:

```bash
/model                          # Opens interactive model picker
/model nous-portal/hermes-4     # Direct switch
magent --provider ollama --model deepseek-coder-v3
```

---

## 8. Multi-User System

### 8.1 User Management Commands

```bash
# List all users
magent user list

# Create a new user
magent user create alice

# Switch to a user
magent user switch alice

# Show current user
magent user current

# Delete a user (prompts for confirmation)
magent user delete bob

# Show user's memory graph stats
magent memory stats
magent memory stats --user alice
```

### 8.2 User Isolation

- Each user has a completely independent MagGraph directory under `~/.config/magent/users/<name>/memory/`.
- User profiles can have their own provider preferences, default models, permission settings, and skill overrides.
- Switching users mid-session immediately swaps the active memory context.
- No data crosses between user graphs unless explicitly exported.

### 8.3 User Profile Schema

```toml
# ~/.config/magent/users/alice/profile.toml

[preferences]
default_provider = "nous-portal"
default_model = "nous-hermes-4"
theme = "dark"
memory_budget_tokens = 4000

[permissions]
mode = "balanced"          # silent | balanced | paranoid | yolo
auto_commit_memory = true
allowed_shell_patterns = ["git *", "npm *", "cargo *", "pytest *"]

[memory]
auto_write = true
write_every_n_turns = 5    # also always writes at end of session
max_nodes = 10000
encrypt = false            # set true to enable AES-256 encryption at rest

# Override extraction model for this user (optional)
# extraction_provider = "ollama"
# extraction_model = "llama3.2:3b"
```

---

## 9. Skills System

### 9.1 Overview

Skills extend the agent's capabilities through plain-text SKILL.md files. Skills are discovered automatically from:

1. `~/.config/magent/skills/` — global skills for all users
2. `.magent/skills/` — project-local skills (read when the agent runs in that directory)
3. The user's own memory graph — nodes of type `skill_learned` are injected as lightweight skill summaries

### 9.2 SKILL.md Format

```markdown
---
name: docker-debugging
description: >
  Diagnose and fix Docker container issues including build failures,
  networking problems, and compose stack errors. Activate when the
  user mentions Docker, containers, Dockerfile, or compose files.
tools_required: [shell, file_read]
version: "1.0"
---

# Docker Debugging Skill

## When to Activate
Activate when the user mentions: 'Docker', 'container', 'Dockerfile', ...

## Procedure
1. Run `docker ps -a` to list all containers and their status.
2. Run `docker logs <container_id>` to capture recent output.
...
```

### 9.3 Skill Discovery & Injection

- At session start, the agent scans all skill directories and builds a **skill registry**.
- The skill's `description` field is matched against the user's request using lightweight keyword matching.
- Matching skills have their SKILL.md content injected into the system prompt.
- A maximum of 3 skills are active simultaneously to avoid context bloat.

### 9.4 Auto-Skill Learning

After successfully solving a complex problem, the agent can optionally:

1. Distill the solution into a new SKILL.md file.
2. Store it as a `skill_learned` node in the user's MagGraph.
3. Propose saving it as a persistent skill file for future sessions.

---

## 10. Sub-Agent System

### 10.1 Overview

MagAgent supports spawning **sub-agents** for parallelizing work. Sub-agents are:

- **Isolated**: each has its own conversation context and tool scope.
- **Lightweight**: spawned in-process via `asyncio` (no separate processes for simple tasks).
- **Memory-sharing**: sub-agents can read the parent user's memory graph (read-only by default; write requires explicit permission).
- **Scoped**: sub-agents operate only within an explicitly defined working directory scope.

### 10.2 Sub-Agent Use Cases

| Use Case | Example |
|---|---|
| Parallel file analysis | "Analyze these 5 files simultaneously and summarize each" |
| Research + implementation split | One agent researches the API, another drafts the code |
| Test generation | Spawn a sub-agent to write tests while the main agent implements |
| Multi-file refactoring | Each sub-agent handles one module |

### 10.3 Sub-Agent Slash Command

Users can explicitly spawn sub-agents:

```
/spawn "Write unit tests for the auth module"
/spawn --scope ./frontend "Audit all React components for accessibility"
```

---

## 11. Permission Model

The permission model is the key to balancing safety with developer ergonomics. MagAgent avoids **permission fatigue** by categorizing all agent actions into risk tiers and only interrupting the user for genuinely high-risk operations.

### 11.1 Risk Tiers

| Tier | Risk Level | Default Behavior | Examples |
|---|---|---|---|
| **0 — Silent** | None | Auto-execute, no notification | Read files within CWD, `git status`, `git log`, `ls`, `cat` |
| **1 — Auto** | Low | Execute + show in audit trail | Write/create files within CWD, `git add`, `git commit`, `npm install`, `cargo build` |
| **2 — Confirm** | Medium | Show proposed action, user presses Enter to confirm | Delete files, shell commands outside CWD, `git push`, `curl` to known domains |
| **3 — Block** | High | Requires explicit typed confirmation | `rm -rf`, `sudo`, system-level file writes, network calls to unknown hosts, credential access |

### 11.2 Permission Modes

| Mode | Description | Suitable For |
|---|---|---|
| `silent` | Tiers 0–2 auto-execute; only Tier 3 prompts | Experienced users in trusted environments |
| `balanced` *(default)* | Tier 0–1 auto; Tier 2 confirms; Tier 3 blocks then prompts | Most users |
| `paranoid` | Tier 0 auto; all others prompt | Security-conscious users |
| `yolo` | Everything auto-executes (Tier 3 still shown but one-key confirm) | Local experiments, power users |

```bash
magent mode balanced      # Set permission mode
/mode yolo                # Change in-session
```

### 11.3 Action Allowlist

Users can pre-approve specific shell patterns so they never trigger prompts:

```toml
[permissions]
allowed_shell_patterns = [
  "git *",
  "npm *",
  "cargo *",
  "pytest *",
  "docker compose up *",
]
```

### 11.4 Kill Switch

At any time during agent execution, pressing `Ctrl+C` immediately halts the agent and all sub-agents.

---

## 12. Memory Graph Auditability

### 12.1 `magent memory stats`

```
╔════════════════════════════════════════╗
║     MagAgent Memory Graph Stats        ║
║     User: alice                        ║
╠════════════════════════════════════════╣
║  Nodes                       247       ║
║  Edges (total)               891       ║
║  Edges (wikilink)            312       ║
║  Edges (frontmatter)         579       ║
╠════════════════════════════════════════╣
║  Node Types                            ║
║    preference                 34       ║
║    project                    18       ║
║    pattern                    52       ║
║    skill_learned              11       ║
║    fact                       89       ║
║    session_summary            31       ║
║    error_pattern              12       ║
╠════════════════════════════════════════╣
║  Storage                               ║
║    Graph directory            4.2 MB   ║
║    Avg node size              1.7 KB   ║
║    Largest node               12.4 KB  ║
║    Git history (commits)      143      ║
║    Git history (size)         18.1 MB  ║
╠════════════════════════════════════════╣
║  Activity                              ║
║    Last write                 2h ago   ║
║    Sessions this week         12       ║
║    Nodes created (7d)         23       ║
╚════════════════════════════════════════╝
```

### 12.2 Additional Memory Commands

```bash
magent memory search "JWT authentication"    # Search the memory graph
magent memory show prefers_typescript        # Show a specific node
magent memory traverse project_myapp_backend --depth 3
magent memory delete error_pattern_old       # Delete a specific node
magent memory export --format json --out ~/memory_backup.json
magent memory log --last 20                  # Show recent memory writes
magent memory reset                          # Reset all memory (with confirmation)
magent memory ui                             # Open embedded web dashboard
```

---

## 13. Agent Capabilities (Tools)

### 13.1 Built-in Tools

| Tool | Description | Default Tier |
|---|---|---|
| `read_file` | Read a file preview, truncated for large files | 0 — Silent in project |
| `read_file_range` | Read exact 1-based line ranges | 0 — Silent in project |
| `outline_file` | Show compact source symbols and line numbers | 0 — Silent in project |
| `write_file` | Create/overwrite file within CWD | 1 — Auto |
| `edit_file` | Apply targeted edits (diff-based) | 1 — Auto |
| `delete_file` | Delete file within CWD | 2 — Confirm |
| `run_shell` | Execute a shell command | Varies by command |
| `list_dir` | List directory contents | 0 — Silent |
| `search_codebase` | Grep/ripgrep within project | 0 — Silent |
| `web_search` | Search the web | 1 — Auto |
| `web_fetch` | Fetch a URL | 1 — Auto |
| `memory_read` | Query user's MagGraph | 0 — Silent |
| `memory_write` | Write to user's MagGraph | 0 — Silent (internal) |
| `spawn_subagent` | Spawn a child agent | 1 — Auto |
| `lsp_diagnostics` | Get LSP errors/warnings | 0 — Silent |
| `git_ops` | Git status/log/diff/add/commit | Varies |

### 13.2 MCP Support

MagAgent supports the **Model Context Protocol (MCP)**, allowing users to connect any MCP-compatible server:

```toml
[mcp.servers.filesystem]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-filesystem", "/path"]

[mcp.servers.postgres]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-postgres"]
env = { POSTGRES_URL = "postgresql://..." }
```

---

## 14. Coding-Specific Features

| Feature | Description |
|---|---|
| **Project auto-detection** | Detects language, framework, package manager from project root |
| **Context forking** | Rewind and branch conversation trajectories for complex tasks |
| **Plan & Build mode** | `--plan` flag shows proposed changes before executing |
| **LSP integration** | Surfaces diagnostics from language servers in real time |
| **Test awareness** | Detects test frameworks; auto-runs tests after edits |
| **Git-aware operations** | Understands diffs, staged files, branch status |
| **Multi-file editing** | Edits multiple files atomically with rollback on error |
| **Code search** | Ripgrep-powered codebase search with AST-aware results |

### 14.1 Local Productivity Workbench

MagAgent includes a local-first workbench stored as plain JSON under
`~/.config/magent/users/<username>/workbench/`. This turns MagAgent into a
durable coding and productivity agent rather than a single-session assistant.

Shipped workbench surfaces include:

- Task ledger: `magent task add/list/done/report`
- Artifact tracking: `magent artifact add/list/show/open/checksum`
- Project profiles: `magent project profile/list/commands/config/command-history/command-promote`
- Local inbox: `magent inbox add/list/triage`
- Routines and follow-ups: `magent routine add/list/run`, `magent followup add/list`
- Personal knowledge: `magent knowledge remember/recall/forget`
- Planning and review: `magent plan --save`, `magent plan-exec`, `magent plan-preview`, `magent plan-run`, `magent plan-list`, `magent plan-show`, `magent plan-apply`, `magent plan-discard`, `magent run`, `magent review --json`, `magent review --save`, `magent review-show`
- Repo intelligence: `magent graph`, `magent code index/symbols/related`, `magent test map/related/explain/run-related`, `magent test-intel`, `magent env-doctor`, `magent diagnostics`, `magent ci --logs`, `magent ci --repair-plan --save`
- Patch queue: `magent patch save/list/apply/revert`
- Checkpoint undo: `magent checkpoint list/show/diff/restore/restore-last/session-list/session-diff/session-restore`
- Built-in documentation: `magent tutorial`, `magent docs list/show/search/doctor/generate-reference`
- Reliability surfaces: agent-loop harness, CLI smoke coverage, provider/config/DB/logging tests, and `magent docs show testing`
- Data/API/notes helpers: `magent data inspect`, `magent api save/list`, `magent notes`
- Session and usage views: `magent session timeline`, `magent stats`, `magent dashboard --serve`

---

## 15. Configuration Reference

### Global Config (`~/.config/magent/config.toml`)

```toml
[agent]
name = "MagAgent"
version = "0.10.0"
selective_tools = true

[defaults]
provider = "ollama"
model = "qwen2.5-coder:32b"
permission_mode = "balanced"
context_window_tokens = 32000
memory_budget_tokens = 4000
repo_map_budget_tokens = 1200
skill_budget_tokens = 2000

[memory]
auto_write = true
auto_commit = false
write_every_n_turns = 5      # + always at end of session
extraction_provider = "ollama"
extraction_model = "qwen2.5:7b"
encrypt = false              # AES-256 encryption at rest (opt-in)
recall_body_tokens = 220
semantic_enabled = true
semantic_provider = "ollama"
semantic_model = "nomic-embed-text"
semantic_top_k = 8

[models]
coding = "openai/gpt-4.1"
review = "anthropic/claude-sonnet-4"
memory = "ollama/qwen2.5:7b"
cheap = "opencode-go/deepseek-v4-flash"
fallback = ["ollama/qwen2.5-coder:32b"]

[context]
compact_every_n_turns = 10
keep_recent_turns = 6
max_history_tokens = 6000
prune_stale_tool_results = true
prompt_caching = true

[tool_budgets]
default = 8000
read_file = 16000
run_shell = 10000
db_query = 8000

[skills]
# Skills lockfile — pins skill versions like requirements.txt
lockfile = "~/.config/magent/skills.lock"

[ui]
theme = "dark"           # dark | light | auto
stream_output = true
show_tool_calls = true
show_memory_writes = false

[providers]
# ... see Section 7.3

[mcp]
# ... see Section 13.2
```

---

## 16. Installation

```bash
# Via pip (recommended)
pip install magent

# Or via pipx (isolated environment)
pipx install magent

# First-time setup wizard
magent setup

# Verify installation
magent --version
magent doctor     # Checks providers, dependencies, memory dir
```

The `magent setup` wizard:
1. Creates `~/.config/magent/` directory structure
2. Creates a default user profile (prompts for username)
3. Initializes the MagGraph memory directory
4. Interactively configures at least one provider
5. Runs a quick smoke test

---

## 17. Implementation Roadmap

### Phase 1 — Foundation (v0.1)

**Goal:** Functional single-user agent with MagGraph memory and basic provider support.

- [ ] Project scaffold: Typer CLI, Rich TUI, packaging
- [ ] LiteLLM provider abstraction layer
- [ ] Provider support: Ollama, OpenAI, Anthropic
- [ ] Basic tool suite: read/write/edit files, shell, list_dir, web search
- [ ] MagGraph integration: memory read (pre-task) and write (post-task)
- [ ] `magent memory stats` command
- [ ] `magent setup` wizard
- [ ] Risk-tier permission model (balanced mode)
- [ ] Session logging (JSONL)

### Phase 2 — Multi-User & Skills (v0.2)

**Goal:** Multi-user system, skills, and expanded provider support.

- [ ] Multi-user management: `user create/switch/delete/list`
- [ ] Per-user isolated MagGraph directories
- [ ] Skill system: discovery, injection, auto-learning
- [ ] Provider support: Nous Portal, OpenCode Zen, Google, Groq, OpenRouter
- [ ] `magent memory search/show/traverse/delete/export` commands
- [ ] Permission mode switching (`magent mode`)
- [ ] LSP integration
- [ ] Plan & Build mode (`--plan` flag)

### Phase 3 — Sub-Agents & MCP (v0.3)

**Goal:** Parallel task execution and MCP ecosystem integration.

- [ ] Sub-agent spawning and lifecycle management
- [ ] `/spawn` slash command
- [ ] MCP server support (client-side)
- [ ] MagGraph Git auto-commit integration
- [ ] Context forking
- [ ] `magent doctor` health check command
- [ ] LM Studio and AWS Bedrock provider support

### Phase 4 — Polish & Ecosystem (v1.0)

**Goal:** Production quality, broad ecosystem, strong docs.

- [ ] Embedded MagGraph web dashboard (`magent memory ui`)
- [ ] Git sync for memory graphs (multi-machine)
- [ ] Session replay / export
- [ ] Comprehensive test suite
- [ ] Full documentation site
- [ ] VS Code extension (read-only memory view)
- [ ] Auto-update mechanism

---

## 18. Key Design Decisions & Rationale

### Why Python over Rust/Go?

MagGraph provides native Python bindings via PyO3. Python gives us the fastest path to a great agent with access to LiteLLM, Rich, asyncio, and the entire AI/ML ecosystem. The Rust core of MagGraph handles performance-critical memory operations. A Rust rewrite of the agent layer is a v2+ consideration.

### Why MagGraph over a vector DB?

Vector databases require running a server and treat memory as opaque blobs. MagGraph stores memory as plain Markdown files in Git — human-readable, version-controlled, diffable, and portable. The `[[wikilink]]`-based edge system means the knowledge graph emerges naturally from writing. For a local-first agent, this is ideal.

### Why LiteLLM over a custom abstraction?

LiteLLM is the de-facto standard for multi-provider LLM access. It handles retries, streaming, fallbacks, and cost tracking. Building our own would be reinventing the wheel — especially for supporting 10+ providers cleanly.

### Why risk-tiered permissions over always-ask or always-allow?

Research shows that always-asking leads to 93%+ blind approval rates (permission fatigue), which is worse security than auto-allow. The tiered model ensures users only see prompts for genuinely risky operations, making those prompts meaningful and reducing cognitive load.

### Why SKILL.md over code-defined skills?

Skills as Markdown files are editable by non-developers, committable to repos, readable by LLMs (injected directly into context), versionable, shareable, and compatible with the emerging OpenCode/Hermes ecosystem.

---

## 19. Security Considerations

| Concern | Mitigation |
|---|---|
| API key exposure | Keys loaded from environment variables; never stored in plaintext in config |
| Shell injection | Shell commands constructed as argument lists, not string interpolation |
| Memory exfiltration | Memory graph stays 100% local; no telemetry; no cloud sync by default |
| Sub-agent scope creep | Sub-agents operate in explicitly scoped directories; cannot write outside scope |
| Runaway agents | `Ctrl+C` hard stop; configurable per-session token budget cap |
| Malicious skills | Skills can only inject text into context — they cannot execute code directly |

---

## 20. Success Metrics

| Metric | Target (v1.0) |
|---|---|
| Time to first useful response | < 5 seconds (local model) |
| Memory recall accuracy | > 80% relevant context injected for known topics |
| Session continuity | Users report agent "remembers" preferences across sessions |
| Skill loading time | < 200ms per skill |
| Graph node count at 6 months | Avg 100–500 nodes per active user |
| Provider coverage | 10+ providers working in v1 |
| Permission interruption rate | < 5% of operations require user confirmation in balanced mode |

---

## 21. Resolved Design Decisions

> All questions from the initial draft have been resolved.

| # | Question | Decision |
|---|---|---|
| 1 | **Memory write timing** | Write every **5 user turns** (configurable via `memory.write_every_n_turns`) **plus** always at end of session |
| 2 | **Memory extraction model** | Fully configurable; users can set `extraction_provider` + `extraction_model` independently of the main agent model |
| 3 | **Project-scoped memory** | **Flat user graph**; agent uses consistent `Project: [[project_<slug>]]` wikilinks so nodes cluster naturally around project hubs |
| 4 | **Default user** | **First-run wizard always creates a named user** — no anonymous/default user |
| 5 | **Memory privacy** | **No encryption by default**; opt-in AES-256 at-rest encryption via `memory.encrypt = true` in profile |
| 6 | **Skill versioning** | **Yes** — skills.lock file pins versions; additionally, a new `bookmark` node type tracks useful URLs found during tasks for future reuse |

---

*End of PRD v0.1 — All decisions resolved, ready for implementation.*
