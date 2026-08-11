# Memory

MagAgent memory is powered by MagGraph. Each user gets a separate local graph:

`~/.config/magent/users/<user>/memory/`

MagAgent requires `maggraph>=0.4.1` and uses MagGraph's native memory APIs. The `0.4.1` floor includes Python 3.14-compatible abi3 wheels, explainable hybrid retrieval, global/project recall, backlink evidence, crash-safe reviewed batches, synchronized package metadata, and stable downstream API contract tests.

- Structured graph search over IDs, types, tags/frontmatter, body text, links, suppression state, and recency.
- Recall bundles with compact Markdown, body excerpts, links, backlinks, metadata, and relevance reasons.
- Memory schema helpers for preferences, project facts, decisions, tasks, session summaries, bookmarks, and tool failures.
- Durable merge, suppress, and unsuppress operations owned by MagGraph.
- Incremental `update_file` refreshes and `changed_since` change-feed entries after writes and inbox promotion.
- Explainable hybrid ranking combines MagGraph lexical, graph, recency, temporal,
  suppression, supersession, and project signals with optional semantic scores from
  MagAgent's local sidecar when the installed MagGraph supports it.
- New memories carry project, source task/session/tool, extraction method, confidence,
  validity, supersession, and canonical identity when supplied.

Useful commands:

- `magent memory stats`
- `magent memory search "query"`
- `magent memory show <node-id>`
- `magent memory node <node-id>`
- `magent memory update-node <node-id> --preview --body-file node.md`
- `magent memory update-node <node-id> --body-file node.md`
- `magent memory batch --operations-file reviewed-memory.json --preview`
- `magent memory batch --operations-file reviewed-memory.json`
- `magent memory traverse <node-id>`
- `magent memory inbox`
- `magent memory inbox accept <candidate-id>`
- `magent memory inbox reject <candidate-id>`
- `magent memory inbox edit <candidate-id> --body "..."`
- `magent memory review --diff`
- `magent memory approve`
- `magent memory export --out backup.json`
- `magent memory quality`
- `magent memory merge <target-id> <source-id> --preview`
- `magent memory merge <target-id> <source-id>`
- `magent memory suppress <node-id> --reason "stale"`
- `magent memory unsuppress <node-id>`
- `magent memory sync status`

Memory nodes are Markdown and can be reviewed in git. MagAgent recalls compact relevant memory before tasks, then writes learned facts, preferences, patterns, projects, bookmarks, tool failures, and session summaries when configured.

## Recall Provenance

Memory recall now includes a "Why These Memories" section. It shows which search fields matched, the graph score, and backlinks for each recalled anchor. Backlinks help explain why a memory is connected to the current task and what other memories depend on it.

For token efficiency, MagAgent asks MagGraph for recall bundles instead of expanding large traversals by default. Each bundle includes a compact summary, a bounded body excerpt, outgoing links, backlinks, metadata, and a relevance reason.

## Memory Inbox

`magent memory inbox` is a review queue for facts that look useful but should not be written automatically. It gathers candidates from project context, open tasks, plans, saved reviews, command failures, and recent session events.

Use `magent memory inbox accept <candidate-id>` to write one candidate to MagGraph. Use `magent memory inbox reject <candidate-id>` to suppress it, or `magent memory inbox edit <candidate-id> --body "..."` to polish the text before accepting.

Accepted inbox items are written through MagGraph's memory-node helpers. MagAgent refreshes the changed node with `update_file` and returns `changed_since` entries so UI and CLI callers can update cheaply.

Desktop editors should use `magent memory update-node --preview` before applying edits. Preview mode reports old/new body hashes, character counts, and links without writing to the graph.

For several reviewed changes, use `memory batch`. Operation objects support `update`
(`id`, `body`), `suppress` (`id`, optional `reason`), `unsuppress` (`id`), and `merge`
(`target_id`, `source_id`). MagGraph prevalidates the complete list and rolls back an
applied batch if an operation fails. Older MagGraph installations return an actionable
unsupported-capability error rather than applying a partial fallback batch.

## Retrieval Evals

Run `magent eval memory evals/memory.json` with labeled cases, or evaluate a
reproducible fixture with `--memory-dir`. Use `--report-out` to retain release evidence.

```json
{
  "name": "project-memory",
  "thresholds": {
    "precision_min": 0.8,
    "recall_min": 1.0,
    "stale_hit_rate_max": 0.0,
    "explanation_coverage_min": 1.0,
    "budget_pass_rate_min": 1.0
  },
  "cases": [
    {
      "id": "current-release-decision",
      "query": "how do we publish releases",
      "expected_ids": ["release_process"],
      "stale_ids": ["old_release_process"],
      "contradiction_ids": ["unsafe_release_process"],
      "expected_project": "demo",
      "require_provenance": true,
      "limit": 5,
      "max_context_tokens": 800
    }
  ]
}
```

The v2 report includes precision, recall, mean reciprocal rank, stale and contradiction
hit rates, project-scope accuracy, explanation, provenance and backlink coverage,
average context tokens, and token-budget pass rate. Suite thresholds become explicit
release gates. It is local and deterministic except for a configured semantic embedding
adapter.

The repository baseline can be reproduced with:

```bash
magent eval memory evals/memory-quality-v2.json \
  --memory-dir evals/fixtures/memory-demo --project demo
```
