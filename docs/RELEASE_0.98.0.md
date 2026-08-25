# MagAgent 0.98.0

Status: released 2026-08-25.

MagAgent 0.98.0 rebuilds the local Web UI on a real toolchain and makes a turn survive the browser
that asked for it. 0.97.0 delivered the workspace; this release makes it durable, reviewable, and
accessible, and closes a configuration bug that reached well beyond the browser.

## Highlights

- **A turn is a run.** It executes on its own thread and records its reply whether or not anyone is
  watching. Closing the tab mid-reply used to kill the work with the socket: the answer was never
  recorded and the conversation kept a question with no response.
- **Reattachment.** Streams read an append-only event log from a cursor, and a reloading tab finds
  its run by conversation, so reconnecting replays what it missed instead of losing it. Only a
  still-running turn is resumed; a finished one already wrote its reply.
- **Stop actually stops.** It cancelled the socket and left the turn running on the server, still
  spending tokens. It now cancels the run, checked between chunks and between group participants,
  and keeps whatever was already said rather than letting it vanish.
- **Tool approvals reach the browser.** The Web UI has a user but no console, so without somewhere
  to ask it could only refuse every tool above the permission mode's auto-approve threshold: the
  agent could not do real work and never explained why. A tool needing a decision now pauses the
  turn and asks in the transcript. Unanswered is a denial.
- **Memory.** A read-only browser over the memory graph: size and health, full note text, and the
  notes linking to and from each one, searchable in the same modes the agent's own recall uses.
- **First run.** Opening the UI on a machine that has never been set up shows a setup panel rather
  than a composer whose first message is guaranteed to fail. It never accepts a credential.
- **A React and TypeScript frontend.** The interface was 30 KB of hand-minified JavaScript across
  six views with no build step, which could not be reviewed in a diff or tested. It is now compiled
  by Vite, unit tested, and verified against its committed bundle in CI.

## Fixes

- **Configuration leaked into the process-wide default.** `load_global_config` shallow-copied
  `DEFAULT_GLOBAL_CONFIG`, and `_deep_merge` aliased it the same way, so every nested container a
  caller did not replace pointed at the module-level dict. Writing to `cfg["providers"]` edited the
  default for the whole process, and a later load — for a different user or a different workspace —
  inherited that provider entry including an inline `api_key`. Every `configure_*` path mutates a
  loaded config, so all of them were affected. Both paths now deep-copy.
- Readiness called the shipped default provider ready on machines that had never installed Ollama,
  because a local provider needs no key; the first message then failed with a connection error. The
  local runtime is now probed directly.
- `GET /api/conversations` always returned 405: the blanket "mutating paths refuse GET" guard caught
  the list branch too, making it dead code.
- `magent dashboard --serve` bound its socket and then aborted, rendering the live server handle as
  part of its JSON result.
- A daemon cancellation test failed about one run in five on ordinary machine load. Two timing
  assumptions were too tight and neither concerned cancellation.

## Accessibility

Two audit passes run against a live server, because the properties that matter are computed styles
against real backgrounds rather than anything a unit test can assert. The first covers contrast in
both themes, accessible names, heading structure, pointer-target size, clipped text, and horizontal
overflow; the second covers the tab ring, focus indication, `prefers-reduced-motion`, 200% zoom,
and narrow viewports.

Fixed: small muted text between 2.8:1 and 4.4:1, below the 4.5:1 AA threshold for text that size; a
`.ghost-button` class used in three views but never defined, so those buttons fell back to the user
agent's default size and colour; a theme toggle that tied with the rail's hover rule on specificity
and came later, keeping its resting colour against the hover background at 1.34:1 in every theme;
two `<h1>` elements per page from the sidebar brand plus the page title, while the chat view had
none at all; and a search field whose wrapper had no focus treatment, so focusing it changed nothing
on screen.

## Security

Loopback binding, per-launch authorization, CSRF enforcement, POST-only mutations, bounded JSON
bodies, Host and Origin checks, content security policy, and `no-store` response policy are
unchanged from 0.97.0.

Credentials are never accepted through the first-run form: `set_default_provider` can persist an
inline `api_key` into the global config file, so that argument is never passed from that path. Keys
stay in the environment or the system keyring, and the panel reports only whether one was found and
which variable it expects. The memory browser is read-only; editing, merging, and deletion stay in
the CLI where the destructive commands have their confirmations.

An approval that goes unanswered times out and refuses rather than leaving a tool authorised by
default or a worker thread parked forever.

## Validation

- 1031 Python tests pass; 24 frontend tests pass.
- The committed frontend bundle is checked against its source in CI; a stale bundle fails the build.
- Both accessibility passes are clean across every view in both themes.

## Install

```bash
python -m pip install --upgrade magent==0.98.0
magent ui --open
```
