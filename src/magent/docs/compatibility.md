# Compatibility and State Migration

MagAgent 0.90 freezes the proposed 1.0 stable contract set. Inspect it without reading
source code:

```bash
magent system contracts
magent system compatibility
```

The inventory labels every listed CLI command as stable or beta, lists supported public
Python imports, enumerates global and user configuration keys without values, and includes
task, event, plugin, memory, MCP, Agentic Graph, and desktop contracts. Experimental MCP
extensions remain outside the support promise.

## Persistent state

Persistent state has its own schema marker under `~/.config/magent/state.json`. A missing
marker means pre-0.90 legacy state. Preview and apply its migration with:

```bash
magent system migrate
magent system migrate --apply
```

Apply always creates a private ZIP backup before changing files. The first migration copies
legacy subagent and shell-approval keys into their stable locations, preserves unknown keys,
writes a sanitized migration history, and adds the version marker.

Rollback is also preview-first:

```bash
magent system rollback ~/.config/magent/migration-backups/magent-state-TIMESTAMP.zip
magent system rollback ~/.config/magent/migration-backups/magent-state-TIMESTAMP.zip --apply
```

Archives are rejected if a member is absolute or traverses outside the state root. An older
runtime refuses a newer schema with an actionable error. It never silently downgrades or
rewrites state it does not understand.
