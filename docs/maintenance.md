# MagAgent maintenance tracker

Audited 2026-11-24 against checkout `fa83c65`. The nine migration tests passed. Both observations below used temporary state directories.

Claim a row by entering your name or task ID and setting the status to **In progress**. Use **Blocked** with the missing dependency if needed. Set **Done** after the acceptance check passes and record the fix commit or PR, the command or manual check, and its result. If a newer revision already resolves the item, record that evidence and close it. Keep status in this table.

| ID | Priority | Status | Owner | Fix and verification |
| --- | --- | --- | --- | --- |
| MAG-01 | P1 | Open | — | — |
| MAG-02 | P2 | Open | — | — |

### MAG-01 · Reject malformed state versions before startup or migration

**Reproduced.** `assert_supported_state()` accepted `true` and `-1` as schema versions. [src/magent/state_schema.py](../src/magent/state_schema.py) checks isinstance(value, int), then only enforces an upper bound. [src/magent/migrations.py](../src/magent/migrations.py) consumes that value.

**Acceptance check.** Test both invalid markers through migration planning and startup. Each should report an incompatible marker without rewriting state. Preserve behavior for a missing legacy marker, supported integer, and newer integer.

### MAG-02 · Keep provider cooldown diagnostics usable after a bad record

**Reproduced.** A cooldown file containing `[]` raises AttributeError in `list_provider_cooldowns()` and stops the entire listing. The JSON read is guarded but the subsequent `.get()` is outside that guard in [src/magent/provider_cooldown.py](../src/magent/provider_cooldown.py).

**Acceptance check.** Place a valid active record beside malformed JSON, an array and a record with a bad reset time. The provider cooldown command should still return the active record and a usable diagnostic for bad entries. Preserve valid files.
