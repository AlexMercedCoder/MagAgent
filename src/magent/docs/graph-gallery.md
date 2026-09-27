# Agentic Graph gallery

Ready-to-adapt Agentic Graphs (AGS 1.0). Every file lives in
[`docs/examples/agraph/`](https://github.com/AlexMercedCoder/MagAgent/tree/main/docs/examples/agraph)
and passes `ags-validate --strict` and `magent graph validate --strict` in CI. Copy one into
your project, change the objective and parameters, then:

```bash
magent graph validate my.agraph.yaml --strict
magent graph plan my.agraph.yaml          # order, routes and cost preview
magent graph run my.agraph.yaml --approval-stdio   # or from the Web UI Graphs board
```

| Graph | Level | Shape | What it does |
| --- | --- | --- | --- |
| `minimal.agraph.yaml` | 1 | task, gate | Draft a CONTRIBUTING.md, then a maintainer approves it. The smallest useful graph. |
| `link-audit.agraph.yaml` | 1 | task | Crawl a built docs site and triage every broken link. |
| `mcp-issue-digest.agraph.yaml` | 1 | MCP tool, task | Fetch issues from a GitHub MCP server, then write a triage digest. |
| `a2a-research-handoff.agraph.yaml` | 1 | A2A agent, task | Hand a research question to an A2A agent, then check its answer against the project. |
| `bug-triage.agraph.yaml` | 2 | task | Reproduce, diagnose and propose a bounded fix for a reported bug. |
| `docs-audit.agraph.yaml` | 2 | task | Compare docs with current commands and behaviour and report stale material. |
| `release-prep.agraph.yaml` | 2 | task, gate | Prepare a release and require human approval before publishing. |
| `test-repair-loop.agraph.yaml` | 3 | loop, task | Diagnose-and-fix loop that stops when the suite is green, escalating if it cannot. |
| `docs-site-refresh.agraph.yaml` | 3 | map, subgraph, task | Refresh every stale page, audit links and fix what broke. |
| `library-v1-release.agraph.yaml` | 3 | decision, gate, task | Take an internal Python library to a documented, published v1.0. |

## Nodes run by MCP tools or A2A agents (experimental)

A task node can be executed by an external tool or agent instead of a MagAgent model session,
through MagAgent's `x-magagent-executor` extension (AGS requires harnesses to preserve `x-`
keys; other harnesses ignore this one):

```yaml
x-magagent-executor:
  kind: mcp                 # a tool on a server under [mcp.servers]
  server: github
  tool: search_issues
  arguments: {query: "${{ inputs.topic }} is:open"}
  output: issues            # a declared output (default: the first one)
```

```yaml
x-magagent-executor:
  kind: a2a                 # an A2A agent's JSON-RPC endpoint (message/send, tasks/get)
  url: https://agents.example.com/research
  message: "Research this: ${{ inputs.question }}"   # default: the node's prompt
  token_env: RESEARCH_AGENT_TOKEN                    # optional bearer token variable
  timeout_seconds: 600
  output: findings
```

- Every executor call is approved like any other external action: through `--approval-stdio`,
  the Web UI, the terminal, or `--yes`. With no way to ask, the call is refused (`RT042`).
- A2A needs HTTPS except on loopback. The reply's text parts (task artifacts, then the status
  message) become the output; `json: true` parses them as JSON.
- A task that ends `failed`, `canceled` or `rejected`, or asks for more input, fails the node
  (`RT047`); graphs cannot answer follow-up questions from an A2A agent.
- Validation reports executor mistakes as `MX001` before anything runs.

## Contributing a graph

Add the file under `docs/examples/agraph/`, add a row here, and run
`pytest tests/unit/test_agraph.py -k examples -m "slow or not slow"`: every example must validate
strictly and complete a structural run (no provider calls).
