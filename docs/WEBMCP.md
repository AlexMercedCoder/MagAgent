# WebMCP browser tools

MagAgent can discover and invoke page-scoped WebMCP tools through an isolated Playwright profile.
Install the optional runtime once:

```bash
python -m pip install "mag-agent[browser]"
playwright install chromium
magent webmcp status
```

`https://alexmerced.app` is enabled by default. Manage additional exact HTTPS origins explicitly:

```bash
magent webmcp origins
magent webmcp origin-add https://tools.example.com
magent webmcp origin-remove https://tools.example.com
```

Normal chat, bot, subagent, and graph sessions use `webmcp_open`, `webmcp_list_tools`,
`webmcp_call_tool`, `webmcp_status`, and `webmcp_close`. They remain subject to the active OAP
profile, permission mode, runtime approval, and audit policy. For diagnostics, the direct CLI can
inspect a page and make an explicitly approved one-off call:

```bash
magent webmcp open https://alexmerced.app/quarry
magent webmcp call quarry_list_tables --url https://alexmerced.app/quarry \
  --registry-revision sha256:... --arguments '{}' --yes
```

The runtime verifies the final URL after redirects, isolates persistent browser storage per origin,
caps returned data, and hashes the live URL plus registry metadata. Calls may bind that revision;
stale calls fail and require rediscovery. Page text, schemas, annotations, and results are untrusted
content and cannot grant authority. Credentials and browser storage are never returned to the model.
