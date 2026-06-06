# Config Reference

Generated from MagAgent's packaged default config and provider metadata.

## Global Config

Stored at `~/.config/magent/config.toml`.

### `agent`

- `agent.name` default: `'MagAgent'`
- `agent.version` default: `'0.24.0'`
- `agent.selective_tools` default: `True`
- `agent.max_subagents` default: `3`
### `defaults`

- `defaults.provider` default: `'ollama'`
- `defaults.model` default: `'qwen2.5-coder:32b'`
- `defaults.permission_mode` default: `'balanced'`
- `defaults.context_window_tokens` default: `32000`
- `defaults.memory_budget_tokens` default: `4000`
- `defaults.repo_map_budget_tokens` default: `1200`
- `defaults.skill_budget_tokens` default: `2000`
### `memory`

- `memory.auto_write` default: `True`
- `memory.auto_commit` default: `False`
- `memory.write_every_n_turns` default: `5`
- `memory.extraction_provider` default: `'ollama'`
- `memory.extraction_model` default: `'qwen2.5:7b'`
- `memory.encrypt` default: `False`
- `memory.recall_body_tokens` default: `220`
- `memory.semantic_enabled` default: `True`
- `memory.semantic_provider` default: `'ollama'`
- `memory.semantic_model` default: `'nomic-embed-text'`
- `memory.semantic_top_k` default: `8`
### `context`

- `context.compact_every_n_turns` default: `10`
- `context.keep_recent_turns` default: `6`
- `context.max_history_tokens` default: `6000`
- `context.prune_stale_tool_results` default: `True`
- `context.prompt_caching` default: `True`
### `tool_budgets`

- `tool_budgets.default` default: `8000`
- `tool_budgets.read_file` default: `16000`
- `tool_budgets.read_file_range` default: `12000`
- `tool_budgets.web_fetch` default: `12000`
- `tool_budgets.run_shell` default: `10000`
- `tool_budgets.run_python` default: `10000`
- `tool_budgets.search_codebase` default: `9000`
- `tool_budgets.db_query` default: `8000`
### `skills`

- `skills.lockfile` default: `'~/.config/magent/skills.lock'`
### `ui`

- `ui.theme` default: `'dark'`
- `ui.stream_output` default: `True`
- `ui.show_tool_calls` default: `True`
- `ui.show_memory_writes` default: `False`
### `providers`

### `models`

- `models.coding` default: `''`
- `models.review` default: `''`
- `models.memory` default: `''`
- `models.cheap` default: `''`
- `models.fallback` default: `[]`
### `subagents`

- `subagents.max_subagents` default: `3`
- `subagents.max_parallel_subagents` default: `2`
- `subagents.model_role` default: `'coding'`
- `subagents.sandbox_mode` default: `''`
### `mcp`


## User Profile

Stored at `~/.config/magent/users/<user>/profile.toml`.

### `preferences`

- `preferences.default_provider` default: `''`
- `preferences.default_model` default: `''`
- `preferences.theme` default: `'dark'`
- `preferences.memory_budget_tokens` default: `4000`
### `permissions`

- `permissions.mode` default: `'balanced'`
- `permissions.auto_commit_memory` default: `False`
- `permissions.allowed_shell_patterns` default: `['git *', 'npm *', 'cargo *', 'pytest *', 'python *', 'pip *']`
### `memory`

- `memory.auto_write` default: `True`
- `memory.write_every_n_turns` default: `5`
- `memory.max_nodes` default: `10000`
- `memory.encrypt` default: `False`

## Model Roles

Use `magent model set-role <role> <provider/model>` and `magent model health`.

- `coding`
- `review`
- `memory`
- `cheap`
- `fallback`

## Permission Modes

Use `magent permission explain <mode>` and `magent permission set <mode>`.

- `balanced`: Default. Auto-run low-risk actions, confirm medium/high risk actions.
- `paranoid`: Only silent reads run automatically; almost every action asks first.
- `silent`: Auto-run most low and medium risk actions; tier-3 actions still require typed confirmation.
- `yolo`: Auto-run almost everything. Useful only in externally sandboxed environments.

## Provider IDs

Use `magent provider matrix` and `magent provider test-matrix` for live readiness.

- `opencode-go`
- `ollama`
- `lmstudio`
- `openai`
- `anthropic`
- `nous-portal`
- `opencode-zen`
- `google`
- `groq`
- `openrouter`
- `bedrock`
- `mistral`
- `deepseek`
- `xai`
- `perplexity`
- `cerebras`
- `together_ai`
- `fireworks_ai`
- `deepinfra`
- `custom`
