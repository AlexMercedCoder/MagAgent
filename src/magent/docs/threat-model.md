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
