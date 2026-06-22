# Terminal UI

MagAgent's interactive terminal UI is built with Rich and is designed to stay readable during long coding sessions.

## Session Banner

Interactive sessions start with a compact `MagAgent` banner. The banner adapts to terminal width and shows the active user, provider, model when available, permission mode, optional git branch, and compact current path.

## Response Rendering

Non-streamed responses render as Markdown inside a light `MagAgent` panel so headings, lists, code fences, and links are easier to scan.

Streaming responses print tokens immediately for responsiveness. By default, MagAgent no longer re-renders the same answer after streaming completes, which keeps interactive sessions quieter. The renderer still supports an opt-in final Markdown render for debugging or alternate frontends.

## Status Lines

TUI helpers expose compact status rendering for operational events:

- `print_status(..., level="success")`
- `print_status(..., level="warning")`
- `print_status(..., level="error")`
- `print_error(...)`

Use these for checkpoint saves, memory writes, command outcomes, and other short-lived agent events.

## Session Controls

Interactive sessions include daily-driver slash commands:

- `/retry` removes the last exchange from context and reruns the previous user prompt.
- `/undo` removes the last exchange from context without rerunning it.
- `/usage` summarizes token usage, tool calls, estimated cost, and slowest steps for the current session.
- `/insights` summarizes recent session logs.
- `/mode <silent|balanced|paranoid|yolo>` changes the live permission mode for the current session.
- `/goal <task>` runs a strengthened goal-loop prompt with implementation, verification, review, and artifact-existence stop conditions.

## Theme

The built-in `TuiTheme` centralizes styles for accent, border, success, warning, danger, muted, user, provider, mode, and path text. Keeping styles named makes future light/dark and compact modes easier to add without touching every render call.

## Testing

The TUI has capture-based tests for:

- compact session context
- adaptive banner rendering
- Markdown response panels
- status and error lines
- streaming without duplicated output
- optional final Markdown rendering
