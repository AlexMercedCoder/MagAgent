# MagAgent 1.4.3

This patch improves state validation and provider cooldown diagnostics.

- Startup and migration planning reject boolean and negative schema markers before changing state.
- Provider cooldown diagnostics report malformed records while continuing to list valid cooldowns.
