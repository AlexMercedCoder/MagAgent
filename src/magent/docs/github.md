# GitHub Workflows

MagAgent can use the authenticated `gh` CLI for PR and issue workflows.

Commands:

- `magent github status`
- `magent github issues`
- `magent github issue <number>`
- `magent github prs`
- `magent github pr <number>`
- `magent github checks`
- `magent github checks <pr-number>`

These commands intentionally rely on your existing GitHub CLI authentication. They do not introduce a separate token store.

Good uses:

- triage open issues before planning work
- inspect PR files and status checks
- summarize review context before a local fix
- pair with `magent ci --logs --repair-plan`
