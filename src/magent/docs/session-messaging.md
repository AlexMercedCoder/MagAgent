# Session-to-Session Messaging

MagAgent sessions can coordinate through an authenticated, local-only message channel.
The feature is enabled by default and does not require a daemon or network account.

## Quick Start

Start two interactive MagAgent sessions under the same MagAgent user, then inspect the
roster:

```bash
magent session peers
magent session send <session-id-or-name> "Please review the current patch"
magent session receipts <sender-session-id>
magent session doctor
```

The agent can use the same surface through `list_sessions` and
`send_session_message`. Durable session IDs are authoritative. A display name works
only when it resolves to exactly one live session.

## Receiving Policy

Choose the default for newly started sessions:

```bash
magent session policy accept
magent session policy hold
magent session policy refuse
```

`accept` queues messages for the next safe agent turn boundary. `hold` requires review
with `magent session inbox <session-id> --held` followed by `magent session accept` or
`magent session refuse`. `refuse` rejects delivery. Non-interactive sessions downgrade
`accept` to `hold` unless `--headless-accept` was explicitly configured.

## Delivery And Recovery

Messages receive `delivered`, `held`, `refused`, `expired`, or `unreachable` receipts.
Unreachable attempts stay in the sender's durable local outbox. A live sender can run:

```bash
magent session retry <sender-session-id>
```

Inbox, held queue, outbox, and receipt records live under
`~/.config/magent/messaging/`. Runtime Unix sockets use an owner-only short directory
under `/tmp` on macOS/Linux; Windows uses an authenticated loopback endpoint. Queue
files and roster capabilities are owner-only.

## Security Model

Only bounded plain text and explicit provenance metadata cross the channel. MagAgent
does not transfer conversation history, file contents, hidden context, credentials,
permission state, or MCP responses.

Every peer message is injected under an `UNTRUSTED PEER MESSAGE` delimiter. It is not
a user message and cannot:

- approve a command or permission request;
- answer MCP elicitation;
- change configuration or system instructions;
- widen tool access;
- execute slash commands;
- override the current user's request.

The receiver keeps its own provider, sandbox, tools, and approval policy. Per-session
capabilities rotate on registration, Unix peers are checked against the current OS user
where supported, duplicate nonces are suppressed, queues are bounded, messages expire,
and per-peer rate and hop limits prevent accidental loops.

## Diagnostics

```bash
magent session peers --include-stale
magent session inbox <session-id>
magent session inbox <session-id> --held
magent session receipts <sender-session-id> --json
magent session events
```

Accepted messages emit a redacted `session_message_received` activity event. Logs keep
IDs and provenance, not hidden reasoning or credentials.

Cross-machine messaging is intentionally unsupported. It requires a separate,
end-to-end encrypted, device-bound relay design.

## Interactive Commands

Inside `magent`, use `/session` to show the durable identity printed by the startup
banner, `/peers` to discover other sessions, and `/send <peer> <text>` to coordinate
without leaving chat. `/inbox held`, `/accept <message-id>`, `/refuse <message-id>`,
and `/receipts` provide the same review and delivery workflow in the active session.
