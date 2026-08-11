# Code Intelligence

MagAgent includes a real local Language Server Protocol client under `magent lsp`.

## Commands

- `magent lsp status`: show server commands, availability, languages, and extensions.
- `magent lsp symbols [--query name]`: request workspace symbols.
- `magent lsp diagnostics`: collect bounded workspace diagnostics.
- `magent lsp definition <symbol>`: locate a symbol and request definitions.
- `magent lsp references <symbol>`: request references including declarations.
- `magent lsp hover <path> --line N --column N`: request hover information.
- `magent lsp rename <path> <new-name> --line N --column N`: preview a workspace edit.

Line and column values are one-based at the CLI boundary. Rename returns an edit for review; it does not apply the edit automatically.

## Servers

MagAgent starts installed servers as local subprocesses:

| Language | Server commands |
|---|---|
| Python | `pyright-langserver --stdio`, then `pylsp` |
| TypeScript/JavaScript | `typescript-language-server --stdio` |
| Rust | `rust-analyzer` |
| Go | `gopls serve` |

Install Python LSP support with `python -m pip install "mag-agent[lsp]"`. TypeScript users should install compatible `typescript` and `typescript-language-server` npm packages. Rust and Go servers are discovered from `PATH`.

The client negotiates capabilities, opens/changes/closes documents, answers common server-to-client requests, cancels timed-out requests, supports restart, and performs clean shutdown. TypeScript server discovery locates a sibling global TypeScript installation when necessary.

## Fallbacks And Bounds

When a compatible server is absent or fails, Python symbols/definitions/diagnostics use a bounded AST fallback and references use bounded text search. Every response includes `source: lsp`, `source: ast-fallback`, or `source: text-fallback` plus a fallback reason.

Diagnostics reuse one server process per language and collect notifications in one workspace-wide four-second window. The scanner opens at most 100 supported files, preventing a missing publish event from adding a per-file timeout.

## Review Integration

`magent review --json`, release checks, project diagnostics, and repair workflows consume this shared diagnostic surface. Real Python and TypeScript process round trips run in CI; deterministic JSON-RPC lifecycle tests use a fixture server.
