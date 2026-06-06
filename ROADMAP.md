# MagAgent Roadmap

> Recommended enhancements for MagAgent — organized by phase, priority, and implementation detail.
> Each item includes what to build, why it matters, and how to approach it.

---

## Phase 0 — Token Efficiency (Do First)

These improvements reduce token spend on every single interaction, regardless of the model. They compound with every feature built after them — fewer tokens wasted means cheaper sessions, longer effective context windows, and faster responses.

---

### 0.1 · Tool Output Budgets (Token Caps Per Tool)

**Status:** Expanded in v0.7.0. Large file reads are previewed, exact range reads are available, agent-side tool results are compressed before context injection, and dispatch-level per-tool output budgets now cap oversized results with `raw=true` as an escape hatch.

**Why:** The biggest single source of token waste is uncapped tool output. A `read_file` on a 2,000-line file burns thousands of tokens even when the agent only needed 10 lines. A `web_fetch` on a documentation page can return 15,000 tokens of boilerplate. These cost money and crowd out useful context.

**What to build:**
- Add `max_output_tokens` cap to every tool's return value — truncate with a clear `[truncated at N tokens — use offset/path params to read more]` notice
- Per-tool configurable limits in `config.toml`:

```toml
[tool_budgets]
read_file = 8000         # chars, not tokens — fast to compute
web_fetch = 6000
run_shell = 4000
run_python = 4000
search_codebase = 3000
http_request = 8000
db_query = 4000          # cap rows returned
```

- New tool: `read_file_range(path, start_line, end_line)` — so the agent can surgically read just the relevant lines after seeing a truncated result
- `search_codebase` already uses ripgrep; add `--max-count` to avoid giant match floods
- For `db_query`, add automatic `LIMIT 100` if no LIMIT clause is present

**Implementation:** Wrap every tool return in a `_budget_output(result, tool_name)` function in `ToolExecutor` that truncates at the configured limit.

---

### 0.2 · Selective Tool Injection

**Why:** The standard OpenAI function-calling schema for 31 tools costs thousands of prompt tokens *on every LLM call* — even simple conversational questions that don't need most tools. That's wasted on every turn.

**What to build:**
- Tool classifier: given the user's message, use a small fast model (or keyword heuristics) to predict which tool categories are relevant
- Tool categories:
  - `file_ops` — read_file, write_file, edit_file, delete_file, list_dir
  - `code_exec` — run_shell, run_python, install_package
  - `web` — web_search, web_fetch, http_request
  - `data` — db_*, json_query
  - `system` — system_info, notify, clipboard_*, open_file
  - `docs` — always inject (small definitions, rarely called)
- Always inject the 8 most-used tools; inject the rest only when the category is predicted relevant
- Config: `selective_tools = true` (default off for predictability)
- Fallback: if the agent attempts a tool not in the injected set, re-run with the full tool set

**Expected savings:** 40–60% reduction in tool-definition tokens on conversational turns.

---

### 0.3 · Prompt Caching Awareness

**Why:** Anthropic (Claude) and OpenAI both offer prompt caching — if the beginning of a prompt is identical across calls, the cached portion is billed at 10% of the normal rate. MagAgent can structure its prompts to maximize cache hits.

**What to build:**
- Move the **static** parts of the system prompt (tool definitions, base agent instructions) to the front — they never change across turns
- Move the **dynamic** parts (memory context, skill context, which change per-turn) to the end
- For Anthropic: add `cache_control: {"type": "ephemeral"}` breakpoints after the static section using LiteLLM's `extra_headers` or message metadata
- For OpenAI: structure messages so the first N tokens are identical across all calls in the session
- Track cache hit rate in session logs: `{"event": "cache", "cached_tokens": 1800, "saved_usd": 0.0016}`
- Config: `prompt_caching = true` (auto-detect provider support)

**Expected savings:** 50–90% cost reduction on cached portions for Claude and GPT-4o users.

---

### 0.4 · Smart File Reading (Partial Reads + Outline Mode)

**Status:** Shipped in v0.3.0. `read_file_range` and `outline_file` are available, `read_file` previews large files, and the system prompt nudges targeted file reads.

**Why:** The agent often reads entire files to find one function. A smarter read strategy can give the agent what it needs with 90% fewer tokens.

**What to build:**
- `read_file` gains `start_line`/`end_line` params (already planned in 0.1, expand here)
- New tool: `outline_file(path)` — returns a compact structural overview using simple AST parsing:
  ```
  src/auth.py (312 lines)
    L1-20   imports
    L22     class AuthManager:
    L35       def login(self, user, password)  → L35-67
    L69       def logout(self, token)          → L69-82
    L85     def hash_password(pwd: str)        → L85-95
  ```
- Agent calls `outline_file` first, then `read_file` with the exact line range it needs
- Modify the system prompt to instruct the agent to always `outline_file` before `read_file` on any file over 100 lines
- Add `search_codebase` result format that includes line numbers so agents can read targeted ranges

**Expected savings:** 60–80% token reduction on large file reads.

---

### 0.5 · Stale Tool Result Pruning

**Why:** The conversation history sent to the LLM includes every tool call and its result from the entire session. A file that was read 20 turns ago and then rewritten is sending stale, irrelevant content on every subsequent call — paying for context that actively misleads the model.

**What to build:**
- Track which files have been written/edited after being read in the conversation
- Prune stale `read_file` tool results from the conversation history when a newer write to the same path exists
- Mark tool results as `[pruned — file was modified at turn N]` placeholder to preserve conversation flow
- Similarly prune: duplicate `web_search` results for the same query, `system_info` results older than 10 turns
- Config: `prune_stale_tool_results = true` (default: true)
- Track pruning savings in session logs

**Implementation:** `ConversationPruner` class that runs after each tool-result append, O(N) pass over recent history.

**Expected savings:** 20–40% reduction in conversation history tokens in long sessions.

---

### 0.6 · Tool Response Compression

**Status:** Partially shipped in v0.3.0. Agent-side tool results are compressed/truncated before entering conversation context. Fine-grained raw/debug controls remain future work.

**Why:** Many tool results include verbose JSON, full error tracebacks, or redundant metadata that the model doesn't need but still pays for. Compressing results to the signal reduces token consumption.

**What to build:**
- `compress_tool_result(tool_name, result)` post-processor that:
  - `list_dir`: removes `__pycache__`, `.git`, `node_modules` entries and summarizes them as `[+247 hidden build/cache files]`
  - `run_shell`/`run_python`: trims repeated lines (e.g. 50 identical warning messages → `[first warning] × 50`)
  - `web_search`: strips duplicate result descriptions, trims URL clutter
  - `db_query`: if >20 rows, show first 10 + `[... N more rows]`
  - `run_shell` with `git log`: strip hash detail, keep just message + author + date
- Apply compression before appending to conversation, always preserving `ok` and `error` fields
- Add `raw=true` param to any tool to bypass compression for debugging

**Expected savings:** 15–30% reduction on tool-heavy sessions.

---

### 0.7 · Memory Token Budget Enforcement

**Status:** Shipped in v0.3.0 for local recall. Memory recall now reports an approximate budget, injects compact matches before excerpts, and truncates individual node bodies.

**Why:** The memory recall injected into every system prompt can balloon unchecked. If the user has 500 memory nodes, a naive recall might inject 10,000 tokens of context — more than the response itself.

**What to build:**
- `MemoryManager.recall()` already accepts `budget_tokens` — make it actively enforce this:
  - Rank recalled nodes by relevance score (keyword match density)
  - Fill the budget greedily from highest-ranked nodes
  - Truncate individual node bodies at `max_node_tokens` (default: 200 tokens)
  - Report `[Memory: N nodes, M tokens used of budget]` in debug mode
- Config:
```toml
[memory]
recall_budget_tokens = 2000    # max tokens injected per turn
max_node_tokens = 200          # truncate individual nodes
max_nodes_recalled = 15        # hard cap on nodes recalled
```
- In-session: `/memory` shows current recall budget usage

**Expected savings:** Predictable, bounded memory injection — never more than configured budget regardless of graph size.

---

## Phase 1 — Core Robustness (Near-term)

These improvements harden the current feature set and fix the most impactful gaps before adding new capabilities.

---

### 1.1 · Model Context Protocol (MCP) Support

**Why:** MCP is fast becoming the standard for AI tool extensibility. Claude Code, Cline, OpenCode, and Cursor all support it. Adding MCP support lets MagAgent instantly tap into a universe of pre-built integrations — GitHub, Jira, Postgres, Notion, Figma, and hundreds more — without writing any adapter code.

**What to build:**
- `MCPClient` class wrapping the MCP spec (`mcp` Python SDK or direct JSON-RPC over stdio/HTTP)
- Config section `[mcp.servers.<name>]` with `command`, `args`, `env` per server
- MCP tool discovery: on session start, query each configured server for its tool list and inject them into the agent's tool definitions alongside built-ins
- MCP tool dispatch: route calls to the appropriate server process
- CLI: `magent mcp list` (show all MCP servers + tools), `magent mcp add <name> <command>`

**Config example:**
```toml
[mcp.servers.github]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-github"]
env = { GITHUB_TOKEN = "${GITHUB_TOKEN}" }

[mcp.servers.postgres]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-postgres", "postgresql://localhost/mydb"]
```

**Packages:** `mcp>=1.0` (official Python SDK)

---

### 1.2 · Codebase Repo-Map (Semantic Awareness)

**Status:** MVP shipped in v0.9.0. `magent code index` builds a lightweight Python symbol/import/test index, `magent code symbols` searches saved symbols, and `magent code related` reports likely tests and import peers. Broader tree-sitter language coverage and prompt-time repo-map injection remain future work.

**v0.10.0 update:** Test intelligence now covers common Python, JS/TS, Go, and Rust test naming patterns, includes `magent test explain`, and can use project-local `{tests}` command templates for targeted runs.

**v0.12.0 update:** Added `magent ui`, a live read-only local operations dashboard over workspace state, project doctor, patches, checkpoints, memory quality, docs search, and release checks.

**v0.11.0 update:** Added project command roles, project doctor, workspace status, patch preview/explain, release checks, and scriptable review failure thresholds.

**v0.13.0 update:** Polished the Rich TUI with a compact adaptive banner, shared theme styles, Markdown response panels, reusable status lines, and quieter non-duplicating streaming output.

**v0.14.0 update:** Added `magent context map` and `magent memory promote` to make the relationship between MagGraph memory and workbench state explicit.

**v0.14.1 update:** Added compatibility-safe modular hygiene by extracting tool execution and workbench storage primitives, plus packaged architecture boundary docs.

**v0.14.2 update:** Extracted CLI app composition into `magent.cli.app` so command registration is separate from command implementation behavior.

**v0.14.3 update:** Added command context helpers, workbench domain modules, tool helper modules, and typed record wrappers to continue compatibility-safe modularization.

**v0.15.0 update:** Added workflow recipes, memory inbox review, tool capability packs, project playbooks, and actionable local UI handlers for release checks, patch previews, checkpoint diffs, and memory promotion.

**v0.16.0 update:** Added sandboxed plan/recipe execution, local eval suites, Playwright browser helpers, GitHub PR/issue commands, a cockpit-oriented UI state, comparison docs, and repo demo assets.

**v0.18.0 update:** Added CLI-first setup commands for providers, model roles, memory behavior, gateway platforms, and sub-agent orchestration caps so most common configuration can happen through guided commands instead of direct TOML edits.

**v0.19.0 update:** Added guided onboarding, provider/model/memory/subagent wizards, project initialization, profile presets, doctor fix suggestions, next-action recommendations, and explicit OpenAI API vs Codex subscription plus OpenCode Zen vs Go access-mode distinctions.

**Why:** The agent currently reads files reactively when the model asks. A proactive repo-map gives the model a bird's-eye view of the entire codebase — file names, class/function signatures, import graphs — so it can navigate multi-file tasks without hallucinating about what exists. This is the single biggest quality-of-life improvement for coding tasks.

**What to build:**
- `RepoMap` class using `tree-sitter` to parse Python, JS/TS, Go, Rust, Ruby, Java into an AST
- Extract: file path, top-level classes, functions, their signatures, and docstrings
- Build a compact token-efficient text representation (like Aider's repo-map)
- Inject a truncated repo-map into the system prompt when `--project` is specified
- Rebuild incrementally on file changes (watch `.git/index` for changes)
- Store repo-map snapshot in the project's SQLite database for fast re-use

**Config:**
```toml
[project]
repo_map = true
repo_map_max_tokens = 4000
repo_map_languages = ["python", "typescript", "go"]
```

**Packages:** `tree-sitter>=0.23`, language grammar wheels (`tree-sitter-python`, `tree-sitter-typescript`, etc.)

---

### 1.3 · Checkpoint & Undo System

**Status:** Expanded in v0.8.0. MagAgent snapshots files before writes/edits/deletes, lists and restores checkpoints, shows checkpoint diffs, restores the latest checkpoint, and can diff/restore all checkpoints for an agent session.

**Why:** Before any file write, edit, or delete, snapshot the affected files. Users can then `/undo` the last N operations and restore exactly. This is the #1 trust-building feature — Cline's human-in-the-loop proved it decisively.

**What to build:**
- `CheckpointManager`: before every `write_file`, `edit_file`, `delete_file` tool call, snapshot the file content to a per-session checkpoint store (SQLite BLOB or git stash)
- `/undo [N]` slash command: restore the last N file operations
- `/undo list`: show checkpoint history with timestamps and file paths
- CLI: `magent undo` (undo last session's changes)
- Integration point: wrap `ToolExecutor` dispatch to call checkpoint before any write-tier tool

**Storage:** Append-only SQLite table per session:
```sql
CREATE TABLE checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    step INTEGER NOT NULL,
    tool_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    original_content BLOB,     -- NULL if file didn't exist
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

---

### 1.4 · Context Window Management & Conversation Summarization

**Status:** Partially shipped in v0.3.0. MagAgent now performs deterministic conversation compaction using recent-turn retention and compacted session state. LLM-authored summaries and token/cost telemetry remain future work.

**Why:** Long sessions hit model context limits and quality degrades. The agent needs to gracefully manage conversation history — summarizing old turns rather than truncating them blindly.

**What to build:**
- Track token count of the conversation using `litellm.token_counter()`
- When approaching the model's context limit (configurable threshold, default 80%), trigger an automatic summarization pass:
  - Send the last N turns to the extraction model: *"Summarize this conversation as a bullet list of: decisions made, code written, problems solved, and open items"*
  - Replace those turns in the conversation with a single `[Summary]` system message
  - Write summary to memory graph as a `session_summary` node
- Config: `context_window_threshold = 0.8`, `summarize_every_n_turns = 20`
- Visual indicator in the REPL when a summarization pass occurs

---

### 1.5 · Cost & Token Tracking

**Why:** Developers using paid APIs have no visibility into what sessions cost. A lightweight cost tracker lets users optimize their model usage.

**What to build:**
- Extract token usage from LiteLLM response objects (`usage.prompt_tokens`, `usage.completion_tokens`)
- Log to session JSONL: `{"event": "token_usage", "prompt": 1200, "completion": 400, "model": "...", "cost_usd": 0.0018}`
- Store aggregate stats in the user's `default` SQLite database (`_token_usage` table)
- CLI: `magent stats` — show total tokens used, estimated cost by model, by day
- In-session: `/cost` shows current session spend
- Use LiteLLM's `completion_cost()` for pricing — it has a built-in model cost database

---

## Phase 2 — Power Features (Medium-term)

Capabilities that significantly expand what MagAgent can do autonomously.

---

### 2.1 · Browser Automation via Playwright

**Why:** Web automation is a massive use case — scraping dynamic pages, testing web UIs, filling forms, taking screenshots for debugging. The current `web_fetch` tool can't handle JavaScript-rendered pages.

**What to build:**
- `BrowserTool` class wrapping `playwright-python`
- New tools exposed to the agent:
  - `browser_open(url)` — navigate to URL, wait for load
  - `browser_screenshot(path)` — capture current page as PNG
  - `browser_click(selector)` — click a CSS/XPath selector
  - `browser_type(selector, text)` — type into an input
  - `browser_extract(selector)` — extract text from matching elements
  - `browser_scroll(pixels)` — scroll the page
  - `browser_close()` — close browser session
- Persistent browser session within a conversation (one `Page` object reused)
- Permission tier: CONFIRM for `browser_open` (since it makes network requests), SILENT for screenshot/extract

**Optional skill:** `docs/skills/browser-automation/SKILL.md` with Playwright patterns

**Packages:** `playwright>=1.44` (requires `playwright install chromium`)

---

### 2.2 · Plan Mode (Draft Before Execute)

**Status:** MVP expanded in v0.8.0. `magent plan --save` stores durable plans, `magent plan-run` creates pending plan records with diff/review context, `magent plan-exec` buffers current diffs and shell commands as executable operations, `magent plan-preview` inspects them, `magent plan-discard` discards them, and `magent plan-apply` executes buffered operations and optional checks. Full intercepted live tool execution remains future work.

**Why:** For complex multi-file tasks, show the user a complete plan with diff previews before applying any changes. This reduces mistakes on large refactors.

**What to build:**
- `--plan` flag on the CLI: `magent --plan "Refactor auth to use JWTs"`
- In plan mode, all `write_file`, `edit_file`, `delete_file`, `run_shell` calls are intercepted and stored as a `Plan` object instead of executed
- After the agent's tool loop completes, display a rich diff summary:
  - Files to be created/modified/deleted
  - Shell commands to be run
  - Unified diffs for each file change
- User sees: `Apply this plan? [y/N/edit]`
  - `y` → execute all buffered operations in order
  - `N` → discard
  - `edit` → open interactive editor to remove specific steps
- Slash command: `/plan <task>` (same from REPL)

---

### 2.3 · Vector Memory Search (Semantic Similarity)

**Status:** Shipped in v0.5.0 as a local SQLite semantic sidecar. `magent memory index` builds embeddings from MagGraph nodes, `magent memory search` defaults to hybrid search, and `magent memory semantic status/reset` manages the sidecar. Ollama embeddings are used when available with deterministic offline vectors as fallback.

**Why:** The current memory search is keyword-based (ripgrep over Markdown). Semantic similarity search would let MagAgent surface memories like *"you solved a similar auth bug 3 months ago"* even if the exact words don't match.

**What shipped:**
- Rebuildable per-user SQLite vector index under `~/.config/magent/users/<user>/workbench/vector/`.
- MagGraph remains the source of truth; vectors are disposable derived cache.
- Hybrid search combines semantic similarity and keyword overlap, then falls back to keyword if the sidecar is empty.
- Agent recall can use semantic anchors before BFS traversal.
- CLI: `magent memory index`, `magent memory search --semantic "jwt refresh token bug"`, `magent memory search --keyword "jwt"`.

**Config:**
```toml
[memory]
semantic_enabled = true
semantic_model = "nomic-embed-text"
semantic_provider = "ollama"
```

**Packages:** no additional runtime dependency; uses stdlib SQLite and optional local Ollama HTTP.

---

### 2.4 · Workspace / Project Profiles

**Status:** Expanded in v0.8.0. Project profiles discover commands from package manifests, Makefiles, Justfiles, language manifests, and project-local `.magent/config.toml`; diagnostics records command outcomes; `magent project command-history` and `magent project command-promote` support command learning.

**Why:** Different projects have different rules — different linters, different shell commands to trust, different models to use. A per-project `.magent/config.toml` file lets the agent adapt automatically.

**What to build:**
- On session start with `--project <dir>`, check for `.magent/config.toml` in that directory
- Deep-merge project config over user config (project config wins on conflicts)
- Per-project config can specify: default model, permission overrides, trusted shell patterns, project-local skills directory, system prompt additions
- CLI: `magent project init` — scaffold `.magent/config.toml` in the current directory
- CLI: `magent project info` — show the merged effective config for the current project

**Example `.magent/config.toml`:**
```toml
[project]
name = "ecommerce-api"
description = "FastAPI e-commerce backend"

[defaults]
model = "anthropic/claude-3-5-sonnet-20241022"

[permissions]
allowed_shell_patterns = ["pytest *", "ruff *", "alembic *", "docker compose *"]

[memory]
write_every_n_turns = 3

[context]
system_prompt_extra = """
This is a FastAPI project using PostgreSQL, SQLAlchemy 2.0, and Alembic.
Always use async patterns. Follow existing patterns in src/api/.
"""
```

---

### 2.5 · Custom Agent Personas

**Why:** Different tasks benefit from different agent personalities. A "Security Auditor" persona focuses on finding vulnerabilities; a "Code Reviewer" focuses on readability and best practices; a "DevOps Engineer" focuses on deployment and infra.

**What to build:**
- `personas/` directory: `~/.config/magent/personas/<name>.toml`
- Persona defines: system prompt suffix, default model, tool restrictions, memory query bias
- CLI: `magent --persona security-auditor "Review src/auth.py for vulnerabilities"`
- Built-in personas shipped with MagAgent:
  - `default` — balanced generalist coding assistant
  - `code-reviewer` — focused on readability, patterns, test coverage
  - `security-auditor` — focused on OWASP, injection, auth flaws
  - `devops` — focused on Docker, CI/CD, IaC
  - `refactor` — focused on reducing complexity, improving architecture
  - `documenter` — focused on generating docstrings, READMEs, API docs
- `/persona <name>` in-session command to switch

---

### 2.6 · Task Queue & Background Execution

**Why:** Developers want to queue up multiple tasks ("fix all TODO comments", "add docstrings to every function", "write tests for every module") and let MagAgent work through them overnight without babysitting.

**What to build:**
- `TaskQueue` backed by the user's SQLite database (`_task_queue` table)
- CLI: `magent task add "Write unit tests for src/api/*.py"`
- CLI: `magent task list` — show pending/running/complete tasks
- CLI: `magent task run` — start processing queue (runs each task as an AgentSession, writes results to JSONL)
- CLI: `magent task run --daemon` — background mode with PID file
- Each task gets its own session log; on completion, sends a desktop notification
- Per-task timeout, retry count, and priority level

---

## Phase 3 — Ecosystem (Long-term)

Larger investments that position MagAgent as a platform rather than just a tool.

---

### 3.0 · Local Productivity Workbench

**Status:** Shipped in v0.4.0. MagAgent now includes durable local JSON-backed ledgers for tasks, artifacts, project profiles, inboxes, routines, follow-ups, knowledge notes, API bookmarks, patch queues, session timelines, policy profiles, and static dashboard export.

---

### 3.1 · Local Web Dashboard

**Status:** MVP expanded in v0.12.0. `magent dashboard` exports a local HTML dashboard, `magent dashboard --serve` serves it on localhost, and `magent ui` provides a live read-only local operations dashboard.

**Why:** A local web UI makes memory visualization, session history browsing, and task management accessible without memorizing CLI commands — especially useful for non-developer users and for debugging the memory graph visually.

**What to build:**
- Lightweight FastAPI server: `magent dashboard` — launches at `http://localhost:7820`
- Pages:
  - **Memory Graph** — interactive node/edge visualization (D3.js force graph)
  - **Sessions** — searchable session log history with full transcript replay
  - **Databases** — SQLite browser (table list, row viewer, query editor)
  - **Skills** — installed skills list, toggle active/inactive, SKILL.md viewer
  - **Providers** — test connections, show latency, token usage charts
  - **Gateway** — real-time gateway log tail, start/stop controls
- Read-only by default; write operations require a local auth token
- Auto-opens browser on `magent dashboard --open`

**Packages:** `fastapi>=0.111`, `uvicorn>=0.30`, `jinja2` (already installed)

---

### 3.2 · VS Code Extension

**Why:** Developers spend most of their time in VS Code. A lightweight extension that surfaces MagAgent's memory and tools without leaving the editor would dramatically increase daily usage.

**What to build:**
- VS Code extension (`vscode-magent`) communicating with a local MagAgent API server
- Features:
  - **Inline chat** in the editor — select code, right-click → "Ask MagAgent"
  - **Memory sidebar** — view/search the memory graph alongside your editor
  - **Terminal integration** — `magent` terminal spawns pre-configured in VS Code terminal
  - **File watcher** — notify MagAgent when files change for context-aware suggestions
  - **Status bar** — show active user, model, memory node count

**Architecture:** MagAgent runs an HTTP API server (`magent serve --port 7821`) that the extension calls. The extension itself is a thin TypeScript client.

---

### 3.3 · Plugin / Extension System

**Why:** A formal plugin system lets the community extend MagAgent with new tools, skills, and provider adapters — similar to how VS Code extensions work.

**What to build:**
- Plugin spec: a Python package with an `entry_points` group `magent.plugins`
- Each plugin declares: new tools, new skills, new provider configs, new CLI commands, system prompt extensions
- CLI: `magent plugin install <package>`, `magent plugin list`, `magent plugin remove`
- Plugin sandbox: plugins run in the same process but tool calls still go through the permission system
- Plugin manifest validation on install
- Official plugin index (a curated GitHub repo listing verified plugins)

**Example community plugins to seed:**
  - `magent-plugin-aws` — AWS CLI tools (S3, EC2, Lambda, CloudFormation)
  - `magent-plugin-docker` — Docker/Compose lifecycle management
  - `magent-plugin-linear` — Linear issue management via MCP
  - `magent-plugin-obsidian` — Read/write Obsidian vault notes

---

### 3.4 · Multi-Agent Orchestration

**Why:** Complex software projects need specialized agents working in parallel — an architect agent that designs the solution, a coder agent that implements it, a reviewer agent that critiques the result. This is the trajectory of the field.

**What to build:**
- `Orchestrator` class: takes a high-level goal, decomposes it into sub-tasks using a "planner" model
- Each sub-task is assigned to a `SubAgentSession` with a focused persona and tool subset
- Agents communicate through the shared memory graph and a shared SQLite coordination table
- Result synthesis: orchestrator collects sub-agent results and produces a unified output
- CLI: `magent orchestrate "Build a full CRUD REST API for a blog with tests and documentation"`
- Visual progress tree in the terminal showing each agent's status

**Coordination schema:**
```sql
CREATE TABLE orchestration_tasks (
    id TEXT PRIMARY KEY,
    parent_id TEXT,
    goal TEXT NOT NULL,
    persona TEXT,
    status TEXT DEFAULT 'pending',  -- pending/running/done/failed
    result TEXT,
    assigned_agent TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

---

### 3.5 · Voice Interface

**Why:** Hands-free coding is genuinely useful — while reading documentation, reviewing a design on a whiteboard, or when your hands are occupied. Voice input also lowers the barrier for less technical users.

**What to build:**
- STT (Speech-to-Text): `faster-whisper` for local transcription (no cloud, works offline, fast)
- TTS (Text-to-Speech): `pyttsx3` for system TTS or `kokoro-onnx` for high-quality local synthesis
- `magent --voice` flag: activates push-to-talk mode (hold Space to record, release to send)
- Configurable wake word (optional): say "Hey Mag" to activate without key press
- TTS output toggleable: agent's responses can be read aloud or just displayed
- Visual waveform indicator in terminal during recording

**Config:**
```toml
[voice]
enabled = false
stt_model = "base.en"       # faster-whisper model size
tts_engine = "pyttsx3"      # or "kokoro"
push_to_talk_key = "space"
```

**Packages:** `faster-whisper>=1.0` (optional extra), `pyttsx3>=2.9` (optional)

---

### 3.6 · E2B / Docker Sandboxed Code Execution

**Why:** The current `run_python` tool executes code in the same process as MagAgent. For untrusted code or production-like testing, a proper sandboxed execution environment is essential.

**What to build:**
- Abstract `CodeSandbox` interface with two implementations:
  - `DockerSandbox`: spin up a `python:3.12-slim` container, mount a temp workspace, exec code, capture output, destroy container
  - `E2BSandbox`: use [E2B](https://e2b.dev) cloud micro-VMs for ephemeral, internet-accessible environments with package install support
- Automatic fallback: if Docker is available use it; otherwise use local subprocess; E2B if configured
- Each sandbox session is scoped to a conversation (reuse the same container/VM for the session, destroy on exit)
- New tool `run_sandboxed(code, packages=[])` that auto-installs packages in the sandbox before running

**Config:**
```toml
[sandbox]
backend = "docker"    # docker | e2b | local
e2b_api_key = ""
docker_image = "python:3.12-slim"
timeout_seconds = 60
```

---

### 3.7 · Built-In Documentation and Self-Help

**Status:** Expanded in v0.9.0. MagAgent ships packaged Markdown docs, recipes, and a built-in `magent tutorial`; exposes `magent docs list/show/search/doctor/generate-reference`; includes an internal `magent_docs_search` tool; and has tests around docs packaging/search.

**v0.10.0 update:** Added packaged testing/reliability documentation, changelog, and expanded docs for dry-run plan apply, test explanations, and safer memory maintenance.

**v0.11.0 update:** Added packaged patch workflow docs and expanded release-readiness recipes.

**Why:** MagAgent should be able to explain itself without requiring the user to leave the terminal, open the README, or guess command syntax. A competitive general-use agent needs robust internal documentation for its own commands, configuration, workflows, memory model, safety model, and troubleshooting paths.

**What to build:**
- Add a versioned internal documentation bundle shipped inside the package, for example `magent/docs/`.
- Add `magent docs` commands:
  - `magent docs list` — list built-in topics
  - `magent docs show memory` — render a focused topic
  - `magent docs search "semantic memory"` — search packaged docs locally
  - `magent docs doctor` — report stale or missing generated docs
- Add an in-session help tool so the agent can retrieve its own docs before answering questions about MagAgent features.
- Generate command reference pages from Typer metadata during release so CLI docs stay in sync with the executable.
- Include troubleshooting docs for providers, permissions, MagGraph memory, semantic indexing, MCP, gateway setup, PyPI/install issues, and common project diagnostics.
- Add examples and recipes for real workflows: coding task, memory audit, patch queue, CI repair, local dashboard, remote gateway, and productivity workbench.
- Add tests that fail when documented commands disappear or when new commands ship without docs.

**Implementation:** Keep author-written guides as Markdown, generate command references into Markdown during release, and expose both through a tiny local search index. Reuse the semantic memory sidecar pattern for docs search if useful, but keep keyword search as the always-available baseline.

---

## Implementation Priority Matrix

| Enhancement | Impact | Effort | Priority |
|---|---|---|---|
| **Tool Output Budgets** | 🔥🔥🔥🔥🔥 | Low | **P0** |
| **Stale Result Pruning** | 🔥🔥🔥🔥 | Low | **P0** |
| **Memory Token Budget** | 🔥🔥🔥🔥 | Low | **P0** |
| **Smart File Reading** | 🔥🔥🔥🔥 | Low | **P0** |
| **Tool Response Compression** | 🔥🔥🔥 | Low | **P0** |
| **Prompt Caching** | 🔥🔥🔥🔥🔥 | Low | **P0** |
| **Selective Tool Injection** | 🔥🔥🔥🔥 | Medium | **P0** |
| MCP Support | 🔥🔥🔥🔥🔥 | Medium | **P1** |
| Checkpoint/Undo | 🔥🔥🔥🔥 | Low | **P1** |
| Repo-Map | 🔥🔥🔥🔥 | Medium | **P1** |
| Context Window Mgmt | 🔥🔥🔥🔥 | Low | **P1** |
| Cost Tracking | 🔥🔥🔥 | Low | **P1** |
| Built-In Documentation | 🔥🔥🔥🔥 | Medium | **P1** |
| Project Profiles | 🔥🔥🔥🔥 | Low | **P2** |
| Plan Mode | 🔥🔥🔥🔥 | Medium | **P2** |
| Vector Memory Search | 🔥🔥🔥 | Medium | **P2** |
| Browser Automation | 🔥🔥🔥🔥 | Medium | **P2** |
| Custom Personas | 🔥🔥🔥 | Low | **P2** |
| Task Queue | 🔥🔥🔥 | Medium | **P2** |
| Web Dashboard | 🔥🔥🔥 | High | **P3** |
| Plugin System | 🔥🔥🔥🔥🔥 | High | **P3** |
| Multi-Agent Orchestration | 🔥🔥🔥🔥🔥 | High | **P3** |
| VS Code Extension | 🔥🔥🔥🔥 | High | **P3** |
| Voice Interface | 🔥🔥🔥 | Medium | **P3** |
| E2B/Docker Sandbox | 🔥🔥🔥 | Medium | **P3** |

---

## Recommended First Sprint

If implementing today, start with these — highest impact, lowest effort:

1. **Tool Output Budgets** — Wrap `_budget_output()` around every tool return. One afternoon of work, immediate savings on every session.
2. **Stale Result Pruning** — One `ConversationPruner` class, applied after each tool append. Prevents long sessions from becoming expensive.
3. **Memory Token Budget** — Shipped in v0.3.0 for local recall; semantic reranking remains future work.
4. **Smart File Reading** — Shipped in v0.3.0 with `read_file_range`, `outline_file`, and large-file previews.
5. **Prompt Caching** — Restructure system prompt (static first, dynamic last). Zero-code-change for most providers.
6. **MCP Support** — After efficiency is solid, open the ecosystem. One `MCPClient` class + config section.

Implementing items 1–5 first means every subsequent session — including all the new features built after them — automatically runs leaner. The compounding effect is significant.

---

> *"The Magpie collects. The Magpie remembers. The Magpie improves."*
