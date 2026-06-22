# Tool Capability Packs

Tool packs group MagAgent's runtime tools by capability so selective loading is easier to understand and control.

Commands:

- `magent tools list`
- `magent tools explain files`
- `magent tools disable web`
- `magent tools enable web`

Built-in packs:

- `files`: file reads, writes, Word/PowerPoint artifact creation, SVG/diagram/image creation, diffs, archives, image reads, and docs search
- `shell`: shell, Python subprocess, package install, search, git, and system info
- `web`: DDGS/DuckDuckGo web search with relevance filtering, fetch, deep research, HTTP requests, browser snapshots, and browser screenshots
- `data`: JSON query helpers
- `db`: named SQLite database helpers
- `desktop`: notifications, clipboard, and open-file helpers

Disabled packs are stored in the local workbench and used by the tool executor when it advertises callable tools for a turn.

## Deep Research

The `deep_research` tool runs several web searches, deduplicates source URLs, optionally fetches source pages, and returns cited evidence packets plus a compact summary. It is intended for current-state research, comparisons, ecosystem surveys, and documentation discovery where the agent needs more than one search result.

The result includes the topic, generated queries, search metadata, source URLs, snippets, fetched excerpts when available, and fetch failures. It does not hide provenance behind a synthesized answer.

## Office Artifacts

The `create_docx` and `create_pptx` tools create Word documents and PowerPoint presentations from structured sections/slides. Agents should prefer these tools over generating temporary Python scripts for common document and deck requests.

## Visual Artifacts

The `create_svg`, `create_diagram`, and `create_image` tools create local visual artifacts without shell scripts. `create_svg` writes structured SVG vector files, `create_diagram` writes Mermaid `.mmd` or Markdown diagram files, and `create_image` renders simple PNG/JPEG compositions from shapes and text.
