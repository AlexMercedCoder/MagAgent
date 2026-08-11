# Release Policy

MagAgent releases are qualified by evidence, not version numbers alone. Run
`magent release check`, the full automated test suite, the real-agent eval suite,
documentation drift checks, and packaged-wheel smoke tests before publishing.

## Severity

- **Critical:** data loss, secret exposure, sandbox escape, arbitrary approval bypass, or a
  primary execution path that cannot complete. Blocks every release.
- **High:** repeatable failure in installation, provider setup, file editing, cancellation,
  memory integrity, or stable machine contracts. Blocks a milestone release.
- **Medium:** degraded but recoverable behavior with a documented workaround. May ship only
  when recorded in release evidence and known limitations.
- **Low:** cosmetic or narrow inconvenience that does not threaten correctness. Track it and
  avoid obscuring it with a misleading success claim.

## Evidence

`magent release evidence` creates `magent.release-evidence.v2` JSON. It records the source
commit, runtime, docs and provider contract checks, eval report, test and coverage summaries,
CI URL, artifact hashes, contract and migration assurance, supply-chain evidence, and
severity-prefixed exceptions. `critical:` and `high:` exceptions
block the evidence gate; recorded `medium:` and `low:` exceptions remain visible without
overriding a passing enforced gate. Missing evidence is reported as missing;
the command never infers that an external check passed.

`magent release supply-chain` consumes a JSON `pip-audit` report plus built artifacts. It
emits a CycloneDX 1.6 SBOM, SHA-256 manifest, sanitized tracked-file secret scan, and
in-toto/SLSA-shaped provenance. These files do not claim cryptographic signing; signing
requires maintainer-controlled credentials and remains separately visible.
