# Troubleshooting

Start with:

- `magent doctor`
- `magent docs doctor`
- `magent memory stats`
- `magent memory semantic status`

Common issues:

- Provider errors: confirm API keys or local Ollama availability.
- New user unsure where to begin: run `magent --help` and use the Start Here panel,
  especially `magent configure`, `magent tutorial`, `magent doctor`, and `magent next`.
- `magent ask` appears quiet: update MagAgent. One-shot `ask` prints periodic progress lines in human-readable mode while keeping `--json` clean for scripts.
- `magent research` prints JSON unexpectedly: use `--no-json` on older builds. Newer builds use readable output by default and keep JSON behind `--json`.
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
- Project command roles: run `magent project doctor`.
- Undo an agent file change: run `magent checkpoint restore-last`.
- Patch apply confusion: run `magent patch preview <id>` and `magent patch explain <id>`.
- Workspace clutter: run `magent workspace clean-report`.
- Release readiness: run `magent release check`.
- Missing command docs: run `magent docs doctor`.
- A generated file is missing after an agent turn: run `magent checkpoint list` and
  ask MagAgent to inspect the exact expected path. MagAgent normalizes common
  tool argument aliases such as `file_path`, but older releases may have failed
  with `[Error: 'path']` before writing anything.
- A slash command wakes the agent unexpectedly: update MagAgent. Unknown slash
  commands are handled by the CLI and should now show `try /help` instead of
  becoming an agent prompt.
- A read-only pipeline asks for high-risk permission: update MagAgent. Common
  read-only chains such as `cat file | wc -l`, `pip list | grep`, and import
  probes should not repeatedly prompt. Read-only `curl`/`wget` inspection
  pipelines are auto-approved; uploads, output-file writes, and mutating HTTP
  methods still ask. Unknown or write-capable chains can still be approved
  `once`, for the `session`, or `always`.
- The agent asks to approve a huge heredoc or Python snippet to write a file:
  update MagAgent. Shell-based file writes are refused with guidance to use
  `write_file`/`edit_file`, so the model can correct course without another
  permission prompt.
- A tool looks hung: interactive sessions print `Still running <tool>...` after
  a few seconds and then periodically until the tool returns.
- `pip install --upgrade mag-agent` says every version requires a different
  Python: the `pip` executable is attached to an older Python. Use
  `python3 -m pip install --upgrade mag-agent` or install with
  `pipx install --python python3 mag-agent`.

For a clean first setup, run `magent setup`, create or switch to a user, then run `magent doctor`.
