# Memory

MagAgent memory is powered by MagGraph. Each user gets a separate local graph:

`~/.config/magent/users/<user>/memory/`

Useful commands:

- `magent memory stats`
- `magent memory search "query"`
- `magent memory show <node-id>`
- `magent memory traverse <node-id>`
- `magent memory review --diff`
- `magent memory approve`
- `magent memory export --out backup.json`
- `magent memory sync status`

Memory nodes are Markdown and can be reviewed in git. MagAgent recalls compact relevant memory before tasks, then writes learned facts, preferences, patterns, projects, bookmarks, and session summaries when configured.

