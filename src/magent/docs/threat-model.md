# Threat Model

MagAgent is a local agent that converts model output into file, process, network, browser,
plugin, gateway, and durable-state actions. The model and all content it reads are untrusted.
The user, project files, provider responses, websites, plugins, MCP servers, gateway messages,
and imported archives may be malicious or mistaken.

## Protected Assets

- project and user files outside the active workspace
- credentials, provider keys, gateway tokens, and environment variables
- command execution authority and saved approvals
- local services, cloud metadata endpoints, and private network resources
- workbench, daemon, graph, session, permission, and memory state
- the identity and authorization boundary of remote gateway users

## Trust Boundaries

Model-proposed actions cross a policy boundary before execution. Shell commands are parsed
structurally; file and archive paths are contained; outbound URLs are resolved and checked;
remote gateway users are authorized; local HTTP mutations require a launch token and POST;
plugins declare permissions; durable stores use locks and atomic replacement. A successful
provider response never grants additional authority.

## Primary Threats And Mitigations

| Threat | Mitigation |
| --- | --- |
| Prompt-injected shell or interpreter execution | Structural command classification, effective policy shared by execution surfaces, scoped approval, optional OS sandbox |
| Substitution, redirect, upload, or mutating-flag bypass | Segment-aware parsing and regression probes that cannot be lowered by saved trust |
| Workspace escape or archive traversal | Resolved-path containment, unsafe-component rejection, bounded extraction |
| SSRF, redirect rebinding, metadata access, or oversized response | Shared URL policy, DNS/IP checks on every redirect, method tiers, streamed size caps |
| Credential disclosure in errors or reports | Central secret scrubbing, sanitized evidence, no credential values in provider reports |
| Unauthorized gateway action | Deny-by-default allowlists, mention rules, rate limits, per-channel serialization, session-scoped approvals |
| Local dashboard cross-origin mutation | Random launch token, host/origin validation, POST-only mutations, bounded listener exposure |
| Torn or concurrent state write | Cross-process locking, atomic replacement, corruption preservation, durable claims |
| Malicious plugin or MCP contribution | Manifest validation, path containment, permission declaration, explicit enablement and trust metadata |

## 1.4.0 Surfaces: SEC-1 Self-Review

This section covers what 1.4.0 adds. It is a **self-review by the people who wrote the code**
(2026-09-27), not an independent audit or penetration test. It found 30 issues, a few of them
defense-in-depth hardening rather than exploitable bugs, all fixed before release; each fix has
a regression test that failed before the fix
(`tests/unit/test_sec1_regressions.py`, and `editors/vscode/test/client.test.ts` for the
extension). STRIDE letters: **S**poofing, **T**ampering, **R**epudiation, **I**nformation
disclosure, **D**enial of service, **E**levation of privilege.

### RPC gateway (`magent serve --rpc`)

Assets: command execution as the user, run output, approval decisions, the bearer token.

| STRIDE | Threat | Mitigation |
| --- | --- | --- |
| S | Caller without the token | Bearer token (16+ chars, `hmac.compare_digest`), 401 otherwise (`rpc_gateway.py`, `Gateway.authorized`) |
| S | Web page via DNS rebinding or CSRF, including the SSE URL | Token in a header (browsers cannot add it cross-site; SSE takes no query token); requests with `Origin`/`Sec-Fetch-Site` get 403 (`_from_browser`) |
| T | Remote caller re-exposes the machine (`serve`, `ui`, `daemon start`, `--install-completion`) | Command resolved with the real CLI parser (`resolve_command_path`), then denied; root denied flags |
| T | `--project` outside the allowed roots | Resolved-path check (`_inside_roots`) |
| R | Who ran what | JSONL audit log, created 0600, secret flags redacted (`audit`, `redact_args`) |
| I | Token or keys in logs | Values after `--api-key`/`--token`/`--password`/`--secret` redacted; stdin input never logged |
| D | Slow or idle clients, floods, memory growth | 60 s socket timeout; body/arg/output/line limits; 4 concurrent streams; 32 finished streams kept; 240 req/min; failed-auth logging capped at 60/min |
| E | Plain HTTP on a network | Loopback only unless `--allow-remote`; TLS proxy documented |

Residual risk: the token is the user's full authority; the denials and roots are guard rails,
and a token holder can run other commands (for example `ask --prompt-file` on any readable
file). With `--allow-remote` and no proxy the token crosses the network in clear text. Stream
ids are guessable only when a client chooses them, and any token holder may read any stream.
Covering tests: `test_rpc_gateway.py`, `test_sec1_regressions.py` (RPC section).

### Approval push (doorbells and `/api/approvals/stream`)

Assets: timely delivery of approval decisions; the approval store stays the source of truth.

| STRIDE | Threat | Mitigation |
| --- | --- | --- |
| S | Another user rings a doorbell or fakes a decision | A ring carries no data, only "re-read the store"; decisions are read from the locked store (`approval_bus.py`) |
| T | Another user pre-creates `/tmp/magent-doorbells-<uid>` or a symlink and swaps sockets | Directory must be a real directory we own with no group/other bits, else loopback UDP (`_private_dir`) |
| I | Stream leaks pending actions | `/api/approvals/stream` sits behind the Web UI launch token and loopback Host/Origin checks (`ui.py`, `_authorized`) |
| D | Ring floods | Each ring costs one store read; a lost or dropped ring is covered by a 2 s re-read |

Residual risk: on the UDP fallback any local user can send wake-ups (extra store reads, never
decisions). Covering tests: `test_approval_broker.py`, `test_sec1_regressions.py` (doorbells).

### Team memory

Assets: what teammates' sessions recall, the review record, local files near the clone.

| STRIDE | Threat | Mitigation |
| --- | --- | --- |
| S | Author spoofs a name to accept their own proposal | Branch user, `Magent-Author` trailer and every commit author must agree; a reviewer matching any is refused (`team_memory.py`, `_authors`, `decide`) |
| T | Push straight to `main` (review is client-side) | `sync` refuses a tree review would refuse (`tree_problems`); docs ask for branch protection |
| T | Symlink or submodule nodes, hooks or fsmonitor from the shared repo | `core.symlinks=false`, `core.hooksPath=/dev/null`, `core.fsmonitor=false` on every git call; mode checks in `show`/`tree_problems`; recall skipped if the clone has a symlink (`recall_safe`, `agent._team_memory_manager`) |
| T | Prompt injection through recalled nodes | Nodes framed as teammates' reference notes, not instructions (`agent_runtime/context.py`); tools still need their normal approvals |
| R | Who accepted what | `REVIEWS.jsonl` on `main`, merge commits name author and reviewer |
| I | Secrets in shared nodes | Secret scrubber check on propose, show and sync (`validate_node`) |
| E | Option injection through a remote URL | `git clone -- <remote>` |

Residual risk: identity is not authentication (anyone can set a Git author name); a teammate
who lies about their name and has push access can bypass review unless the host protects
`main`. Injection text that passes review is still text the model reads. Covering tests:
`test_team_memory.py`, `test_sec1_regressions.py` (team memory).

### Plugin signing and registries

Assets: code and permissions that run inside MagAgent; the trust store.

| STRIDE | Threat | Mitigation |
| --- | --- | --- |
| S | Key substitution under a trusted key id | `trust_key` refuses to replace a different key with the same id (`plugin_signing.py`) |
| T | Content added after signing (nested manifest-named files, symlinked directories) | Digest covers everything but the top-level manifest and signature, hashes links as links; signed packs may not contain symlinks (`plugin_sdk.plugin_digest`, `pack_symlinks`) |
| T | Zip slip, links, devices, decompression bombs | Member checks plus `filter="data"`, 5,000 entries and 200 MiB unpacked limits (`plugin_registry._safe_extract`) |
| T | TOCTOU between verify and install | Signed packs are verified again on the installed copy and removed if invalid (`plugins.install_plugin`); enabling rechecks the signature |
| T | Downgrade, rollback, cross-registry shadowing, wrong pack in archive | Numeric version order, no implicit downgrade, one registry per name or `--registry`, archive name and version must match the entry (`install_from_registry`) |
| T | HTTPS downgrade by redirect | Every redirect hop checked (`_read`) |
| I | Misleading consent | The trust prompt shows permissions from the signed manifest (`cli/commands/plugins.py`) |

Residual risk: trust is per key, not per plugin name (a trusted key may sign any name); the
first key is trusted on first use after a prompt; there is no revocation list or transparency
log. Covering tests: `test_plugin_signing_registry.py`, `test_plugin_sdk.py`,
`test_sec1_regressions.py` (plugins).

### Graph MCP and A2A executors

Assets: provider keys and other environment secrets, internal network services, approvals.

| STRIDE | Threat | Mitigation |
| --- | --- | --- |
| I | A graph sends a secret variable to its own URL | `token_env` must start with `A2A_`; the approval names the variable (`agraph/remote_executors.py`) |
| I | SSRF to metadata or private services | Shared URL policy, private and link-local refused unless `allow_private_network: true` (shown in the approval); redirects not followed (`_check_a2a_address`) |
| E | Call without approval | Every call goes through the graph's approval path or `--yes` (`agraph/execute.py`, `_approve_external_call`) |
| D | Huge replies | Replies truncated to 200,000 characters |

Residual risk: DNS can change between the address check and the request; the A2A response body
is read fully before truncation; `--yes` approves every call in the graph. Covering tests:
`test_graph_executors.py`, `test_sec1_regressions.py` (A2A).

### VS Code extension

Assets: the program the extension starts and its permission mode.

| STRIDE | Threat | Mitigation |
| --- | --- | --- |
| E | A repository's `.vscode/settings.json` names the executable or picks a permissive mode | Settings scoped `machine` and read from user settings only (`userSetting`); extension disabled in untrusted workspaces (`package.json`) |
| T | Command injection | `spawn` with an argument list, no shell; the prompt goes through a 0600 file in a private temp directory |
| I | Webview script injection | No webviews: results open as Markdown text documents, approvals as native modals |
| S | Approving by dismissing | A dismissed prompt sends a deny |

Covering tests: `editors/vscode/test/client.test.ts`.

### Local inputs: `--prompt-file`, `MAGENT_MOCK_SCRIPT`, `auth add`

| STRIDE | Threat | Mitigation |
| --- | --- | --- |
| D | `--prompt-file /dev/zero`, a FIFO, or a file that grows | Regular files only, opened non-blocking, at most the limit read from one handle (`cli/shared._resolve_ask_task`) |
| T | Scripted mock replies | Used only with the `mock` provider when the variable is set; scripted tool calls go through normal approvals (`providers/mock.py`) |
| I | Key visible in argv, errors or a readable file | `--api-key-stdin`; the old `--api-key` is hidden and warns; `config.toml` is made 0600 before the key is written; keyring errors are scrubbed (`auth_store.py`) |

Residual risk: following a symlinked prompt file is allowed (it is your own path).
Covering tests: `test_ask_prompt_file.py`, `test_sec1_regressions.py`.

### Parallel read tools and grants

| STRIDE | Threat | Mitigation |
| --- | --- | --- |
| T | A read runs before an earlier write or after a denial | Read-only runs start only when the loop reaches them (`agent_runtime/parallel_tools.py`, `tool_loop.py`) |
| E | Prompts race | Permission checks are synchronous, so prompts stay one at a time |
| E | Grant scope confusion | Grants match the exact action digest (command plus working directory); session grants need the same session id, and session-less executors get a unique id (`tools/shell._shell_grant_origin`) |
| E | Expiry bypass | Persistent grants expire (`grant_ttl_days`), are listed and revocable, and every use is receipted (`approval_broker.py`) |

Residual risk: within one batch, reads after a denied read have already run (they are reads
and each needed its own approval); expiry uses the wall clock, so someone who can set the
system clock back can extend a grant. Covering tests: `test_parallel_tools_and_edit_quality.py`,
`test_approval_broker.py`, `test_sec1_regressions.py`.

## Verification

Run the credential-free assurance probes at any time:

```bash
magent system security-report
magent system security-report --output security-report.json
```

The report uses schema `magent.security-assurance.v1`, contains no secret values, and is
embedded in `magent release evidence`. CI also runs focused bypass, durability, gateway,
provider, and packaged-wheel acceptance tests.

## Residual Risks

Approved shell commands execute with the user's authority unless an OS sandbox is enabled.
Third-party providers, browsers, language servers, plugins, MCP servers, and gateways retain
their own supply-chain and service risks. Localhost provider endpoints require an explicit
private-network allowance. Compatible providers have adapter evidence but are not represented
as live-qualified. No policy can guarantee that user-approved code is benign.

Critical or high security and data-loss findings block release. Report vulnerabilities through
the repository's private security-reporting channel; do not include credentials or sensitive
project data in a public issue.
