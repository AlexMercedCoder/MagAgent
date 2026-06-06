# Memory

MagAgent memory is powered by MagGraph. Each user gets a separate local graph:

`~/.config/magent/users/<user>/memory/`

Useful commands:

- `magent memory stats`
- `magent memory search "query"`
- `magent memory show <node-id>`
- `magent memory traverse <node-id>`
- `magent memory inbox`
- `magent memory inbox accept <candidate-id>`
- `magent memory inbox reject <candidate-id>`
- `magent memory inbox edit <candidate-id> --body "..."`
- `magent memory review --diff`
- `magent memory approve`
- `magent memory export --out backup.json`
- `magent memory sync status`

Memory nodes are Markdown and can be reviewed in git. MagAgent recalls compact relevant memory before tasks, then writes learned facts, preferences, patterns, projects, bookmarks, and session summaries when configured.

## Memory Inbox

`magent memory inbox` is a review queue for facts that look useful but should not be written automatically. It gathers candidates from project context, open tasks, plans, saved reviews, command failures, and recent session events.

Use `magent memory inbox accept <candidate-id>` to write one candidate to MagGraph. Use `magent memory inbox reject <candidate-id>` to suppress it, or `magent memory inbox edit <candidate-id> --body "..."` to polish the text before accepting.
