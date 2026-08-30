# Config Reference

Generated from MagAgent's packaged default config and provider metadata.

## Global Config

Stored at `~/.config/magent/config.toml`.

### `agent`

- `agent.name` default: `'MagAgent'`
- `agent.version` default: `'0.99.0'`
- `agent.selective_tools` default: `True`
- `agent.max_subagents` default: `3`
- `agent.max_model_rounds_per_turn` default: `16`
- `agent.max_tool_calls_per_turn` default: `80`
- `agent.max_identical_tool_calls_per_turn` default: `3`
- `agent.max_failed_same_tool_per_turn` default: `2`
- `agent.doom_loop_policy` default: `'halt'`
- `agent.tool_use_enforcement` default: `'auto'`
- `agent.file_mutation_verifier` default: `True`
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
- `context.instructions` default: `[]`
- `context.prune_stale_tool_results` default: `True`
- `context.prompt_caching` default: `True`
- `context.prompt_cache_key_scope` default: `'project'`
- `context.prompt_cache_retention` default: `''`
- `context.prompt_cache_min_stable_tokens` default: `1024`
### `tool_budgets`

- `tool_budgets.default` default: `8000`
- `tool_budgets.read_file` default: `16000`
- `tool_budgets.read_file_range` default: `12000`
- `tool_budgets.web_fetch` default: `12000`
- `tool_budgets.run_shell` default: `10000`
- `tool_budgets.run_python` default: `10000`
- `tool_budgets.search_codebase` default: `9000`
- `tool_budgets.db_query` default: `8000`
### `budgets`

- `budgets.session_usd` default: `0.0`
- `budgets.daily_usd` default: `0.0`
- `budgets.warn_at` default: `0.8`
### `permissions`

- `permissions.shell_sandbox` default: `'off'`
- `permissions.shell_sandbox_network` default: `False`
- `permissions.allowed_shell_patterns` default: `[]`
- `permissions.trusted_shell_patterns` default: `[]`
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
- `models.frontier` default: `''`
- `models.memory` default: `''`
- `models.cheap` default: `''`
- `models.image_maker` default: `''`
- `models.fallback` default: `[]`
### `subagents`

- `subagents.max_subagents` default: `3`
- `subagents.max_parallel_subagents` default: `2`
- `subagents.model_role` default: `'coding'`
- `subagents.sandbox_mode` default: `''`
### `agraph`

### `agraph.tier_roles`

- `agraph.tier_roles.minimal` default: `'cheap'`
- `agraph.tier_roles.standard` default: `'coding'`
- `agraph.tier_roles.advanced` default: `'coding'`
- `agraph.tier_roles.frontier` default: `'frontier'`
- `agraph.allow_command_criteria` default: `True`
- `agraph.max_parallel_nodes` default: `2`
### `mcp`

### `session_messaging`

- `session_messaging.enabled` default: `True`
- `session_messaging.name` default: `''`
- `session_messaging.policy` default: `'accept'`
- `session_messaging.headless_accept` default: `False`
### `agent_profiles`

- `agent_profiles.enabled` default: `True`
- `agent_profiles.default_profile` default: `'magagent'`
- `agent_profiles.user_paths` default: `['~/.config/magent/agents', '~/.agentprofiles']`
- `agent_profiles.project_paths` default: `['.magent/agents', '.agents']`
- `agent_profiles.writeback` default: `'propose'`
- `agent_profiles.max_state_tokens` default: `1200`
- `agent_profiles.max_state_bytes` default: `200000`
- `agent_profiles.max_profiles` default: `200`
- `agent_profiles.max_delegation_depth` default: `3`

## User Profile

Stored at `~/.config/magent/users/<user>/profile.toml`.

### `preferences`

- `preferences.default_provider` default: `''`
- `preferences.default_model` default: `''`
- `preferences.default_agent_profile` default: `''`
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
- `image_maker`
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
- `trusted-router`
- `prime-intellect`
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
