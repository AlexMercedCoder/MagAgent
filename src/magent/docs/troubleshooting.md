# Troubleshooting

Start with:

- `magent doctor`
- `magent docs doctor`
- `magent memory stats`
- `magent memory semantic status`

Common issues:

- Provider errors: confirm API keys or local Ollama availability.
- Empty semantic search: run `magent memory index`.
- No code symbols: run `magent code index` from the project root.
- Missing targeted tests: run `magent test map` and confirm tests use `test_*.py` names.
- Unexpected targeted tests: run `magent test explain <file>` to see match reasons.
- Noisy memory recall: run `magent memory quality`, then merge or suppress stale nodes.
- Accidental memory suppression: run `magent memory unsuppress <node-id>`.
- Model routing not used: run `magent doctor` and check the `[models]` table.
- MagGraph errors: confirm `maggraph` is installed and the memory directory exists.
- Gateway issues: run `magent gateway status` and inspect `magent gateway logs`.
- GitHub Actions triage: run `magent ci --logs` in a repository with authenticated `gh`.
- GitHub Actions repair planning: run `magent ci --repair-plan`.
- Project checks: run `magent diagnostics`.
- Project command discovery: run `magent project commands`.
- Undo an agent file change: run `magent checkpoint restore-last`.
- Missing command docs: run `magent docs doctor`.

For a clean first setup, run `magent setup`, create or switch to a user, then run `magent doctor`.
