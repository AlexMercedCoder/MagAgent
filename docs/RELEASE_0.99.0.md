# MagAgent 0.99.0

MagAgent 0.99.0 aligns its Open Agent Profile and Agentic Graph implementations with the published
1.0 specifications and the 1.0.1 Python support libraries.

## Standards support

- OAP 1.0 Level 3 profile loading, composition, authority narrowing, runtime instantiation,
  reviewable state, lifecycle integration, and canonical `AgentStateDelta` persistence.
- AGS 1.0 Level 3 validation, deterministic planning and execution, decisions and joins, bounded
  loops and maps, subgraphs, human gates, criteria evaluation, resume protection, and portable run
  records.
- RFC 8785 canonical JSON digests for portable profile, specification, graph, and run identities.
- CI checkouts pinned to OAP commit `7fb633a1a59dd7636ffb0030d254f2f58934f74a` and AGS commit
  `f180a4dbd07911f90dd0821f531d7ccd51bb0764`.

The detailed claims are published in [oap-conformance.json](oap-conformance.json) and
[ags-conformance.json](ags-conformance.json). These files are implementation evidence and do not
represent third-party certification.

## Compatibility

Existing MagAgent Markdown agent definitions continue to load through the legacy conversion
boundary. Newly authored, imported, exported, and updated profiles use canonical OAP 1.0 fields.
MagAgent-specific AGS data is retained only in `x-` extension fields, and portable run records use
the specification-owned schema.

The CLI creator, setup wizard, legacy converter, Web UI creator, and Web UI import/export paths all
share the canonical authoring and validation boundary. The Web UI now retains the selected provider
and model route instead of silently discarding it, and invalid authoring input is returned as a
client error.

## Upgrade

```bash
python -m pip install --upgrade "mag-agent==0.99.0"
magent --version
magent agent conformance
magent docs doctor
```

Before publishing, run the complete supported-Python CI matrix, immutable upstream fixture checks,
dependency audit, build and wheel smoke tests, and generate the release-candidate evidence bundle
from the tagged commit.
