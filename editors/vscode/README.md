# MagAgent for VS Code (preview)

A minimal VS Code extension that drives a locally installed MagAgent through its stable machine
API. It is not published to the Marketplace; build and install it yourself.

## What it does

- **MagAgent: Ask** and **MagAgent: Ask About Selection** run `magent ask` in the first
  workspace folder. Status lines stream to the *MagAgent* output channel and the reply opens as
  a Markdown document. **MagAgent: Cancel Run** stops a run.
- When a run needs approval (a shell command, a file outside the project, ...), VS Code shows a
  modal with the exact action, risk and arguments and the choices MagAgent offered. Closing the
  modal denies the action; nothing is approved by default.
- **MagAgent: Show Memory Used by Last Run** shows which memory nodes the last run recalled
  (`magent memory evidence last --json`), including team-memory nodes.

## How it talks to MagAgent

Only public, versioned CLI contracts (see `magent docs show desktop-integration`):

- `magent ask --prompt-file <tmp> --project <folder> --json --events --approval-stdio
  [--permission-mode <mode>]`: stdout carries AAIS 1.0 NDJSON envelopes, then one result
  document; decisions go back as `approval.decided` lines on stdin. The prompt goes through a
  private temporary file, never argv.
- `magent memory evidence last --json` (`magent.run-memory-evidence.v1`).

## Settings

| Setting | Default | Meaning |
| --- | --- | --- |
| `magagent.executable` | `magent` | Command to run; `python -m magent` also works. |
| `magagent.permissionMode` | `balanced` | Permission mode for runs started here. |

## Build and install locally

```bash
cd editors/vscode
npm ci
npm test           # unit tests against a scripted stand-in for magent
npm run build      # compiles to dist/
npx @vscode/vsce package --no-dependencies   # optional: make a .vsix to install
```

Requires MagAgent 1.4 or later (for `--prompt-file`, clean `--json` stdout and memory evidence).
`test/real-magent.test.ts` runs against a real MagAgent when `MAGENT_REAL_EXECUTABLE` is set.
