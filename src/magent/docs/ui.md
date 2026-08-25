# Local UI

`magent ui` starts a local-only chat workspace for the current MagAgent user and project. It packages a lightweight conversational alternative to Mag Command Center directly with the CLI while retaining the local operations dashboard as a secondary view. It is not a hosted service.

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

**Everything on this screen reads.** Promotion still goes through `/api/memory/promote`, and
editing, merging, suppression, and deletion stay in the CLI, where the destructive commands already
have their confirmations. Both the note roster and each note's body are bounded, because a memory
graph grows without limit and a browser only ever shows a window of it.

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
- `/api/conversations/message`
- `/api/runs?conversation_id=<conversation-id>`
- `/api/runs/events?id=<run-id>&after=<cursor>`
- `/api/runs/cancel`
- `/api/profile`
- `/api/profiles`
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
- `/api/memory/promote?id=<candidate-id>`
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
