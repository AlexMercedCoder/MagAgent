# Semantic Memory

Semantic memory search is a local sidecar index for MagGraph memory.

Commands:

- `magent memory index`: build or update the sidecar.
- `magent memory search "query"`: hybrid semantic and keyword search.
- `magent memory search --semantic "query"`: semantic-only search.
- `magent memory search --keyword "query"`: keyword search.
- `magent memory semantic status`: show sidecar status.
- `magent memory semantic reset`: reset the sidecar.

The sidecar is stored under:

`~/.config/magent/users/<user>/workbench/vector/memory_index.sqlite`

MagGraph remains the source of truth. The semantic index is disposable and can be rebuilt at any time. MagAgent uses Ollama embeddings when available and falls back to deterministic local vectors when offline.

In keyword mode, MagAgent now delegates to MagGraph's native structured search API. Hybrid mode uses the semantic sidecar first when available, then falls back to MagGraph search. Recall context is assembled from MagGraph recall bundles so semantic results still carry graph provenance such as backlinks and relevance reasons.
