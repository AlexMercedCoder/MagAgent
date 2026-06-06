# Code Intelligence

MagAgent includes local code-intelligence commands under `magent lsp`.

## Commands

- `magent lsp status`: show known language-server commands and whether they are installed.
- `magent lsp symbols`: list Python classes and functions using a local AST fallback.
- `magent lsp symbols --query name`: filter symbols.
- `magent lsp diagnostics`: report Python syntax diagnostics.
- `magent lsp definition <symbol>`: find matching symbol definitions.
- `magent lsp references <symbol>`: search local source references.

## Behavior

The implementation is LSP-aware and local-first:

- it detects common language-server executables such as `pylsp`, `pyright-langserver`, `typescript-language-server`, `rust-analyzer`, and `gopls`
- it provides no-server fallbacks for symbols, definitions, references, and diagnostics
- it feeds diagnostics into review and project diagnostics flows

The fallback path is intentionally dependency-light and bounded by MagAgent's shared project scanner, so large repositories do not require a full language-server startup just to get basic intelligence.

## Review Integration

`magent review --json` and `magent diagnostics` include local diagnostics. This gives test-repair and review workflows a shared source of syntax failures before the agent spends tokens on deeper analysis.
