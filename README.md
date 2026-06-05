# MagAgent

> CLI-based local AI coding agent powered by **[MagGraph](https://github.com/AlexMercedCoder/MagGraph)** persistent memory.

MagAgent is a terminal-native AI coding assistant that **remembers you**. It uses MagGraph — a Rust-powered, in-process graph database — to build a persistent knowledge graph of your preferences, projects, patterns, and bookmarks. Every session makes it smarter about *your* workflow.

---

## Features

- 🧠 **Persistent Memory** — MagGraph stores knowledge as plain Markdown files in Git. Readable, versionable, and fully local.
- 🔌 **10+ Providers** — Ollama (local), Nous Portal, OpenCode Zen, OpenAI, Anthropic, Google, Groq, OpenRouter, LM Studio, AWS Bedrock.
- 👥 **Multi-User** — Each user has an isolated memory graph. Switch users in one command.
- 📚 **Skills System** — Extend the agent with SKILL.md files (project-local or global).
- 🤖 **Sub-Agents** — Spawn parallel agents for complex multi-file tasks (`/spawn`).
- 🛡️ **Smart Permissions** — Risk-tiered automation. No permission fatigue. Four modes: `silent`, `balanced`, `paranoid`, `yolo`.
- 📊 **Memory Auditability** — `magent memory stats` shows node/edge counts, disk usage, and activity.

---

## Quick Start

### Install

```bash
pip install magent
# or
pipx install magent
```

### First-time setup

```bash
magent setup
```

The wizard will:
1. Create a named user profile with isolated memory graph
2. Configure your preferred AI provider
3. Test the connection

### Start a session

```bash
magent
```

### One-shot task

```bash
magent "Refactor the auth module to use JWTs"
```

---

## Providers

| Provider | Config ID | Notes |
|---|---|---|
| **Ollama** | `ollama` | Local, free. Default. |
| **Nous Portal** | `nous-portal` | Hermes 4 + 200+ models |
| **OpenCode Zen** | `opencode-zen` | Curated coding models |
| **OpenAI** | `openai` | GPT-4o, GPT-5 |
| **Anthropic** | `anthropic` | Claude 3.5/4 |
| **Google** | `google` | Gemini 2.0 |
| **Groq** | `groq` | Fast inference |
| **OpenRouter** | `openrouter` | 200+ models aggregator |
| **LM Studio** | `lmstudio` | Local GUI models |
| **AWS Bedrock** | `bedrock` | Enterprise |
| **Custom** | `custom` | Any OpenAI-compat endpoint |

Switch model mid-session: `/model nous-portal/hermes-4`

---

## Commands

### User Management

```bash
magent user create alice    # Create a user
magent user switch alice    # Switch active user
magent user list            # List all users
magent user delete alice    # Delete a user (prompts for confirmation)
magent user current         # Show active user
```

### Memory

```bash
magent memory stats                      # Node/edge counts, disk usage
magent memory search "JWT auth"          # Search memory by keyword
magent memory show prefers_typescript    # View a node
magent memory traverse project_myapp    # BFS traversal from a node
magent memory delete old_node           # Delete a node
magent memory export --out backup.json  # Export all nodes
magent memory reset                     # Wipe all memory (with confirmation)
```

### Other

```bash
magent setup          # First-run wizard
magent mode balanced  # Set permission mode (silent|balanced|paranoid|yolo)
magent doctor         # Health check
magent --version      # Show version
```

### Slash Commands (in-session)

| Command | Description |
|---|---|
| `/help` | Show available commands |
| `/memory` | Memory graph stats |
| `/skills` | List loaded skills |
| `/model` | Show / change model |
| `/user` | Show active user |
| `/mode <mode>` | Change permission mode |
| `/clear` | Clear conversation history |
| `/spawn <task>` | Spawn a sub-agent |
| `/exit` | End session |

---

## Permission Modes

| Mode | Description |
|---|---|
| `balanced` *(default)* | Low-risk ops auto; medium requires Enter; high requires typed "yes" |
| `silent` | Only destructive ops prompt |
| `paranoid` | Everything except reads prompts |
| `yolo` | Everything auto-executes |

Pre-approve shell patterns in your profile:
```toml
[permissions]
allowed_shell_patterns = ["git *", "npm *", "pytest *"]
```

---

## Skills

Place `SKILL.md` files in:
- `~/.config/magent/skills/<skill-name>/SKILL.md` — global
- `.magent/skills/<skill-name>/SKILL.md` — project-local

See [`docs/skills/git-workflow/SKILL.md`](docs/skills/git-workflow/SKILL.md) for an example.

---

## Memory Graph

Memory is stored in `~/.config/magent/users/<name>/memory/` as plain Markdown files.
Each node has a type, body, and edges (wikilinks).

Node types: `preference`, `project`, `pattern`, `skill_learned`, `fact`,
`session_summary`, `error_pattern`, `contact`, `bookmark`

Memories are written every **5 turns** (configurable) and always at session end.

---

## Configuration

`~/.config/magent/config.toml`:

```toml
[defaults]
provider = "ollama"
model = "qwen2.5-coder:32b"
permission_mode = "balanced"

[memory]
write_every_n_turns = 5
extraction_provider = "ollama"
extraction_model = "qwen2.5:7b"
encrypt = false

[providers.nous-portal]
base_url = "https://inference-api.nousresearch.com/v1"
api_key_env = "NOUS_API_KEY"
default_model = "nous-hermes-4"

[providers.ollama]
base_url = "http://localhost:11434"
default_model = "qwen2.5-coder:32b"
```

---

## Development

```bash
git clone https://github.com/AlexMercedCoder/MagAgent.git
cd MagAgent
pip install -e ".[dev]"
pytest
```

---

## License

Apache 2.0 — see [LICENSE](LICENSE)
