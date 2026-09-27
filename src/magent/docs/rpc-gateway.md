# Remote JSON-RPC gateway (experimental)

`magent serve --rpc` lets a desktop client on another machine, such as Mag Command Center's
remote runtime, drive this MagAgent: run commands, stream a run's output, answer its approvals and
cancel it. It is **experimental** in 1.4: the protocol (`magent.rpc.v1`) may still change in a
minor release.

```bash
magent serve --rpc                               # 127.0.0.1:7850, prints a one-time token
magent serve --rpc --root ~/code/app --root ~/code/lib
printf '%s' "$TOKEN" | magent serve --rpc --token-stdin
magent serve --rpc --token-file ~/.config/magent/rpc-token   # keep the file mode 0600
```

On start it prints one JSON object: `url`, `host`, `port`, `roots`, `audit_log`, and `token`
when it generated one. The token is shown once and never written to disk. Press Ctrl+C to stop;
stopping cancels every running stream.

## Security model

- Every request except `GET /healthz` needs `Authorization: Bearer <token>` (at least 16
  characters, compared in constant time). A wrong token is HTTP 401.
- It binds to loopback. Any other `--host` is refused unless you pass `--allow-remote`, because
  the gateway speaks plain HTTP. For remote use, keep it on loopback and put a TLS reverse proxy
  in front (below).
- Requests are bounded: 2 MiB bodies, 256 arguments of at most 64 KiB, 2 MiB of stdin, 8 MiB of
  captured output, 4 concurrent streams, 240 requests per minute.
- Commands that start servers or need a terminal are refused: `serve`, `ui`, `setup`,
  `configure`, `dashboard`, `daemon start`, `gateway start`, `memory ui`, `mcp serve`, and the
  root `--install-completion` / `--show-completion` flags. The command is found by parsing the
  arguments with MagAgent's own CLI definition, so root options such as `--provider x` in
  front of it do not hide it.
- Requests that carry browser headers (`Origin` or `Sec-Fetch-Site`) are refused with HTTP 403,
  so a web page cannot use the gateway even through DNS rebinding. Desktop clients never send
  them.
- Idle or half-sent connections are closed after 60 seconds. The 32 most recent finished
  streams are kept for `stream.events`; older ones are forgotten. Failed authentication is
  logged at most 60 times a minute.
- `--project` values must resolve inside a `--root`; commands run with the first root as their
  working directory.
- Every call is appended to `~/.config/magent/logs/rpc-gateway.jsonl` (created mode 0600) with the peer address,
  method and arguments, with values after `--api-key`, `--token`, `--password` and `--secret`
  redacted.
- The token grants the same authority as your MagAgent user. The command denials and the
  `--root` check are guard rails, not a sandbox: a token holder can run any other command,
  including ones that read files outside the roots (`ask --prompt-file`) or change settings.
  Approvals are still enforced by the run itself: a streamed run started with
  `--approval-stdio` waits for an AAIS decision written through `write_magent_stream`.

## Protocol `magent.rpc.v1`

`POST /rpc` takes one JSON-RPC 2.0 request object (no batches) and returns `result` or
`error: {code, message, data?}`. JSON-RPC errors come back with HTTP 200 (except 401), which is
what Mag Command Center's transport expects.

| Method | Params | Result |
| --- | --- | --- |
| `runtime_info` | `{}` | `{schema: "magent.rpc-gateway.v1", protocol, transport, version, capabilities, methods, roots, limits}` |
| `run_magent` | `{args: string[]}` | `{ok, command, stdout, stderr, status}`, the desktop app's `CommandResult` |
| `run_magent_input` | `{args, input: string}` | `CommandResult`, with `input` written to stdin |
| `stream.start` | `{args, id?}` | `{id, command}`; the run starts in the background with stdin open |
| `stream.events` | `{id, after?: seq, wait_ms?: <=25000}` | `{id, events: [{seq, id, stream: "stdout"\|"stderr"\|"status", line}], next, gap, done, result: CommandResult\|null}` |
| `stream.list` | `{}` | `{streams: [{id, command, started_at, done, status}]}` |
| `write_magent_stream` | `{id, line}` | `true`; `line` must be a valid AAIS `approval.decided` envelope |
| `cancel_magent_stream` | `{id}` | `true` if a running stream was stopped (its whole process group), else `false` |

Stream events use the desktop app's `magent-stream` event shape (`id`, `stream`, `line`) plus a
`seq`. Long-poll with `after = next` until `done`. `gap: true` means older lines were dropped
from the 5,000-line buffer.

`GET /rpc/streams/<id>/events?after=<seq>` streams the same events as Server-Sent Events:
`event: stream` records (the `id:` field is `seq`), keep-alive comments, and a final
`event: done` whose data is the `CommandResult`. It needs the same bearer header.

Error codes: `-32700` parse error, `-32600` invalid request, `-32601` unknown method (with the
supported list in `data.methods`), `-32602` invalid params, `-32603` internal, `-32001`
unauthorized, `-32003` forbidden (denied command or `--project` outside the roots), `-32004`
unknown or finished stream, `-32029` rate limited, `-32030` too many concurrent streams.

A typical approval-gated run:

1. `stream.start {args: ["ask", "fix the tests", "--json", "--approval-stdio"]}`
2. `stream.events` until a `stdout` line is an `approval.requested` envelope
3. show it to the user, then `write_magent_stream {id, line: <approval.decided envelope>}`
4. keep reading `stream.events` until `done`; `cancel_magent_stream` stops it early

Recorded request/response pairs for all of this live in the repository at
`tests/fixtures/rpc_gateway/lifecycle.json` so clients can test against them.

## TLS reverse proxy

Keep the gateway on `127.0.0.1` and terminate TLS in front of it. Caddy:

```text
agent.example.com {
    reverse_proxy /rpc* 127.0.0.1:7850 {
        flush_interval -1
    }
}
```

nginx:

```nginx
location /rpc {
    proxy_pass http://127.0.0.1:7850;
    proxy_http_version 1.1;
    proxy_buffering off;          # needed for the SSE event stream
    proxy_read_timeout 1h;
    proxy_set_header Authorization $http_authorization;
}
```

Restrict who can reach the proxy (VPN, firewall or client certificates); the bearer token is
the only application-level check.
