# Tool Capability Packs

Tool packs group MagAgent's runtime tools by capability so selective loading is easier to understand and control.

Commands:

- `magent tools list`
- `magent tools explain files`
- `magent tools disable web`
- `magent tools enable web`

Built-in packs:

- `files`: file reads, writes, diffs, archives, image reads, and docs search
- `shell`: shell, Python subprocess, package install, search, git, and system info
- `web`: web search, fetch, and HTTP requests
- `data`: JSON query helpers
- `db`: named SQLite database helpers
- `desktop`: notifications, clipboard, and open-file helpers

Disabled packs are stored in the local workbench and used by the tool executor when it advertises callable tools for a turn.
