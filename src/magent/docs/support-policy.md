# Platform Support and Deprecation Policy

MagAgent's machine contracts are available through `magent system contracts`. The
command is the source of truth for Command Center and third-party clients.
`magent system compatibility` provides the complete 1.0 candidate inventory, including
public imports, CLI commands, config keys, and stability labels.

## Supported runtime

- Python 3.11, 3.12, 3.13, and 3.14 are tested release targets.
- MagGraph 0.4.x is the current memory API family; MagAgent requires `maggraph>=0.4.1`.
- Task snapshots use `magent.task.v2`; task events use `magent.task-event.v1`. Desktop clients may continue reading v1 snapshots during the additive-state migration.
- Plugin manifests use SDK API version `1`.
- Provider compatibility reports use `magent.provider-support.v1`.
- Persistent state uses `magent.state.v1`; release supply-chain evidence uses
  `magent.supply-chain.v1`.
- Core MCP support is dual-era through legacy `2025-11-25` and modern `2026-07-28`.

## Compatibility levels

- **stable**: additive fields may appear, consumers must tolerate unknown fields,
  and removals require at least one prior minor release with a deprecation notice.
- **beta**: behavior is tested and documented, but incompatible changes may occur in
  a minor release before 1.0 with migration notes.
- **experimental**: disabled or explicitly opt-in and not a supported release claim.

Task and event state names or required identity fields will not change within v1.
Renderers must ignore unknown event types and detail keys. Plugin manifests reject an
unknown API version rather than guessing compatibility.

Offline provider catalog validation and live completion/tool-use validation are
separate results. This prevents a missing credential, exhausted quota, or temporary
network failure from being misreported as an adapter contract defect.

## Deprecations

After 0.90.0, stable candidate contracts are frozen for 1.0. Deprecations are documented in release notes, command help, and the generated support
matrix. A stable contract receives at least one minor release of notice. Security or
data-loss fixes may disable unsafe behavior immediately, with an explicit migration
path whenever one exists.

Classic MCP stdio and Streamable HTTP remain supported while the ecosystem migrates.
Deprecated HTTP+SSE is opt-in only. Experimental MCP Tasks, remote Skills, and Apps
rendering are not advertised as supported until their upstream schemas, SDK adapters,
and conformance fixtures pass the roadmap acceptance gates.

## Upgrade and downgrade

Run `magent system migrate` to preview an upgrade and `magent system migrate --apply` to
create a mode-0600 backup and apply it. Restore with `magent system rollback <backup>`
after previewing, then add `--apply`. Unknown config keys are preserved. If state declares
a schema newer than the installed runtime understands, MagAgent refuses to load it and
directs the user to upgrade or restore a compatible backup.
