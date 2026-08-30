# Browser Automation

MagAgent has optional Playwright-backed browser helpers.

Commands:

- `magent browser snapshot <url>`
- `magent browser screenshot <url> --out page.png`

Agent tools:

- `browser_snapshot`
- `browser_screenshot`
- `webmcp_open`
- `webmcp_list_tools`
- `webmcp_call_tool`

Install Playwright support when needed:

```bash
pip install "mag-agent[browser]"
playwright install chromium
```

If Playwright is not installed, browser helpers return an explicit install hint instead of failing silently.

## alexmerced.app WebMCP

MagAgent ships an `alexmerced-webmcp` skill and three stable gateway tools rather than injecting
every page's dynamic functions into model context. `webmcp_open` accepts only paths beneath
`https://alexmerced.app`; other origins fail closed. Opening a page captures its live WebMCP
registry, `webmcp_list_tools` returns exact schemas, and `webmcp_call_tool` executes a named entry.

WebMCP is page-scoped. Navigating from `/quarry` to `/quire` replaces the available registry.
Execution uses a dedicated persistent Chromium profile at
`~/.local/share/magent/webmcp/alexmerced-app`, or `MAGENT_WEBMCP_PROFILE` when explicitly set. The
browser is visible by default; set `MAGENT_WEBMCP_HEADLESS=1` for unattended compatibility-mode
runs. All calls still pass through MagAgent's profile/network ceiling. Read-shaped operations are
automatic under the normal policy, while writes and other unknown operations require confirmation.

The static catalog at `https://alexmerced.app/.well-known/webmcp.json` helps the agent select a
page before navigation. The live registry remains authoritative for invocation.
