# Prompt Caching

MagAgent keeps provider prompts cache-friendly by separating the stable agent
instructions from volatile memory, repo, session, and skill context. Providers
that support automatic prefix caching can reuse the stable first system message
across turns and sessions when the prefix is large enough and unchanged.

Useful commands:

- `magent cache doctor`: inspect the configured provider/model cache posture.
- `magent cache doctor --json`: return machine-readable cache diagnostics.
- `magent cache status`: summarize cached token telemetry from local session logs.

Config fields:

```toml
[context]
prompt_caching = true
prompt_cache_key_scope = "project" # project, session, or user
prompt_cache_retention = ""        # provider-specific, optional
prompt_cache_min_stable_tokens = 1024
```

Provider notes:

- OpenAI supports automatic prefix caching and accepts cache-affinity hints such
  as `prompt_cache_key`.
- Anthropic and Bedrock support explicit cache checkpoints on supported models;
  MagAgent reports this capability but keeps explicit checkpoints conservative
  until the provider path has been smoke tested.
- Gemini supports implicit caching and explicit cached content for large
  contexts.
- DeepSeek exposes prompt cache hit/miss token telemetry.
- OpenRouter and OpenAI-compatible gateways depend on the routed upstream model;
  MagAgent uses stable prompt ordering and sticky session hints where available.

Best practices:

- Keep the stable agent/persona instructions boringly stable.
- Put current memory, repo slices, tool results, and active task text after the
  stable prefix.
- Avoid changing the global system prompt between turns unless the behavior
  really changed.
- Use `magent cache status` after several similar sessions to see whether the
  provider reports cached tokens.
