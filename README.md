<div align="center">

<img src="docs/assets/brand/magagent-logo.png" alt="MagAgent logo" width="220">

# 🐦‍⬛ MagAgent

**A terminal-native AI coding agent with persistent memory, built for developers who want an assistant that genuinely learns them.**

[![PyPI version](https://img.shields.io/pypi/v/mag-agent.svg)](https://pypi.org/project/mag-agent/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://python.org)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-201%20passing-brightgreen.svg)](tests/)

[Quick Start](#quick-start) · [Providers](#providers) · [Tools](#tools) · [Skills](#skills) · [Memory](#memory-graph) · [Gateway](#remote-gateway) · [Docs](docs/)

</div>

---

## Why "Mag"?

**Mag** is short for **Magpie** — a member of the *Corvidae* (Corvid) family.

Corvids — crows, ravens, magpies, jays — are among the most cognitively sophisticated animals on Earth. They are renowned for three traits that define what MagAgent aspires to be:

- 🧠 **Memory** — Corvids remember individual human faces for years and recall the locations of thousands of cached food items. MagAgent remembers *your* projects, preferences, patterns, and workflows across every session.
- 🔧 **Tool Use** — Corvids are some of the only non-primate animals that manufacture and use tools. MagAgent wields a rich toolkit: web search, file operations, databases, document generation, HTTP clients, code execution, and more.
- 💡 **Intelligence** — Corvids pass mirror self-recognition tests and demonstrate future planning. MagAgent plans multi-step tasks, spawns sub-agents for parallel work, and self-improves its knowledge graph over time.

The name also nods to **[MagGraph](https://github.com/AlexMercedCoder/MagGraph)** — the Rust-powered graph database that backs MagAgent's memory system, storing knowledge as plain Markdown files in Git.

---

## What is MagAgent?

MagAgent is a **CLI-first AI coding agent** that:

- Runs entirely in your terminal, with an optional local operations UI when you want a browser view
- Configures providers, model roles, memory, gateways, and sub-agent caps through CLI commands before you ever need to open a TOML file
- Presents a polished Rich terminal UI with a compact session banner, Markdown response panels, and quieter streaming
- Bridges workbench state into durable MagGraph memory through context maps and explicit memory promotion
- Documents architecture boundaries for memory, workbench, context, tools, CLI/TUI, and compatibility-safe refactors
- Saves and runs reusable workflow recipes for release prep, bug triage, docs audits, dependency upgrades, and test repair
- Defines reusable primary agents and subagents from `.magent/agents/*.md`, with `@review`, `@explore`, and `@docs` invocation
- Runs project hooks around tools, edits, command failures, memory candidates, and release checks
- Adds LSP-aware code intelligence commands for symbols, diagnostics, definitions, and references
- Queues background asks, recipes, plans, shell tasks, followups, and gateway tasks through `magent daemon`
- Installs local extension packs for agents, recipes, skills, tools, and MCP configuration through `magent plugin`
- Reads project playbooks from `.magent/playbook.toml` for command routines, release checklists, review rules, and context defaults
- Runs saved plans and recipes in worktree, copied, or Docker-backed sandboxes
- Provides local eval suite scaffolding for repeatable repo tasks
- Maintains a **persistent memory graph** per user that grows smarter over time
- Connects to **20 provider options** (local and cloud) via a single config
- Has **33 built-in tools** out of the box — no plugins or configuration required
- Includes **10 pre-built skill libraries** for docs, spreadsheets, PDFs, images, video, data analysis, REST APIs, databases, desktop automation, and Git
- Uses token-efficient context management: conversation compaction, repo-map slices, memory/skill budgets, and compressed tool results
- Ships built-in offline documentation and self-help search through `magent docs`
- Creates restore checkpoints before agent file writes, edits, and deletes
- Reviews memory candidates through `magent memory inbox` before promoting selected facts into MagGraph
- Groups runtime tools into capability packs that can be enabled or disabled with `magent tools`
- Adds optional Playwright browser snapshots/screenshots and GitHub PR/issue commands through `gh`
- Discovers project-local test/lint/build commands and reads `.magent/config.toml`
- Builds a lightweight local code intelligence index for symbols, imports, related files, and targeted tests
- Supports memory quality controls for duplicate review, node merge, and stale-node suppression
- Includes a reliability test harness for the agent loop, provider layer, DB tools, CLI smokes, and packaged docs
- Supports patch-first coding workflows, workspace status reports, project command roles, and release readiness checks
- Supports executable plan records, session-level undo, command learning, saved reviews, and CI repair plans
- Includes a durable **local workbench** for tasks, artifacts, project profiles, inboxes, routines, follow-ups, API bookmarks, patch queues, session timelines, static dashboards, and a live local UI
- Supports a **remote gateway** so you can send it tasks from Slack, Discord, or Telegram while you're away from your terminal

Every session, MagAgent extracts facts, preferences, and patterns from your conversation and writes them into a MagGraph knowledge graph. Next session, it reads that graph to understand your tech stack, coding style, project context, and recurring patterns — without you having to repeat yourself.

---

## Quick Start

### Install

```bash
pip install mag-agent

# With gateway support (Slack/Discord/Telegram):
pip install "mag-agent[gateway]"

# Recommended: isolate with pipx
pipx install mag-agent
```

### First-time setup

```bash
magent setup
magent configure
```

The wizard will:
1. Create a named user profile with an isolated memory graph
2. Walk you through selecting an AI provider and model
3. Test the connection live

### Start a session

```bash
magent
```

### Quick one-shot task

```bash
magent ask "Refactor the auth module to use JWTs and add tests"
magent docs list
magent tutorial
magent doctor
magent recipe run release-prep
magent memory inbox
magent plan-sandbox <plan-id> --dry-run
magent eval init
magent onboard --profile coding-cloud
magent next
```

---

## Providers

MagAgent uses [LiteLLM](https://github.com/BerriAI/litellm) under the hood, supporting any OpenAI-compatible endpoint.

| Provider | Config ID | Notes |
|---|---|---|
| **Ollama** | `ollama` | Local inference, free, default |
| **Nous Portal** | `nous-portal` | Hermes 4, 200+ curated models |
| **OpenCode Zen** | `opencode-zen` | Coding-optimized models |
| **OpenCode Go** | `opencode-go` | Fast, cost-efficient coding models |
| **OpenAI** | `openai` | GPT-4o, GPT-4.1, o3 |
| **Anthropic** | `anthropic` | Claude 3.5 Sonnet / Claude 4 |
| **Google** | `google` | Gemini 2.0 / 2.5 Pro |
| **Groq** | `groq` | Ultra-fast inference |
| **OpenRouter** | `openrouter` | 200+ model aggregator |
| **LM Studio** | `lmstudio` | Local GUI-managed models |
| **AWS Bedrock** | `bedrock` | Enterprise / VPC |
| **Mistral AI** | `mistral` | Mistral-hosted models |
| **DeepSeek** | `deepseek` | DeepSeek chat/reasoning models |
| **xAI** | `xai` | Grok models |
| **Perplexity** | `perplexity` | Sonar search/research models |
| **Cerebras** | `cerebras` | Fast inference models |
| **Together AI** | `together_ai` | Hosted open models |
| **Fireworks AI** | `fireworks_ai` | Hosted open and coding models |
| **DeepInfra** | `deepinfra` | Hosted open models |
| **Custom** | `custom` | Any OpenAI-compatible endpoint |

Configure multiple providers and switch mid-session: `/model anthropic/claude-3-5-sonnet`

CLI-first provider setup:

```bash
magent provider list
magent provider detect
magent provider matrix
magent provider recommend --goal coding
magent provider explain mistral
magent provider env
magent provider test-matrix
magent provider set openai --model gpt-5 --api-key-env OPENAI_API_KEY
magent provider set openai --model gpt-5 --access codex
magent provider wizard
magent provider test
magent provider doctor
```

Provider access modes are intentionally distinct:

- OpenAI API: `magent provider set openai --access api --api-key-env OPENAI_API_KEY`
- OpenAI Codex/ChatGPT plan: `magent provider set openai --access codex`, then run `codex login`
- OpenCode Zen pay-as-you-go: `magent provider set opencode-zen --access payg --api-key-env OPENCODE_ZEN_KEY`
- OpenCode Go subscription: `magent provider set opencode-go --access subscription --api-key-env OPENCODE_GO_KEY`

Route different work to different models:

```bash
magent model roles
magent model set-role coding openai/gpt-5
magent model set-role review anthropic/claude-sonnet-4-5
magent model set-role memory ollama/qwen2.5:7b
magent model set-role cheap openrouter/deepseek/deepseek-chat
magent model set-role fallback "ollama/qwen2.5-coder:32b,openrouter/deepseek/deepseek-chat"
magent model health
magent model wizard
```

Review config changes before applying them:

```bash
magent config propose "use mistral by default, manual memory, cap 2 subagents"
magent config proposals
magent config apply <proposal-id>
magent events list
```

---

## Tools

MagAgent ships with **33 built-in tools** the agent can call without any setup.

Tool capability packs make selective loading explicit:

```bash
magent tools list
magent tools explain web
magent tools disable desktop
magent tools enable desktop
```

Browser automation is optional:

```bash
pip install "mag-agent[browser]"
playwright install
magent browser snapshot https://example.com
magent browser screenshot https://example.com --out example.png
```

### File & Code Tools

| Tool | Description | Permission |
|---|---|---|
| `read_file` | Read file preview, with truncation for large files | Silent in project, confirm outside |
| `read_file_range` | Read exact line ranges from a file | Silent in project, confirm outside |
| `outline_file` | Compact source outline with symbols and line numbers | Silent in project, confirm outside |
| `write_file` | Write/create a file | Auto in project dir |
| `edit_file` | Replace exact string in file | Auto in project dir |
| `delete_file` | Delete file or directory | Confirm |
| `list_dir` | List directory contents | Silent in project, confirm outside |
| `diff_files` | Unified diff between two files | Silent in project, confirm outside |
| `compress` | Zip or tar.gz a file/directory | Auto |
| `extract` | Unzip/untar an archive | Auto |
| `run_shell` | Execute a shell command | Tiered by command risk |
| `run_python` | Run Python code in isolated subprocess | Confirm |
| `install_package` | `pip install` with user permission | Confirm |
| `search_codebase` | Ripgrep pattern search | Silent |
| `git_op` | Any git subcommand | Tiered |

### Web & Network Tools

| Tool | Description | Permission |
|---|---|---|
| `web_search` | DuckDuckGo search (real results, no API key) | Auto |
| `web_fetch` | Fetch URL, clean article extraction via trafilatura | Auto |
| `http_request` | Full HTTP client: GET/POST/PUT/PATCH/DELETE | Auto |
| `browser_snapshot` | Capture title and visible text with Playwright | Auto |
| `browser_screenshot` | Capture a page screenshot with Playwright | Auto |

### Data Tools

| Tool | Description | Permission |
|---|---|---|
| `json_query` | JMESPath query over JSON file or string | Silent |
| `db_query` | SELECT from a named SQLite database | Silent |
| `db_execute` | INSERT/UPDATE/DELETE/CREATE TABLE | Auto |
| `db_list_tables` | List tables + row counts | Silent |
| `db_schema` | Show column definitions for a table | Silent |
| `db_list_databases` | List all user databases | Silent |

### System & Desktop Tools

| Tool | Description | Permission |
|---|---|---|
| `system_info` | CPU, RAM, disk, OS, Python version | Silent |
| `notify` | Desktop notification (plyer / notify-send) | Silent |
| `clipboard_read` | Read system clipboard | Silent |
| `clipboard_write` | Write to clipboard | Auto |
| `open_file` | Open file in default application (xdg-open) | Auto |
| `read_image` | Image metadata + base64 for vision models | Silent in project, confirm outside |

---

## Permission Modes

MagAgent uses a **4-tier risk system** to auto-approve safe operations and only ask when it matters.

| Mode | Behaviour |
|---|---|
| `balanced` *(default)* | Project reads run; outside-project reads confirm; low-risk writes auto-run; medium needs Enter; high needs typed "yes" |
| `silent` | Only destructive or high-risk ops prompt |
| `paranoid` | Everything except file reads requires confirmation |
| `yolo` | Fully autonomous — no prompts |

```bash
magent permission status
magent permission explain paranoid
magent permission set paranoid
/mode paranoid
```

Pre-approve patterns in your config (e.g. trust all `git` and `pytest` commands):

```toml
[permissions]
allowed_shell_patterns = ["git *", "npm *", "pytest *", "cargo *"]
```

---

## Memory Graph

MagAgent's memory is powered by **[MagGraph](https://github.com/AlexMercedCoder/MagGraph)** — a Rust-backed in-process graph database that stores nodes as plain Markdown files in a Git repository.

```
~/.config/magent/users/<username>/memory/
├── preference_uses_typescript.md
├── project_ecommerce_backend.md
├── pattern_prefers_async_await.md
└── ...
```

**Node types:**

| Type | What it stores |
|---|---|
| `preference` | Coding style, tool choices, formatting preferences |
| `project` | Projects you work on, their tech stack and structure |
| `pattern` | Recurring problems and solutions MagAgent has learned |
| `skill_learned` | Techniques and APIs you've used together |
| `fact` | Domain knowledge extracted from conversations |
| `session_summary` | High-level summaries of past sessions |
| `error_pattern` | Bugs and their resolutions |
| `bookmark` | URLs and references the agent saved for you |

Memory is extracted and written every **N turns** (configurable, default 5) and always at session end.

```bash
magent memory stats                     # Node/edge counts, disk usage
magent memory index                     # Build/update semantic search sidecar
magent memory search "JWT"              # Hybrid semantic + keyword search
magent memory search --semantic "JWT"   # Force semantic search
magent memory search --keyword "JWT"    # Force keyword/full-text search
magent memory semantic status           # Inspect semantic sidecar status
magent memory semantic reset            # Reset semantic sidecar
magent memory show project_myapp        # View a node
magent memory traverse project_myapp    # BFS from a node
magent memory review --diff             # Audit pending memory graph changes
magent memory approve                   # Commit reviewed memory graph changes
magent memory quality                   # Find duplicate-looking/suppressed nodes
magent memory merge <target> <source> --preview # Preview duplicate memory merges
magent memory merge <target> <source>   # Merge duplicate memory nodes
magent memory suppress <node-id>        # Mark stale memory suppressed
magent memory unsuppress <node-id>      # Remove suppression markers
magent memory ui                        # Open MagGraph dashboard
magent memory sync status               # Run MagGraph sync status
magent memory export --out backup.json  # Export all nodes as JSON
magent memory reset                     # Wipe all memory (with confirmation)
```

### Token-Efficient Context

MagAgent keeps context lean while preserving useful state:

- **Conversation compaction** summarizes older turns and keeps recent turns verbatim.
- **Repository map slices** inject relevant file/symbol maps instead of whole files.
- **Memory recall budgets** inject compact matches first, then a few excerpts.
- **Semantic memory search** stores local SQLite embedding sidecars, uses Ollama embeddings when available, and falls back to deterministic offline vectors.
- **Selective tool injection** sends a compact relevant tool subset to the model each turn instead of always injecting every built-in tool.
- **Skill budgets** truncate long skill guidance before it crowds out the task.
- **Tool result compression** trims large outputs and points the agent to targeted follow-ups.
- **Stale result pruning** removes old file-read results from live context after files are edited.
- **Tool output budgets** cap oversized tool results with a `raw=true` escape hatch.
- **Large file reads** return previews; use `outline_file` and `read_file_range` for exact context.

---

## Local Workbench

MagAgent's workbench stores practical productivity state under each user profile:

- **Task ledger** — `magent task add/list/done/report`
- **Artifact workspace** — `magent artifact add/list`
- **Project profiles** — `magent project profile/list/commands/roles/doctor/config/command-history/command-promote`
- **Code intelligence** — `magent code index/symbols/related`
- **Test intelligence** — `magent test map/related/explain/run-related`
- **Inbox and routines** — `magent inbox add/triage`, `magent routine add/run`
- **Follow-ups** — `magent followup add/list`
- **Knowledge commands** — `magent knowledge remember/recall/forget`
- **Review and planning** — `magent plan --save`, `magent plan-exec`, `magent plan-preview`, `magent plan-run`, `magent plan-list`, `magent plan-show`, `magent plan-apply`, `magent plan-discard`, `magent review --json`, `magent review --save`, `magent review-show`, `magent run`
- **Repo/test helpers** — `magent graph`, `magent code index/symbols/related`, `magent test map/related/explain/run-related`, `magent test-intel`, `magent env-doctor`, `magent diagnostics`, `magent ci --logs`, `magent ci --repair-plan --save`
- **Patch queue** — `magent patch save/list/apply/revert`
- **Patch-first workflow** — `magent patch preview/explain`, `magent workspace status/clean-report`
- **Checkpoint undo** — `magent checkpoint list/show/diff/restore/restore-last/session-list/session-diff/session-restore`
- **Built-in docs** — `magent docs list/show/search/doctor/generate-reference`
- **Artifact registry** — `magent artifact add/list/show/open/checksum`
- **Data/API/notes** — `magent data inspect`, `magent api save/list`, `magent notes`
- **Session and usage** — `magent session timeline`, `magent stats`, `magent dashboard`, `magent dashboard --serve`, `magent ui`

Workbench files are plain JSON in `~/.config/magent/users/<username>/workbench/`.

---

## SQLite Local Databases

The agent can create and manage structured local databases — per user, per project, or user-specified.

```
~/.config/magent/users/<username>/databases/
├── default.db       # General-purpose
├── myproject.db     # Project-specific
└── analytics.db     # Purpose-specific
```

Inside a session, the agent automatically uses these tools to store structured data — task lists, research caches, API test logs, contacts — without any setup required.

```bash
/db    # In-session: list your databases
```

---

## Skills

Skills are Markdown files that teach the agent how to perform specific tasks — code patterns, library usage, common pitfalls, and decision guides. They are injected into context automatically when relevant.

### Locations

- **Global:** `~/.config/magent/skills/<skill-name>/SKILL.md`
- **Project-local:** `.magent/skills/<skill-name>/SKILL.md`

### Built-in Skills Library

MagAgent ships with 10 pre-built skills in `docs/skills/`:

| Skill | Triggers On | Guide |
|---|---|---|
| [Create Word Docs](docs/skills/create-word-docs/SKILL.md) | docx, word document, report | python-docx + docxtpl |
| [Create Spreadsheets](docs/skills/create-spreadsheets/SKILL.md) | excel, xlsx, spreadsheet | openpyxl with charts/formulas |
| [Create PDFs](docs/skills/create-pdfs/SKILL.md) | pdf, html to pdf | fpdf2 + WeasyPrint + pypdf |
| [Create Images](docs/skills/create-images/SKILL.md) | image, chart, plot, PNG | Pillow + matplotlib |
| [Create Video/Audio](docs/skills/create-video-audio/SKILL.md) | video, audio, mp4, Remotion | Remotion (React) + moviepy + ffmpeg |
| [Data Analysis](docs/skills/data-analysis/SKILL.md) | pandas, csv, dataframe | pandas + SQLite integration |
| [REST API Testing](docs/skills/rest-api/SKILL.md) | api, http, endpoint, curl | http_request patterns + auth |
| [SQLite Database](docs/skills/sqlite-database/SKILL.md) | sql, database, sqlite | Named DBs, common schemas |
| [Desktop Automation](docs/skills/desktop-automation/SKILL.md) | notify, clipboard, open file | notify + clipboard + system info |
| [Git Workflow](docs/skills/git-workflow/SKILL.md) | git, branch, commit, merge, rebase | Git best practices & conflict resolution |

### Writing Your Own Skill

```markdown
---
name: my-skill
description: Brief description — used for matching
version: "1.0"
trigger_keywords:
  - keyword1
  - keyword2
tools_required:
  - run_shell
  - write_file
---

# Skill Title

Guidance for the agent here — code patterns, library usage, pitfalls...
```

---

## Sub-Agents

Spawn a parallel agent to work on a focused sub-task while you continue the main conversation:

```
/spawn Write unit tests for all functions in src/auth.py
```

The sub-agent runs an isolated session sharing your memory graph, completes the task, and returns a summary. Use this for long-running tasks that shouldn't interrupt the main flow.

The main agent can orchestrate sub-agents, and the cap is configurable:

```bash
magent subagent configure --max 3 --parallel 2 --model-role coding
magent subagent status
magent subagent run "Audit the auth tests"
```

Set `--max 0` to disable sub-agent spawning.

---

## Remote Gateway

Send tasks to MagAgent from **Slack**, **Discord**, or **Telegram** while you're away from your terminal.

```bash
# Install gateway dependencies
pip install "mag-agent[gateway]"

# Generate config template
magent gateway init

# Configure from the CLI
magent gateway configure telegram --bot-token "$TELEGRAM_BOT_TOKEN" --allowed-user 12345
magent gateway configure slack --bot-token "$SLACK_BOT_TOKEN" --app-token "$SLACK_APP_TOKEN"
magent gateway wizard discord
magent gateway doctor

# Start (background daemon)
magent gateway start

# Platform-specific
magent gateway start slack
magent gateway start discord telegram

# Monitoring
magent gateway status
magent gateway logs --follow
magent gateway stop
```

### How it works

When you message the bot:
1. It immediately replies **"⏳ Working on it..."**
2. Runs your task through the full agent (tools, memory, etc.)
3. **Edits that message** with the result when done
4. Sessions are **persistent per channel** — it remembers conversation context

### Security

- **Allowlist** — only users in `allowed_user_ids` can send instructions
- **Channel restriction** — optionally limit to specific channels
- **Rate limiting** — configurable per-user request limit (default 10/min)
- **Task timeout** — configurable max execution time (default 5 min)

### Setup Guides

| Platform | Guide | Notes |
|---|---|---|
| **Slack** | [setup-slack.md](docs/gateway/setup-slack.md) | Socket Mode — no public URL needed |
| **Discord** | [setup-discord.md](docs/gateway/setup-discord.md) | Bot token — free, 2-minute setup |
| **Telegram** | [setup-telegram.md](docs/gateway/setup-telegram.md) | @BotFather — simplest of the three |

---

## All Commands

### User Management

```bash
magent user create <name>   # Create a user profile
magent user switch <name>   # Switch active user
magent user list            # List all users
magent user delete <name>   # Delete user + memory (with confirmation)
magent user current         # Show active user
```

### Memory

```bash
magent memory stats                      # Node/edge counts, disk usage
magent memory search "<query>"           # Search memory graph
magent memory show <node-id>             # View a memory node
magent memory traverse <node-id>         # BFS traversal from a node
magent memory delete <node-id>           # Delete a node
magent memory export --out backup.json   # Export all nodes as JSON
magent memory reset                      # Wipe all memory (prompts "yes")
magent memory log                        # View recent session logs
magent memory ui                         # Open embedded MagGraph UI
magent memory sync status                # Git sync status via MagGraph
magent memory sync pull                  # Pull memory graph updates
magent memory sync push -m "message"     # Commit/push memory graph updates
magent memory configure --mode inbox-first --write-every 3
```

### Gateway

```bash
magent gateway init              # Print example config
magent gateway configure telegram # Save platform tokens and allowlists
magent gateway wizard slack      # Prompt for platform token fields
magent gateway doctor            # Show gateway readiness
magent gateway start             # Start all configured platforms (daemon)
magent gateway start slack -f    # Single platform, foreground mode
magent gateway stop              # Stop daemon (SIGTERM)
magent gateway status            # Is daemon running? PID?
magent gateway logs [-n N] [-f]  # View / follow gateway log
```

### Other

```bash
magent setup           # First-run setup wizard
magent configure       # Friendly setup/configuration wizard
magent onboard         # Apply guided profile + project defaults
magent next            # Suggest useful next actions
magent profile list    # Guided configuration presets
magent profile apply   # Apply provider/memory/subagent preset
magent config backup   # Back up global/current-user config
magent config diff     # Diff current config against a backup
magent config restore  # Restore config from a backup
magent provider list   # Known providers and default models
magent provider detect # Provider readiness from local environment
magent provider matrix # Provider catalog and readiness table
magent provider recommend # Recommend providers for a goal
magent provider set    # Set default provider/model
magent provider wizard # Interactive provider/access/model setup
magent provider doctor # Provider/config readiness
magent model roles     # Show role-specific model routing
magent model set-role  # Set coding/review/memory/cheap/fallback role
magent model wizard    # Interactive model role setup
magent subagent status # Show sub-agent caps/defaults
magent subagent run    # Run one focused sub-agent task
magent subagent wizard # Interactive sub-agent setup
magent mode <mode>     # Set permission mode globally
magent doctor          # Health check: providers, memory, deps
magent doctor --json   # Structured actionable readiness checks
magent doctor --fix    # Apply safe local config fixes
magent plan "goal"     # Generate a local implementation plan
magent run "goal"      # Record an autonomous work-session plan
magent review          # Heuristic local diff review
magent graph           # Lightweight repo import graph
magent code index      # Build local symbol/import/test index
magent code symbols    # Search indexed code symbols
magent code related    # Show related tests/import peers for a file
magent test map        # Map source files to likely tests
magent test related    # Show likely tests for a file
magent test explain    # Explain why tests were selected
magent test run-related # Run likely tests for a file
magent test-intel      # Suggest tests for current git changes
magent patch preview   # Preview a saved patch
magent patch explain   # Explain patch impact
magent workspace status # Show git/workbench status
magent release check   # Run release readiness checks
magent project init    # Bootstrap .magent config and playbook
magent project wizard  # Guided project bootstrap
magent env-doctor      # Project environment checks
magent dashboard       # Export static local dashboard
magent ui              # Serve live local operations UI
magent --version       # Show version
```

### In-Session Slash Commands

| Command | Description |
|---|---|
| `/help` | All slash commands |
| `/memory` | Memory graph stats |
| `/skills` | Loaded skills list |
| `/model` | Current model / change model |
| `/user` | Active user |
| `/mode <mode>` | Change permission mode |
| `/spawn <task>` | Spawn a sub-agent |
| `/db` | List your SQLite databases |
| `/clear` | Clear conversation history |
| `/exit` | End session |

---

## Configuration

Prefer the CLI for common changes:

```bash
magent provider set openai --model gpt-5 --api-key-env OPENAI_API_KEY
magent provider set openai --model gpt-5 --access codex
magent model set-role review anthropic/claude-sonnet-4-5
magent memory configure --mode inbox-first --semantic --write-every 3
magent memory wizard
magent gateway configure telegram --bot-token "$TELEGRAM_BOT_TOKEN"
magent subagent configure --max 3 --parallel 2
magent project init
```

Full config at `~/.config/magent/config.toml`:

```toml
[defaults]
provider = "ollama"
model = "qwen2.5-coder:32b"
permission_mode = "balanced"
context_window_tokens = 32000
memory_budget_tokens = 4000
repo_map_budget_tokens = 1200
skill_budget_tokens = 2000

[memory]
write_every_n_turns = 5
extraction_provider = "ollama"
extraction_model = "qwen2.5:7b"
encrypt = false
recall_body_tokens = 220

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

[permissions]
mode = "balanced"
allowed_shell_patterns = ["git *", "npm *", "pytest *"]

[providers.ollama]
base_url = "http://localhost:11434"
default_model = "qwen2.5-coder:32b"

[providers.nous-portal]
base_url = "https://inference-api.nousresearch.com/v1"
api_key_env = "NOUS_API_KEY"
default_model = "nous-hermes-4"

[providers.opencode-go]
base_url = "https://opencode.ai/go/v1"
api_key_env = "OPENCODE_GO_API_KEY"
default_model = "deepseek-v4-flash"

[gateway]
username = "alex"
allowed_user_ids = ["YOUR_SLACK_USER_ID"]
rate_limit_per_minute = 10
max_task_duration_seconds = 300

[gateway.slack]
bot_token = "xoxb-..."
app_token = "xapp-..."

[gateway.discord]
bot_token = "..."

[gateway.telegram]
bot_token = "..."
```

---

## Documentation

| Document | Description |
|---|---|
| [docs/skills/create-word-docs/SKILL.md](docs/skills/create-word-docs/SKILL.md) | Word document generation (python-docx, docxtpl) |
| [docs/skills/create-spreadsheets/SKILL.md](docs/skills/create-spreadsheets/SKILL.md) | Excel spreadsheet generation (openpyxl) |
| [docs/skills/create-pdfs/SKILL.md](docs/skills/create-pdfs/SKILL.md) | PDF generation (fpdf2, WeasyPrint, pypdf) |
| [docs/skills/create-images/SKILL.md](docs/skills/create-images/SKILL.md) | Image manipulation (Pillow, matplotlib) |
| [docs/skills/create-video-audio/SKILL.md](docs/skills/create-video-audio/SKILL.md) | Video/audio (Remotion, moviepy, ffmpeg) |
| [docs/skills/data-analysis/SKILL.md](docs/skills/data-analysis/SKILL.md) | Data analysis (pandas, SQLite) |
| [docs/skills/rest-api/SKILL.md](docs/skills/rest-api/SKILL.md) | REST API testing and integration |
| [docs/skills/sqlite-database/SKILL.md](docs/skills/sqlite-database/SKILL.md) | SQLite database patterns |
| [docs/skills/desktop-automation/SKILL.md](docs/skills/desktop-automation/SKILL.md) | Desktop notifications, clipboard, system info |
| [docs/skills/git-workflow/SKILL.md](docs/skills/git-workflow/SKILL.md) | Git workflows & conflict resolution |
| [docs/gateway/setup-slack.md](docs/gateway/setup-slack.md) | Slack gateway setup (Socket Mode) |
| [docs/gateway/setup-discord.md](docs/gateway/setup-discord.md) | Discord gateway setup |
| [docs/gateway/setup-telegram.md](docs/gateway/setup-telegram.md) | Telegram gateway setup |

---

## Development

```bash
git clone https://github.com/AlexMercedCoder/MagAgent.git
cd MagAgent
pip install -e ".[dev]"

# Run tests
pytest

# Run with coverage
pytest --cov=src/magent --cov-report=term-missing

# Lint
ruff check src/

# Built-in docs coverage
magent docs doctor

# Type check
mypy src/magent
```

### Project Structure

```
src/magent/
├── agent.py          # AgentSession — tool loop, streaming, sub-agents
├── cli/
│   ├── app.py        # Typer app and command-group composition
│   ├── command_context.py # Shared command helper/context functions
│   └── main.py       # CLI entry point and command implementations
├── config/           # TOML config, user profiles
├── gateway/          # Remote gateway (Slack, Discord, Telegram)
│   └── adapters/     # Platform-specific adapters
├── memory/           # MagGraph integration — read, write, search
├── permissions/      # Risk tiers, auto-approve logic
├── providers/        # LiteLLM provider registry
├── repo_map.py       # Token-efficient repository map cache
├── records.py        # Typed record helpers for common dict payloads
├── skills/           # SKILL.md discovery, matching, lockfile
├── subagents/        # Sub-agent runner
├── tokens.py         # Lightweight token budgeting helpers
├── tools/            # 33 built-in tools (file, web/browser, db, system)
│   ├── executor.py   # ToolExecutor implementation
│   └── db.py         # SQLite named database tools
├── context.py        # Context map and memory promotion bridge
├── workbench.py      # Local productivity ledgers and workflow helpers
├── workbench_domains/ # Domain import modules for future workbench extraction
├── workbench_store.py # JSON-backed workbench storage primitive
├── logging.py        # JSONL session event logging
├── setup.py          # First-run wizard
└── tui.py            # Rich terminal UI, theme, status, and streaming renderer
docs/
├── gateway/          # Gateway setup guides
└── skills/           # Built-in skill SKILL.md files
tests/
└── unit/             # 176 unit tests (all mocked, no credentials needed)
```

---

## License

Apache 2.0 — see [LICENSE](LICENSE)

---

<div align="center">

Built with 🐦‍⬛ by [Alex Merced](https://github.com/AlexMercedCoder) · Powered by [MagGraph](https://github.com/AlexMercedCoder/MagGraph)

*Like the Magpie — intelligent, tool-using, and never forgets.*

</div>
