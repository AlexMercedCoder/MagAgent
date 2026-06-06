# Troubleshooting

Start with:

- `magent doctor`
- `magent docs doctor`
- `magent memory stats`
- `magent memory semantic status`

Common issues:

- Provider errors: confirm API keys or local Ollama availability.
- Empty semantic search: run `magent memory index`.
- MagGraph errors: confirm `maggraph` is installed and the memory directory exists.
- Gateway issues: run `magent gateway status` and inspect `magent gateway logs`.
- GitHub Actions triage: run `magent ci --logs` in a repository with authenticated `gh`.
- Project checks: run `magent diagnostics`.
- Missing command docs: run `magent docs doctor`.

For a clean first setup, run `magent setup`, create or switch to a user, then run `magent doctor`.

