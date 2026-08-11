# Provider Reference

Generated from `magent.provider_catalog`.

| Provider | ID | Default Model | Access | Env | Runtime | Tier | Evidence |
|---|---|---|---|---|---|---|---|
| OpenCode Go | `opencode-go` | `deepseek-v4-flash` | subscription | `OPENCODE_GO_KEY` | openai-compatible | compatible | 2026-08-11 |
| Ollama (local) | `ollama` | `qwen2.5-coder:32b` | local |  | ollama | compatible | 2026-08-11 |
| LM Studio (local) | `lmstudio` | `local-model` | local |  | openai-compatible | compatible | 2026-08-11 |
| OpenAI | `openai` | `gpt-5` | api | `OPENAI_API_KEY` | openai | compatible | 2026-08-11 |
| Anthropic | `anthropic` | `claude-sonnet-5` | api | `ANTHROPIC_API_KEY` | anthropic | compatible | 2026-08-11 |
| Nous Portal | `nous-portal` | `deepseek/deepseek-v4-flash` | api | `NOUS_API_KEY` | openai-compatible | qualified | 2026-08-11 |
| OpenCode Zen | `opencode-zen` | `deepseek-v4-flash` | payg | `OPENCODE_ZEN_KEY` | openai-compatible | compatible | 2026-08-11 |
| Google Gemini | `google` | `gemini-3.6-flash` | api | `GEMINI_API_KEY` | gemini | compatible | 2026-08-11 |
| Groq | `groq` | `llama-3.3-70b-versatile` | api | `GROQ_API_KEY` | groq | compatible | 2026-08-11 |
| OpenRouter | `openrouter` | `deepseek/deepseek-chat` | api | `OPENROUTER_API_KEY` | openrouter | compatible | 2026-08-11 |
| TrustedRouter | `trusted-router` | `trustedrouter/cheap` | api | `TRUSTEDROUTER_API_KEY` | openai-compatible | compatible | 2026-08-11 |
| Prime Intellect | `prime-intellect` | `meta-llama/llama-3.1-70b-instruct` | api | `PRIME_INTELLECT_API_KEY` | openai-compatible | compatible | 2026-08-11 |
| AWS Bedrock | `bedrock` | `anthropic.claude-3-5-sonnet-20240620-v1:0` | aws |  | bedrock | compatible | 2026-08-11 |
| Mistral AI | `mistral` | `mistral-large-latest` | api | `MISTRAL_API_KEY` | mistral | compatible | 2026-08-11 |
| DeepSeek | `deepseek` | `deepseek-chat` | api | `DEEPSEEK_API_KEY` | deepseek | compatible | 2026-08-11 |
| xAI | `xai` | `grok-4` | api | `XAI_API_KEY` | xai | compatible | 2026-08-11 |
| Perplexity | `perplexity` | `sonar-pro` | api | `PERPLEXITYAI_API_KEY` | perplexity | compatible | 2026-08-11 |
| Cerebras | `cerebras` | `llama3.1-8b` | api | `CEREBRAS_API_KEY` | cerebras | compatible | 2026-08-11 |
| Together AI | `together_ai` | `moonshotai/Kimi-K2.5` | api | `TOGETHERAI_API_KEY` | together_ai | compatible | 2026-08-11 |
| Fireworks AI | `fireworks_ai` | `accounts/fireworks/models/deepseek-coder-v2-instruct` | api | `FIREWORKS_API_KEY` | fireworks_ai | compatible | 2026-08-11 |
| DeepInfra | `deepinfra` | `openai/gpt-oss-120b` | api | `DEEPINFRA_API_KEY` | deepinfra | compatible | 2026-08-11 |
| Custom Endpoint | `custom` | `your-model-name` | api |  | openai-compatible | compatible | 2026-08-11 |

Use `magent provider matrix`, `magent provider explain <provider>`, and `magent provider env` for live readiness details.

MagAgent prefers the canonical environment variable shown in the table, but it also accepts common aliases. Diagnostics report which non-secret variable name was found.

- `opencode-go` also accepts `OPENCODE_KEY`.
- `nous-portal` also accepts `NOUS_KEY`.
- `opencode-zen` also accepts `OPENCODE_ZEN_API_KEY`, `OPENCODE_KEY`.
- `openrouter` also accepts `OPENROUTER_KEY`.
- `trusted-router` also accepts `TRUSTED_ROUTER_API_KEY`.
- `prime-intellect` also accepts `PRIMEINTELLECT_API_KEY`, `PRIME_API_KEY`.
