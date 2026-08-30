# Installation Shapes

MagAgent 0.60 separates the general-purpose agent from integrations that carry large or platform-specific dependency trees.

## Core

```bash
python -m pip install mag-agent
```

Core includes the CLI/TUI, providers, MagGraph memory, files and shell tools, HTTP, web search, configuration, Git, workbench, and data tools.

## Capability Extras

```bash
python -m pip install "mag-agent[docs]"     # Word, PowerPoint, spreadsheets, PDF
python -m pip install "mag-agent[media]"    # local raster image work
python -m pip install "mag-agent[desktop]"  # clipboard, metrics, notifications, images
python -m pip install "mag-agent[browser]"  # Playwright and article extraction
python -m pip install "mag-agent[webmcp]"   # minimal Playwright WebMCP bridge
python -m pip install "mag-agent[gateway]"  # Slack, Discord, Telegram
python -m pip install "mag-agent[mcp]"      # MCP SDK and Streamable HTTP transport
python -m pip install "mag-agent[lsp]"      # Python language server
python -m pip install "mag-agent[full]"     # all Python capabilities
```

After installing browser or WebMCP support, run `playwright install chromium` for the browser binary. TypeScript, Rust, and Go language servers are external executables discovered from `PATH`.

Use `magent tools doctor` for a machine-readable readiness report and exact install commands. Optional tools return the same actionable command when their dependency is absent rather than failing with an import traceback.

CI installs the full shape for integration coverage, then installs the built wheel in a fresh core-only virtual environment and runs `magent --version` plus `magent tools doctor`.
