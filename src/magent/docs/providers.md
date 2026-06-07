# Provider Reference

Generated from `magent.provider_catalog`.

| Provider | ID | Default Model | Access | Env | Runtime |
|---|---|---|---|---|---|
| OpenCode Go | `opencode-go` | `deepseek-v4-flash` | subscription | `OPENCODE_GO_KEY` | openai-compatible |
| Ollama (local) | `ollama` | `qwen2.5-coder:32b` | local |  | ollama |
| LM Studio (local) | `lmstudio` | `local-model` | local |  | openai-compatible |
| OpenAI | `openai` | `gpt-5` | api | `OPENAI_API_KEY` | openai |
| Anthropic | `anthropic` | `claude-sonnet-4-5` | api | `ANTHROPIC_API_KEY` | anthropic |
| Nous Portal | `nous-portal` | `deepseek/deepseek-v4-flash` | api | `NOUS_API_KEY` | openai-compatible |
| OpenCode Zen | `opencode-zen` | `deepseek-v4-flash` | payg | `OPENCODE_ZEN_KEY` | openai-compatible |
| Google Gemini | `google` | `gemini-2.0-flash` | api | `GEMINI_API_KEY` | gemini |
| Groq | `groq` | `llama-3.3-70b-versatile` | api | `GROQ_API_KEY` | groq |
| OpenRouter | `openrouter` | `deepseek/deepseek-chat` | api | `OPENROUTER_API_KEY` | openrouter |
| AWS Bedrock | `bedrock` | `anthropic.claude-3-5-sonnet-20240620-v1:0` | aws |  | bedrock |
| Mistral AI | `mistral` | `mistral-large-latest` | api | `MISTRAL_API_KEY` | mistral |
| DeepSeek | `deepseek` | `deepseek-chat` | api | `DEEPSEEK_API_KEY` | deepseek |
| xAI | `xai` | `grok-4` | api | `XAI_API_KEY` | xai |
| Perplexity | `perplexity` | `sonar-pro` | api | `PERPLEXITYAI_API_KEY` | perplexity |
| Cerebras | `cerebras` | `llama3.1-8b` | api | `CEREBRAS_API_KEY` | cerebras |
| Together AI | `together_ai` | `moonshotai/Kimi-K2.5` | api | `TOGETHERAI_API_KEY` | together_ai |
| Fireworks AI | `fireworks_ai` | `accounts/fireworks/models/deepseek-coder-v2-instruct` | api | `FIREWORKS_API_KEY` | fireworks_ai |
| DeepInfra | `deepinfra` | `openai/gpt-oss-120b` | api | `DEEPINFRA_API_KEY` | deepinfra |
| Custom Endpoint | `custom` | `your-model-name` | api |  | openai-compatible |

Use `magent provider matrix`, `magent provider explain <provider>`, and `magent provider env` for live readiness details.

`magent configure` can save a cloud provider key in local MagAgent config,
reference an environment variable, or skip credentials for later. Saved keys are
redacted in config output. Interactive sessions preflight credential readiness
before opening the prompt so missing keys produce an actionable setup hint
instead of a provider authentication traceback.
