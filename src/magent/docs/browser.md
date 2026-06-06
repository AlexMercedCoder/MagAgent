# Browser Automation

MagAgent has optional Playwright-backed browser helpers.

Commands:

- `magent browser snapshot <url>`
- `magent browser screenshot <url> --out page.png`

Agent tools:

- `browser_snapshot`
- `browser_screenshot`

Install Playwright support when needed:

```bash
pip install "mag-agent[browser]"
playwright install
```

If Playwright is not installed, browser helpers return an explicit install hint instead of failing silently.
