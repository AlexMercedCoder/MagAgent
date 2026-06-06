# Configuration

Global config lives at:

`~/.config/magent/config.toml`

User profile config lives at:

`~/.config/magent/users/<user>/profile.toml`

Common settings:

- default provider and model
- permission mode
- memory write behavior
- semantic memory provider and model
- model routing roles for coding, review, memory, cheap, and fallback use
- context compaction budgets
- MCP server definitions
- gateway adapter settings
- per-tool output budgets
- project-local `.magent/config.toml` commands and preferences

## CLI-First Setup

Most everyday configuration can be done from the CLI:

```bash
magent configure
magent onboard
magent profile list
magent profile apply coding-cloud
magent provider list
magent provider detect
magent provider set openai --model gpt-5 --api-key-env OPENAI_API_KEY
magent provider set openai --model gpt-5 --access codex
magent provider wizard
magent provider test
magent provider doctor
magent doctor --json
magent doctor --fix
magent next
```

Provider access modes are explicit:

- `openai --access api` uses MagAgent's in-process LiteLLM provider and `OPENAI_API_KEY`.
- `openai --access codex` records that you want Codex/ChatGPT-plan based workflows and checks for the `codex` CLI. Run `codex login` to sign in with ChatGPT.
- `opencode-zen --access payg` uses OpenCode Zen pay-as-you-go credits/API keys.
- `opencode-go --access subscription` uses the OpenCode Go subscription endpoint and `OPENCODE_GO_KEY`.

Use model roles to route specific work to specialized or cheaper models:

```bash
magent model roles
magent model set-role coding openai/gpt-5
magent model set-role review anthropic/claude-sonnet-4-5
magent model set-role memory ollama/qwen2.5:7b
magent model set-role cheap openrouter/deepseek/deepseek-chat
magent model set-role fallback "ollama/qwen2.5-coder:32b,openrouter/deepseek/deepseek-chat"
magent model clear-role cheap
magent model doctor
magent model wizard
```

Memory behavior can be changed per active user:

```bash
magent memory configure --mode inbox-first --semantic --write-every 3
magent memory configure --mode manual --no-semantic
magent memory wizard
```

Gateway platforms can be configured without pasting a TOML block:

```bash
magent gateway configure telegram --bot-token "$TELEGRAM_BOT_TOKEN" --allowed-user 12345
magent gateway configure slack --bot-token "$SLACK_BOT_TOKEN" --app-token "$SLACK_APP_TOKEN"
magent gateway wizard discord
magent gateway doctor
```

The main agent can spawn focused sub-agents. Configure the cap and parallelism with:

```bash
magent subagent configure --max 3 --parallel 2 --model-role coding
magent subagent status
magent subagent run "Audit the auth tests"
magent subagent wizard
```

The cap is enforced by the sub-agent runner. Set `--max 0` to disable sub-agent spawning.

Project-local config:

`<project>/.magent/config.toml`

Bootstrap it from the CLI:

```bash
magent project init
magent project wizard
```

Example:

```toml
[commands]
test = "pytest -q"
lint = "ruff check src tests"
build = ["python -m build"]
```

Provider role routing lets you keep a strong default model while steering specific work to
cheaper or more specialized models:

```toml
[models]
coding = "openai/gpt-4.1"
review = "anthropic/claude-sonnet-4"
memory = "ollama/qwen2.5:7b"
cheap = "opencode-go/deepseek-v4-flash"
fallback = ["ollama/qwen2.5-coder:32b", "openrouter/deepseek/deepseek-chat"]
```

Run `magent doctor` after changing config. It checks dependencies, providers, model
routing, MagGraph memory, semantic memory, MCP, gateway settings, and docs coverage.
