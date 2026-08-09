# MCP Compatibility

MagAgent connects external Model Context Protocol servers to an agent session and
namespaces their tools as `mcp__<server>__<tool>`. Install the optional runtime with:

```bash
python -m pip install "mag-agent[mcp]"
```

## Runtime Support

The SDK v2 bridge supports classic initialization-based MCP through `2025-11-25` and
modern stateless MCP `2026-07-28`. Each server can require one era or use automatic
dual-era negotiation. Existing stdio configurations remain compatible.

Supported transports are:

- `stdio`: recommended for local servers and supported in both protocol eras.
- `streamable-http`: recommended for remote servers.
- `legacy-sse`: deprecated compatibility path requiring an explicit opt-in.

The current MagAgent surface discovers and calls tools, browses prompts and resources,
renders prompts explicitly, reads resources on demand, completes prompt/template
arguments, consumes change notifications, and handles elicitation through explicit
host input. Text, images, audio, embedded resources, resource links, structured
content, annotations, output schemas, and extension metadata are preserved. Tasks,
interactive MCP Apps rendering, and remote skills remain experimental extension work.

MCP runs in a private child process because SDK connection contexts are sensitive to
event-loop ownership in interactive applications. The profile is sent over stdin,
not process arguments, and public status never includes environment or header values.

## Configure Stdio

```toml
[mcp.servers.filesystem]
transport = "stdio"
protocol_mode = "auto"
command = "npx"
args = ["-y", "@modelcontextprotocol/server-filesystem", "/allowed/path"]
timeout = 30
```

Configurations without `transport` or `protocol_mode` are interpreted as `stdio`
plus `auto`. `protocol_mode` accepts:

- `auto`: probe modern discovery and fall back to the classic handshake when needed.
- `legacy`: require the initialization-based protocol path.
- `modern`: require MCP `2026-07-28`.

## Configure Streamable HTTP

```toml
[mcp.servers.remote]
transport = "streamable-http"
protocol_mode = "modern"
url = "https://example.com/mcp"
headers = { Authorization = "Bearer ${MCP_TOKEN}" }
```

`${NAME}` references in MCP environment and header values are resolved from the
bridge environment at connection time. The resolved values are never returned by
public diagnostics. Keep credentials in environment variables rather than committing
them to project configuration.

Legacy HTTP+SSE requires `transport = "legacy-sse"` and
`allow_deprecated_transport = true`. It should only be used for a server that cannot
migrate to stdio or Streamable HTTP.

## Inspect And Test

```bash
magent mcp list
magent mcp test filesystem
magent mcp catalog filesystem
magent mcp resource filesystem file:///allowed/path/README.md
magent mcp prompt filesystem review --arguments '{"path":"app.py"}'
magent mcp complete filesystem review --name path --value app
magent diagnostics --deep
```

These commands report the configured transport and mode, selected era and revision,
discovered tools, prompt/resource catalogs, cache freshness, and a redacted failure
reason. An invalid or unavailable server does not prevent other configured servers
from being inspected.

Catalog loading is lazy so normal agent startup does not fetch unused prompt or
resource metadata. Deterministic catalogs honor the server's `ttlMs` and `cacheScope`.
`--refresh` bypasses the SDK cache. Tool calls conservatively mark loaded catalogs
stale because they may mutate server state; normalized list-changed events use the
same invalidation API. Modern connections open `subscriptions/listen` and report the
honored filter in diagnostics. Classic server notifications pass through the same
normalizer. A lost or rejected stream leaves TTL caching usable and records an
actionable subscription status rather than breaking the MCP connection.

When a tool, prompt, or resource returns `input_required`, the SDK drives the MRTR
exchange through MagAgent's host-input callback. Interactive CLI sessions show
elicitation fields and require consent. Project roots require a separate confirmation.
Sampling is not delegated invisibly: the server must surface the request through the
main conversation. Headless hosts reject input requests until they provide the same
callback contract, so credentials and consent cannot be inferred by the model.

Resource reads are explicit and their text/blob fields are bounded to 200,000
characters before crossing into the main process. Truncation is shown to the user.
MCP prompts and server instructions are untrusted content: displaying or selecting
one never grants tools or bypasses MagAgent permissions.

## Support Matrix

| Surface | Legacy through 2025-11-25 | Modern 2026-07-28 | Notes |
| --- | --- | --- | --- |
| Stdio | Supported | Supported | Auto or strict era |
| Streamable HTTP | Supported by SDK bridge | Supported | Remote conformance pending |
| Legacy SSE | Explicit opt-in | Not recommended | Deprecated compatibility only |
| Tools list/call | Supported | Supported | Structured content preserved |
| Prompts list/get | Supported | Supported | Explicit untrusted rendering |
| Resources list/read | Supported | Supported | Lazy, bounded, cache-aware |
| Resource templates | Supported | Supported | Catalog inspection |
| Completion | Supported | Supported | Prompt and resource-template arguments |
| Cache hints | Supported | Supported | TTL, scope, refresh, freshness |
| Live subscriptions | Notifications adapted | `subscriptions/listen` supported | Honored filter and failures visible |
| MRTR / elicitation | Legacy callbacks supported | `input_required` supported | Explicit host consent; no hidden sampling |
| MCP Apps | Text/metadata fallback | Text/metadata fallback | Sandboxed desktop renderer remains pending |
| Tasks extension | Legacy experimental API not activated | Experimental extension not activated | Python SDK client support is pending upstream |
| Skills over MCP | Experimental roadmap | Experimental roadmap | Local `SKILL.md` already supported |

## Skills

MagAgent supports local and project `SKILL.md` files, relevance matching, context
budgets, lockfiles, and imported Codex-style skill packs. It does not yet fetch skills
from MCP servers.

Skills over MCP is being standardized as a resources-based extension. Until its SEP
and schemas are final, remote discovery remains planned as experimental and opt-in.
Remote skills will enter the existing registry with provenance, hashes, expiry, trust
state, and normal permission controls; instructions never grant tool permission.

See the repository roadmap for OAuth host UX, experimental Tasks and Skills adapters,
MCP Apps rendering, and conformance delivery gates.
