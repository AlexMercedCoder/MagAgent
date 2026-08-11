# Security And Hardening

MagAgent 0.70.0 revalidates every boundary where agent-generated input can reach the host,
network, gateways, plugins, local services, or durable state.

## Inspect Shell Policy

Use the classifier as a dry run before trusting a command shape:

```bash
magent permission classify "find . -name '*.log' -delete"
magent permission classify "curl -s https://example.com | head"
magent permission classify "python -m pytest -q" --json
```

Classification parses command segments, assignments, redirects, and nested substitutions.
Destructive flags, file-writing redirects, uploads, and disguised blocked commands cannot be
lowered by an allowlist. Saved approvals compare structured command shapes and never allow a
wildcard to cross into another pipeline or interpreter.

Use `magent permission trust-list` to inspect saved approvals and
`magent permission trust-clear --yes` to remove them.

## Check Secret Hygiene

```bash
magent permission secrets
magent permission secrets --json
```

The check reports plaintext provider keys, unsafe config-file permissions, and gateway access
that is explicitly open to everyone. It reports configuration locations and repair commands,
but never prints credential values. Prefer `magent auth add PROVIDER` or an environment variable
over storing a key directly in TOML.

## Gateway Access

An empty `allowed_user_ids` list denies everyone. To operate a gateway, configure explicit user
IDs. `allow_anyone = true` is available as a deliberate public-access opt-in and is reported by
the secret-hygiene check.

Persistent remote approvals are disabled by default. Gateway sessions serialize requests per
channel, enforce mention settings, redact provider errors, and scope ordinary approvals to the
current remote session.

## Network Policy

Web and browser tools accept HTTP and HTTPS URLs only. They reject loopback, private,
link-local, multicast, reserved, and cloud-metadata destinations after DNS resolution and after
every redirect. Responses are streamed into bounded buffers. GET and HEAD requests remain
automatic under balanced permissions; methods that mutate remote state require confirmation.

The local operations UI uses a random launch token, validates the host header, and exposes
state-changing actions as POST requests. The static dashboard serves only its generated file,
not the surrounding workbench directory.

## Shell Sandboxes

Set `permissions.shell_sandbox` for command isolation independently of permission prompts.
Available profiles are `off`, `docker`, `bubblewrap`, and `sandbox-exec` (macOS). The Docker
profile mounts the project as the working area, drops Linux capabilities, enables
`no-new-privileges`, and disables networking unless it is explicitly requested. If the selected
sandbox runtime is unavailable, MagAgent fails closed rather than silently running on the host.

```toml
[permissions]
shell_sandbox = "docker"
shell_sandbox_network = false
```

## Spend Limits

Optional limits stop additional model rounds when recorded session or rolling 24-hour spend
reaches the configured amount. Zero disables a limit.

```toml
[budgets]
session_usd = 5.0
daily_usd = 25.0
warn_at = 0.8
```

## Durable State

Workbench ledgers use cross-process locks and atomic replacement. Corrupt JSON is preserved for
diagnosis instead of being silently replaced with an empty ledger. Daemon jobs use durable
claims, and session messaging verifies ownership and permissions of its runtime directory.

## Release Checks

The release gate includes:

```bash
make lint
pytest tests/unit -q
pytest tests/unit --cov=magent --cov-report=term-missing
magent docs generate-reference --check
magent docs doctor
magent system security-report --output security-report.json
python -m build
python -m twine check dist/*
```

Focused regression suites cover permission bypasses, gateway authorization, local UI tokens,
plugin and session path containment, durable state, provider conformance, CLI registration, and
safe resource naming. See `magent docs show threat-model` for trust boundaries,
threats, mitigations, residual risks, and the release-blocking policy.
