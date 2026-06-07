# Memory

MagAgent memory is powered by MagGraph. Each user gets a separate local graph:

`~/.config/magent/users/<user>/memory/`

MagAgent requires `maggraph>=0.2.0` and uses MagGraph's native memory APIs:

- Structured graph search over IDs, types, tags/frontmatter, body text, links, suppression state, and recency.
- Recall bundles with compact Markdown, body excerpts, links, backlinks, metadata, and relevance reasons.
- Memory schema helpers for preferences, project facts, decisions, tasks, session summaries, bookmarks, and tool failures.
- Durable merge, suppress, and unsuppress operations owned by MagGraph.
- Incremental `update_file` refreshes and `changed_since` change-feed entries after writes and inbox promotion.

Useful commands:

- `magent memory stats`
- `magent memory search "query"`
- `magent memory show <node-id>`
- `magent memory node <node-id>`
- `magent memory update-node <node-id> --preview --body-file node.md`
- `magent memory update-node <node-id> --body-file node.md`
- `magent memory traverse <node-id>`
- `magent memory inbox`
- `magent memory inbox accept <candidate-id>`
- `magent memory inbox reject <candidate-id>`
- `magent memory inbox edit <candidate-id> --body "..."`
- `magent memory review --diff`
- `magent memory approve`
- `magent memory export --out backup.json`
- `magent memory quality`
- `magent memory merge <target-id> <source-id> --preview`
- `magent memory merge <target-id> <source-id>`
- `magent memory suppress <node-id> --reason "stale"`
- `magent memory unsuppress <node-id>`
- `magent memory sync status`

Memory nodes are Markdown and can be reviewed in git. MagAgent recalls compact relevant memory before tasks, then writes learned facts, preferences, patterns, projects, bookmarks, tool failures, and session summaries when configured.

## Recall Provenance

Memory recall now includes a "Why These Memories" section. It shows which search fields matched, the graph score, and backlinks for each recalled anchor. Backlinks help explain why a memory is connected to the current task and what other memories depend on it.

For token efficiency, MagAgent asks MagGraph for recall bundles instead of expanding large traversals by default. Each bundle includes a compact summary, a bounded body excerpt, outgoing links, backlinks, metadata, and a relevance reason.

## Memory Inbox

`magent memory inbox` is a review queue for facts that look useful but should not be written automatically. It gathers candidates from project context, open tasks, plans, saved reviews, command failures, and recent session events.

Use `magent memory inbox accept <candidate-id>` to write one candidate to MagGraph. Use `magent memory inbox reject <candidate-id>` to suppress it, or `magent memory inbox edit <candidate-id> --body "..."` to polish the text before accepting.

Accepted inbox items are written through MagGraph's memory-node helpers. MagAgent refreshes the changed node with `update_file` and returns `changed_since` entries so UI and CLI callers can update cheaply.

Desktop editors should use `magent memory update-node --preview` before applying edits. Preview mode reports old/new body hashes, character counts, and links without writing to the graph.
