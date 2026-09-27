#!/usr/bin/env python3
"""Check that every place MagAgent states its current release agrees.

The package version in pyproject.toml is the source of truth. These must match it:

- the web UI package version (webui/package.json);
- the README "Current release: **X.Y.Z**" line near the top;
- ``implementation_version`` in docs/ags-conformance.json and docs/oap-conformance.json;
- the newest released CHANGELOG heading (``## X.Y.Z (YYYY-MM-DD)``), which must also not be
  marked unreleased.

On a tag build (GITHUB_REF=refs/tags/vX.Y.Z) or with --strict, a mismatch fails and the tag must
equal the package version. Otherwise problems are printed as warnings and the exit code is 0, so
an in-progress version bump on a branch does not block work.

Usage: python scripts/check_release_metadata.py [--strict] [--root PATH] [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tomllib
from pathlib import Path

README_RE = re.compile(r"Current release:\s*\*\*(\d+\.\d+\.\d+)\*\*")
RELEASED_HEADING_RE = re.compile(r"^## (\d+\.\d+\.\d+)(.*)$", re.MULTILINE)


def collect(root: Path) -> tuple[str, dict[str, str | None], list[str]]:
    """Return (package version, observed versions by source, problems)."""

    problems: list[str] = []
    package = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    seen: dict[str, str | None] = {}

    webui = root / "webui" / "package.json"
    if webui.exists():
        seen["webui/package.json"] = json.loads(webui.read_text(encoding="utf-8")).get("version")

    readme = (root / "README.md").read_text(encoding="utf-8")
    match = README_RE.search(readme[:4000])
    seen["README.md current release"] = match.group(1) if match else None
    if not match:
        problems.append('README.md: no "Current release: **X.Y.Z**" line near the top')

    for name in ("ags-conformance.json", "oap-conformance.json"):
        path = root / "docs" / name
        if path.exists():
            seen[f"docs/{name}"] = json.loads(path.read_text(encoding="utf-8")).get(
                "implementation_version"
            )

    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    top: str | None = None
    for heading in RELEASED_HEADING_RE.finditer(changelog):
        rest = heading.group(2)
        if "unreleased" in rest.lower():
            problems.append(
                f"CHANGELOG.md: '## {heading.group(1)}{rest}' is marked unreleased; "
                "keep unreleased work under '## Unreleased'"
            )
            continue
        top = heading.group(1)
        break
    seen["CHANGELOG.md top released heading"] = top
    if top is None:
        problems.append("CHANGELOG.md: no released '## X.Y.Z (date)' heading found")

    for source, version in seen.items():
        if version is not None and version != package:
            problems.append(f"{source} says {version}, pyproject.toml says {package}")
    return package, seen, problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--strict", action="store_true", help="Fail on any mismatch.")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--json", action="store_true", help="Emit a JSON report.")
    args = parser.parse_args(argv)

    root = Path(args.root)
    package, seen, problems = collect(root)
    ref = os.environ.get("GITHUB_REF", "")
    tag_build = ref.startswith("refs/tags/")
    strict = args.strict or tag_build
    if tag_build:
        tag = ref.rsplit("/", 1)[-1].removeprefix("v")
        if tag != package:
            problems.append(f"tag {ref} does not match pyproject.toml version {package}")

    if args.json:
        print(
            json.dumps(
                {
                    "ok": not problems,
                    "strict": strict,
                    "package_version": package,
                    "sources": seen,
                    "problems": problems,
                },
                indent=2,
            )
        )
    else:
        label = "error" if strict else "warning"
        for problem in problems:
            print(
                f"::{label}::{problem}"
                if os.environ.get("GITHUB_ACTIONS")
                else f"{label}: {problem}"
            )
        if not problems:
            print(f"Release metadata agrees on {package}.")
        elif not strict:
            print("Advisory only: rerun with --strict (or on a tag build) to enforce.")
    return 1 if problems and strict else 0


if __name__ == "__main__":
    sys.exit(main())
