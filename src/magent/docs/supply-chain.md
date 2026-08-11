# Release Supply Chain

MagAgent generates release evidence from public tooling and local artifacts. First audit the
resolved project dependency set:

```bash
python -m pip_audit . --format json --output dependency-audit.json
```

After building the wheel and source distribution, create the bundle:

```bash
magent release supply-chain \
  --artifact dist/mag_agent-VERSION-py3-none-any.whl \
  --artifact dist/mag_agent-VERSION.tar.gz \
  --audit-report dependency-audit.json \
  --out-dir dist/release-evidence
```

The directory contains:

- `supply-chain.json`: aggregate pass/fail evidence;
- `sbom.cdx.json`: CycloneDX 1.6 direct-dependency SBOM;
- `provenance.intoto.jsonl`: in-toto statement with SLSA provenance predicate;
- `SHA256SUMS`: hashes for every release artifact.

The secret scan examines tracked production and documentation files and reports only path,
line, and finding type, never the matched value. Test fixtures are excluded. Dependency
audit evidence is mandatory for a passing bundle. The provenance statement identifies the
source commit and builder, but it is not a cryptographic signature. Tag, artifact, and native
installer signing require maintainer-controlled platform credentials.
