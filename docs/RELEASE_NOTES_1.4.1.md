# MagAgent 1.4.1

Release notes, November 6, 2026.

A patch release for the bugs the *Graph Engineering with AI Agents* Appendix B walkthrough found
in 1.4.0. The full list, with handoff ids M1-M5, is in the
[CHANGELOG](../CHANGELOG.md#141-2026-11-06).

## Fixes

- **A core install works again.** LiteLLM 1.108 imports the MCP SDK on every completion without
  declaring it, so `pip install mag-agent` without extras failed every model call, the offline
  `mock` provider included. The MCP SDK is now a core dependency, and CI installs the core
  package alone and runs one mock completion.
- **Graphs see project skills.** `requirements.skills` is checked against the same skills a
  session in the project loads, including `.magent/skills/`.
- **Command criteria follow your permission policy.** A criterion command the node's
  `shell:exec` permissions grant and `permissions.allowed_shell_patterns` allows now runs without
  a prompt under `balanced`, `--yes` included, so `magent mode silent` is no longer needed for
  the walkthrough. The policy still outranks the graph. A refused criterion records `RT017`
  naming the command and what refused it, instead of an empty result.
- **Retries say what failed.** Retry feedback carries each failed criterion's `description` with
  its evidence (AGS 10.3), and node `instructions` reach the prompt.
- **Spec diagnostic codes and an honest summary.** Runtime codes follow AGS 1.0 where the
  specification defines one (for example `RT041` for an unbound graph output, `RT033` for a
  missing output), and `magent graph run` counts succeeded, failed and skipped nodes correctly.

## Behavior changes

- Several runtime diagnostic codes changed number; see the
  [Agentic Graphs guide](../src/magent/docs/agentic-graphs.md#diagnostic-codes) for the full
  list. Tools that match on the old numbers need updating.
- Command criteria no longer require `shell_exec` in the node's tools and no longer count against
  the node's tool-call budget. A command outside the node's `shell:exec` permissions is still
  refused, now with `RT017`.
- `mcp>=2.0,<3` is installed by the core package.

## Upgrading

```bash
python -m pip install --upgrade mag-agent
```
