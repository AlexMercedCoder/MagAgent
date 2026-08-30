# Local UI

`magent ui` starts a local-only chat workspace for the current MagAgent user and project. It packages a lightweight conversational alternative to Mag Command Center directly with the CLI while retaining the local operations dashboard as a secondary view. It is not a hosted service.

## Workspace Files And Artifacts

The **Files** view is the project-context boundary for the browser. It lists at most 1,000 files at
a time and skips dependency/build directories, Git internals, and MagAgent state. The only internal
files exposed are browser attachments under `.magent/attachments/`. Preview and every Git action
resolve the requested path against the selected project and refuse traversal and symlink escapes.

Uploads are limited to 5 MB. A message can reference at most 20 files; text-like files no larger
than 256 KB are inlined until the combined 750 KB context budget is reached, while binary and larger
files are named as project paths for the agent's governed file tools. The transcript records the
selected references as message metadata.

The same view includes read-only status/diff/branch/worktree inspection and explicit mutation
controls. Discard and worktree removal require browser confirmation, and Git itself refuses removal
of a dirty worktree. The command console uses `shlex` plus `subprocess` argument arrays with
`shell=False`, a 60-second timeout, and a 256 KB output cap; pipes, redirects, substitutions, and
environment expansion are therefore not silently interpreted by a shell.

## Run Center And Scheduling

The **Runs** view polls one consolidated status surface for Web chat runs, durable Agent Runtime
tasks, graph history, and graph schedules. Durable tasks use their existing lifecycle rules for
pause, resume, cancel, and retry. Desktop notifications are opt-in and fire only when a previously
seen run transitions to a terminal state.

Graph schedules are atomic, project-scoped workbench records with a bounded interval. They execute
only while this local UI process is running, and starting one still calls the normal graph preview, validation,
digest, isolation, budget, and human-gate path. A schedule stores no credential and reports its last
job id or failure. It can be paused, resumed, run immediately, or deleted.

## Extensions And Browser Tools

The **Tools** view makes the harness extension surface discoverable: built-in local/web/browser
backends, plugins, skills, and MCP servers. Plugin enablement delegates to the existing signed
manifest/conformance verifier and refuses a package whose integrity check fails. The MCP inventory
reports names and enabled state only—commands, environment variables, credentials, and tokens are
not returned. Playwright browser support is shown as an optional local backend rather than an
embedded unrestricted browser.

The inventory is actionable without becoming a source-code editor. A reviewed local plugin source
can be installed or removed, and installed plugins can be enabled or disabled through the existing
integrity checks. Project Skills can be created, edited, and deleted beneath
`.magent/skills/<name>/SKILL.md`. MCP registrations can be created, edited, enabled, and removed;
the form supports stdio, Streamable HTTP, and explicitly acknowledged legacy SSE transports,
modern/legacy/automatic compatibility, working directories, timeouts, headers, environment
references, and a pre-save connection test. Authentication fields name environment variables;
stored credentials and literal secret values are never returned to the browser. MCP negotiates an
exact protocol version during initialization, so the compatibility control describes server era
rather than pretending MCP has a simple “1.0 versus 2.0” switch. Plugin package source is
deliberately not edited in the browser—replace the reviewed package instead, so its manifest and
integrity evidence remain meaningful.

The layout remains responsive for local access from another viewport, but the server is deliberately
loopback-only. Remote/mobile synchronization is not implied; use MagAgent's authenticated gateway
adapters for remote channels instead of exposing this local control plane.

## Start the UI

```bash
magent ui
magent ui --project /path/to/project --port 7830
magent ui --open
```

The server binds to `127.0.0.1` and prints the local URL. Press `Ctrl+C` to stop it.

## First Run

The browser assumed a provider was already configured. Open `magent ui` on a machine that never
ran `magent setup` and the first message failed with a credential error, having never said that no
provider was chosen.

The boot sequence now asks `/api/onboarding/readiness` before rendering the workspace. When the
machine cannot run a turn, the setup panel replaces the shell rather than presenting a composer
that is guaranteed to fail. It reports four checks:

| Step | Blocking | Meaning |
| --- | --- | --- |
| Provider | yes | Whether a default provider is selected |
| Model | no | The model that would be used; falls back to the catalog default |
| Credential / Local runtime | yes | Whether a key was found, or whether the local runtime answers |
| Workspace | no | The directory the server was started in |

The shipped default provider is `ollama`. Because a local provider needs no key,
`provider_readiness` calls it ready, so a machine that had never installed Ollama reported ready
and then failed on the first message with a connection error. Readiness therefore probes the local
runtime directly, with a short timeout so a missing runtime does not make the browser wait, and
the step is labelled `Local runtime` rather than `Credential` when it applies.

A provider and model can be chosen in the panel, which writes only the route.
**Credentials are never accepted through the form.** `set_default_provider` can persist an inline
`api_key` into the global config file, and a key typed into a browser form would land there, so
that argument is never passed from this path: keys stay in the environment or the system keyring
and the panel reports only whether one was found and which variable it searched.

## Accessibility

Two audit passes run against a live server, because the properties that matter here are computed
styles against real backgrounds rather than anything a unit test can assert.

The first pass covers contrast in both themes, accessible names, heading structure, pointer-target
size, clipped text and horizontal overflow. The second covers the tab ring, focus indication,
`prefers-reduced-motion`, 200% zoom, and narrow viewports.

Findings fixed: small muted text below the 4.5:1 AA threshold across roughly twenty labels; a
`.ghost-button` class used in three views but never defined, so those buttons fell back to the user
agent's default size and colour; a theme toggle that tied with the rail's hover rule on specificity
and came later, keeping its resting colour against the hover background at 1.34:1; two `<h1>`
elements per page from the sidebar brand plus the page title, while the chat view had none at all;
and a search field whose wrapper had no focus treatment, so focusing it changed nothing on screen.

The composer indicates focus through its wrapper rather than an outline on the textarea, which is
why the search field now does the same.

## Turns Are Runs

A turn used to execute on the HTTP request thread that started it. Close the tab mid-reply and the
work died with the socket: the assistant's answer was never recorded, the conversation kept a
question with no response, and there was no way to stop a turn that was going nowhere short of
killing the server.

A turn is now a **run**. It executes on its own thread, appends every event to an append-only log,
and finishes whether or not anyone is watching.

**Streaming reads from a cursor.** `/api/conversations/message` starts a run and streams its log
from position zero; the first line is the run snapshot, so a client that loses the socket knows
which run to come back to. `/api/runs/events?id=…&after=N` resumes the same log from a cursor and
replays everything past it. Losing the connection therefore loses the *view* of a turn, not the
turn.

**Reattachment is looked up by conversation.** A reloading tab knows which conversation it was in,
not the run id it lost, so `/api/runs?conversation_id=…` returns the newest run for a conversation.
The browser only resumes a run still in the `running` state: a finished run already wrote its reply
into the conversation, and replaying its chunks would show the answer twice.

**Cancellation is cooperative and prompt.** `/api/runs/cancel` sets a flag that the runner checks
between chunks and, in a group turn, between participants, so stopping interrupts a long reply
partway rather than waiting for the model to finish talking. Whatever the turn had already said is
kept and marked cancelled: watching text appear and then vanish makes cancelling look like it
erased the answer.

The Stop control deliberately does **not** abort its own stream. A cancelled run ends its own log,
and letting the stream close normally is what delivers the final transcript.

**Tool approvals reach the browser.** The Web UI runs its sessions with terminal permission
prompts switched off, which without an alternative means every tool above the mode's auto-approve
threshold is refused outright: the agent could not do real work, and never explained why.
`check_permission` now takes an optional `ask` callback for a front end that has a user but no
console, and a run supplies one. A tool needing a decision publishes `approval.requested` into the
run's log, the turn parks until `/api/runs/approve` answers, and `approval.resolved` follows.

Unanswered is a denial. A tab that closed is indistinguishable from one that is thinking, so an
approval that goes unanswered times out and refuses rather than leaving a tool authorised by
default or a worker thread parked forever. Cancelling a run also releases a turn waiting on an
approval, because otherwise cancel appears broken for exactly the turns most likely to need it. The
run snapshot reports any approval still outstanding, so a reattaching browser re-renders the prompt
instead of leaving the run stuck behind a question nobody can see.

Runs are held in memory for reattachment after a reload, not as history: the conversation store is
what persists. Finished runs are evicted oldest-first past a cap, and a run still in flight is never
evicted however old it is, because it still has a reader coming.

## Conversations And Bots

The Chats view supports durable traditional, bot, and group conversations:

- traditional multi-turn MagAgent conversations
- bot conversations backed by one named Open Agent Profile
- bounded group conversations with two to five profile-backed participants
- an explicit coordinator that synthesizes group responses
- streamed response text with speaker attribution
- persisted local histories that survive UI restarts
- assistant replies rendered as markdown, with a copy button on fenced code blocks
- deletion with transcript confirmation, per-conversation project-folder reassignment, and a
  conversation-scoped permission mode that can be selected before the first message or changed later

New conversation setup happens before the first message. Choose the conversation type, browse to an
existing local project folder, select a permission mode, choose up to five profile-backed
participants, and (for groups) a coordinator. Each conversation pins that project, permission mode,
and its participants; the project and permission mode can later be changed from the conversation
controls. MagAgent validates that the target exists and is a directory before using it for files,
Git, tools, or a turn. A conversation-scoped choice does not rewrite the user's global default.

Markdown rendering treats model output as untrusted, because it can quote a hostile file, a scraped page, or a tool result. Every text run is escaped before any markup is introduced, raw HTML is never parsed into elements, and only `http`, `https`, `mailto`, and same-document links become anchors; a `javascript:` or `data:` URL renders as plain text. Your own messages are shown literally, exactly as typed.

The transcript is an `aria-live` region, so streaming output is announced to assistive technology instead of appearing silently.

The UI follows the operating system's light or dark setting, and the control at the foot of the rail cycles between matching the system, forcing light, and forcing dark. The choice is stored per browser and applied before first paint.

Keyboard shortcuts are listed by pressing `/`. Cmd or Ctrl with `K` focuses the message box, with `F` searches conversations, with `Shift+N` starts a chat, and with `1` through `6` switches views. An unmodified key never fires while a text field has focus, so typing `/` in the composer inserts a slash.

When a turn fails, the transcript names the state and the recovery step, rather than printing the raw exception. A missing credential, a rate limit, an unreachable provider, a timeout, a permission denial, a budget or context overflow, an unavailable model, a cancellation, and a profile problem are each recognised; the original text is kept alongside for diagnosis.

Group participants run with isolated profile authority. A profile can narrow the globally configured tools and permission posture, but cannot widen them.

## Bots And Group Conversations

The Bots view is a roster of every profile you can talk to. Chat with one on its own, or tick two to
five and start a group; the first profile picked coordinates the round. Replies are attributed to
the profile that produced them.

## Portable Identities

A profile can be exported as a portable Open Agent Profile document and imported into another
workspace, from the Profiles view or through `/api/profiles/export` and `/api/profiles/import`.

Export never includes secret-like fields, and strips runtime accretion (state, history, inbox,
proposals): a shared profile is a role to adopt, not a snapshot of one machine's session, and
learned state is untrusted context everywhere else. Import drops the same keys on the way in and
resets the revision to 1, so a shared identity cannot carry another workspace's learned claims here
as trusted. A name that already exists is refused with an actionable message rather than silently
overwriting.

Each profile can declare its own provider and model, or leave both blank to inherit the workspace
route. A profile narrows authority; it never widens it.

Project and user profiles can be edited or deleted from a styled dialog. Their editor covers the
provider, model, permission and network ceilings, built-in tools, Skills, and MCP servers. Managed
profiles remain immutable OAP baselines; **Customize as a copy** creates a project-owned profile
that can be narrowed without altering the shipped identity. Updates carry the profile digest that
was inspected, so a second tab cannot silently overwrite a newer revision.

## Graph Kanban

Cards are a Kanban: every node starts **Pending**, moves to **In progress** while MagAgent works
it, and lands in **Complete** when it finishes, whichever way it finished.

A graph reaches the board three ways: load a file, start from a blank board and append cards with
*Add card*, or describe a goal and let the planning model draft one for review. Appending a card
rewires the document's dependency inputs and graph outputs, because MagAgent validates that every
declared output is read by something downstream; a board edited without that rewiring only fails at
save time. Nothing is written until the draft is saved under a name, and *Export* downloads the
current graph, saved or draft, as a JSON document.

The Graphs view finds `.agraph.yaml`, `.agraph.yml`, and `.agraph.json` files inside the selected project. Choose a graph—or enter a project-relative path—to validate its digest-bound execution plan before running it.

You can also author a workflow directly in the browser:

- start with a blank graph and add task cards yourself
- describe a goal and ask the configured planning model for an AI-generated draft
- assign an Open Agent Profile to each task
- select dependencies from the other cards on the board
- edit or delete cards before execution
- save and strictly validate the native `.agraph` document before Run is enabled

*Load graph* is explicit rather than hidden in the file selector. Saving keeps the board populated
from the canonical saved document. Running records the returned job id and polls that exact job;
preview and run responses are normalized from their versioned plan/run envelopes before cards are
placed into Pending, In progress, or Complete. The browser stores that job identity for the tab and
reattaches when the user visits Runs and comes back, so the board does not reset. A health strip
reports polling health, events observed, the job id, and the latest successful check; active cards
pulse and final cards retain actionable failure or skip reasons. Undeclared-tool failures point to
the card editor and name the missing capability rather than displaying only a validator code.

## Memory Editing

The Memory view supports explicit user-authored node creation plus reviewed edits and deletion.
Node ids, types, Markdown bodies, and links use the same `MemoryManager` operations as MagAgent's
runtime. Destructive removal requires browser confirmation and the roster refreshes after every
mutation.

AI-generated graphs are proposals only. They remain editable and never run automatically. Saves are confined to the selected project, and subsequent edits use the graph digest to detect conflicting disk changes.

Every plan is displayed in three fixed columns:

- **To do** for jobs waiting on the run or dependencies
- **Current work** for jobs actively handled by MagAgent
- **Done** for succeeded, failed, blocked, cancelled, and skipped jobs

Cards show their dependencies, assigned profile, execution state, changed-file count, and final success or failure summary. Graph execution runs through MagAgent's existing durable `GraphExecutor`, task, event, and status contracts. Human gate cards must be reviewed individually before the Run button will start the graph.

## Memory

MagAgent's memory is a linked graph of notes the agent wrote about you and your projects, and it
shapes every reply. The browser could only see the promotion inbox, so the memory already in force
was invisible: there was no way to ask what the agent believed, or where a belief came from.

The Memory view reports the graph's size, link count, disk usage, duplicate groups, and suppressed
notes; lists the notes themselves; and opens any one of them with its full text, the notes it links
out to, and the notes that link back to it. Backlinks are the useful direction when asking why the
agent believes something, because they show what referred to a note.

Search runs the same three modes the agent's own recall uses. `semantic` and `hybrid` need an
embedding index that may not exist, and the memory manager already falls back to keyword search, so
an unavailable mode degrades rather than failing.

Explicit memories can be created and edited on this screen, and deletion requires confirmation.
Promotion still goes through `/api/memory/promote`; bulk merging and suppression remain CLI
operations. Both the note roster and each note's body are bounded, because a memory graph grows
without limit and a browser only ever shows a window of it.

## Profiles And Settings

The Bots and Profiles views list the profiles available to the selected project and show their effective provider, model, tools, and permission policy. New profiles are validated through the same Open Agent Profile contract used by the CLI before they are written.

The Settings view only exposes schema-guided, non-secret configuration fields. API keys and other secret-bearing configuration are never returned to the browser.

## Operations

The Operations view combines the same local data used by the CLI:

- workspace status and clean-worktree report
- active tasks, plans, patch queue, reviews, and checkpoints
- project doctor output
- memory quality report for the current user
- recent command history and approximate usage stats
- built-in documentation topics and search results
- release readiness checks and release notes endpoints
- setup readiness, model health, and provider tool-smoke actions
- memory inbox candidates with a promote action
- saved patch previews and checkpoint diffs
- cockpit state for pending plans, recipes, sandbox runs, failed commands, and release checks

## API Endpoints

The dashboard exposes local JSON endpoints for tooling:

- `/api/state`
- `/api/bootstrap`
- `/api/conversations`
- `/api/folders?path=<local-directory>`
- `/api/conversations/message`
- `/api/runs?conversation_id=<conversation-id>`
- `/api/runs/events?id=<run-id>&after=<cursor>`
- `/api/runs/cancel`
- `/api/runs/approve`
- `/api/profile`
- `/api/profiles`
- `/api/profiles/contract`
- `/api/profiles/clone`
- `/api/graphs`
- `/api/graphs/preview?path=<project-relative-graph>`
- `/api/graphs/draft`
- `/api/graphs/preview-draft`
- `/api/graphs/save`
- `/api/graphs/run`
- `/api/graphs/status?job_id=<web-run-id>`
- `/api/settings`
- `/api/onboarding/readiness`
- `/api/onboarding/providers`
- `/api/onboarding/configure`
- `/api/docs/search?q=memory`
- `/api/docs/topic?slug=overview`
- `/api/release/check`
- `/api/release/notes`
- `/api/cockpit`
- `/api/memory/inbox`
- `/api/memory/overview`
- `/api/memory/search?q=<text>&mode=keyword|hybrid|semantic`
- `/api/memory/node?id=<node-id>`
- `/api/memory/nodes`
- `/api/memory/promote?id=<candidate-id>`
- `/api/extensions/mcp/test`
- `/api/patch/preview?id=<patch-id>`
- `/api/checkpoint/diff?id=<checkpoint-id>`

Mutation endpoints are POST-only and require both the per-launch authorization token and CSRF header. The server remains bound to loopback and applies Host, Origin, request-size, content-type, and browser security-header checks.

These endpoints intentionally reuse MagAgent's existing session, profile, configuration, workbench, docs, memory, and release helpers so the browser view stays aligned with CLI behavior.

## Desktop Integration APIs

Desktop clients such as Mag Command Center should prefer the machine-readable CLI surface:

- `magent system info`
- `magent ask --json --events`
- `magent config get`
- `magent config schema`
- `magent config set <path> <json-or-string>`
- `magent memory graph`
- `magent memory node <id>`
- `magent memory update-node <id> --body-file <file>`
- `magent memory inbox --json`
- `magent data sqlite-list`
- `magent data sqlite-tables <db>`
- `magent data sqlite-query <db> <sql>`
- `magent plugin list --json`
- `magent plugin enable <name>`
- `magent plugin disable <name>`

## Building The Interface

The UI is a React and TypeScript application in `webui/`, compiled by Vite into
`src/magent/webui/static/`. The compiled bundle is committed and packaged in the wheel so installed
users never need Node.

```bash
cd webui
npm ci            # exact, lockfile-pinned; `npm install` may drift the pins
npx vitest run
npm run build     # writes ../src/magent/webui/static
```

Rebuild and commit the output in the same change as any source edit, or the shipped UI silently
predates its own code. The `Web UI` workflow enforces this and also starts `magent ui` against a
temporary workspace to confirm the shell is served and the API stays token-gated.

The theme stamp lives in `webui/public/theme-init.js` rather than inline, because the response
Content-Security-Policy is `script-src 'self'` and would block an inline script.

## Relationship To `magent dashboard`

`magent dashboard` exports a static HTML workbench snapshot. `magent dashboard --serve` serves that snapshot on localhost, loopback-only and behind a per-launch token, and blocks until interrupted.

`magent ui` is the interactive local chat and operations workspace. Use it for ongoing conversations, profile-backed bots, bounded group chats, guided settings, and live operational inspection.
