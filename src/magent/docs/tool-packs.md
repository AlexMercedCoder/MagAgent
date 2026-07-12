# Tool Capability Packs

Tool packs group MagAgent's runtime tools by capability so selective loading is easier to understand and control.

Commands:

- `magent tools list`
- `magent tools explain files`
- `magent tools gateway`
- `magent tools backend local`
- `magent tools disable web`
- `magent tools enable web`

Built-in packs:

- `files`: file reads, writes, Word/PowerPoint artifact creation, SVG/diagram/local image creation, AI image generation, diffs, archives, image reads, and docs search
- `shell`: shell, Python subprocess, package install, search, git, and system info
- `web`: DDGS/DuckDuckGo web search with relevance filtering, fetch, deep research, HTTP requests, browser snapshots, and browser screenshots
- `data`: JSON query helpers
- `db`: named SQLite database helpers
- `desktop`: notifications, clipboard, and open-file helpers

Disabled packs are stored in the local workbench and used by the tool executor when it advertises callable tools for a turn.

## Tool Backends And Gateway Readiness

`magent tools gateway` shows which tool backends are currently available:

- local built-ins
- local web search/fetch/research
- browser automation
- configured image generation model role
- subscription-backed provider surfaces such as Nous Portal and OpenCode Go
- MCP servers

`magent tools backend <name>` explains one backend, its credential expectations, and whether it is subscription-backed. This is metadata today; it gives the CLI and Mag Command Center a stable surface for routing future tool gateway behavior without requiring users to edit config files directly.

## Deep Research

The `deep_research` tool runs several web searches, deduplicates source URLs, optionally fetches source pages, and returns cited evidence packets plus a compact summary. It is intended for current-state research, comparisons, ecosystem surveys, and documentation discovery where the agent needs more than one search result.

The result includes the topic, generated queries, search metadata, source URLs, snippets, fetched excerpts when available, and fetch failures. It does not hide provenance behind a synthesized answer.

## Tool Activity Metadata

Built-in tools accept an optional `activity` object with `phase`, `intent`, and `expected` fields. The agent uses this for concise status lines and JSONL diagnostics, then removes it before tool validation and execution.

This is deliberately user-facing metadata, not hidden reasoning. Good examples are `inspect: Find the existing entry point before editing` or `verify: Confirm the generated file exists`.

Session logs also emit stable `activity_event` records for tool completion so
desktop clients can render tool progress in the chat flow without parsing
human-formatted terminal text.

## Office Artifacts

The `create_docx` and `create_pptx` tools create Word documents and PowerPoint presentations from structured sections/slides. Agents should prefer these tools over generating temporary Python scripts for common document and deck requests.

## Visual Artifacts

The `create_svg`, `create_diagram`, and `create_image` tools create local visual artifacts without shell scripts. `create_svg` writes structured SVG vector files, `create_diagram` writes Mermaid `.mmd` or Markdown diagram files, and `create_image` renders simple PNG/JPEG compositions from shapes and text.

The `generate_image` tool uses the configured `image_maker` model role to create AI-generated PNGs. Configure it with `magent model image-wizard` or `magent model set-role image_maker openai/gpt-image-1`.
