"""H-2: scripts/check_release_metadata.py."""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "check_release_metadata", ROOT / "scripts" / "check_release_metadata.py"
)
assert SPEC and SPEC.loader
check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    for name in ("pyproject.toml", "README.md", "CHANGELOG.md"):
        shutil.copy(ROOT / name, tmp_path / name)
    (tmp_path / "docs").mkdir()
    (tmp_path / "webui").mkdir()
    for name in ("ags-conformance.json", "oap-conformance.json"):
        shutil.copy(ROOT / "docs" / name, tmp_path / "docs" / name)
    shutil.copy(ROOT / "webui" / "package.json", tmp_path / "webui" / "package.json")
    return tmp_path


def test_repository_metadata_agrees() -> None:
    _package, _seen, problems = check.collect(ROOT)
    assert problems == []


def test_detects_the_drift_fixed_in_h1(repo: Path, monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_REF", raising=False)
    conformance = repo / "docs" / "ags-conformance.json"
    data = json.loads(conformance.read_text())
    data["implementation_version"] = "0.99.0"
    conformance.write_text(json.dumps(data))
    changelog = repo / "CHANGELOG.md"
    # Mark the newest released heading unreleased, whichever version it is, so the test keeps
    # working after a release bump.
    changelog.write_text(
        re.sub(
            r"^## (\d+\.\d+\.\d+) \([^)]*\)",
            r"## \1 — Unreleased",
            changelog.read_text(),
            count=1,
            flags=re.MULTILINE,
        )
    )
    readme = repo / "README.md"
    readme.write_text(readme.read_text().replace("Current release: **", "Release: **", 1))

    _package, _seen, problems = check.collect(repo)
    text = "\n".join(problems)
    assert "ags-conformance.json says 0.99.0" in text
    assert "marked unreleased" in text
    assert 'no "Current release' in text
    # Advisory by default, strict on request.
    assert check.main(["--root", str(repo)]) == 0
    assert check.main(["--root", str(repo), "--strict"]) == 1


def test_tag_builds_are_strict_and_must_match(repo: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("GITHUB_REF", "refs/tags/v9.9.9")
    assert check.main(["--root", str(repo), "--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["strict"] is True
    assert any("does not match" in item for item in report["problems"])
