from __future__ import annotations

from pathlib import Path

from magent.ask_audit import audit_one_shot_task, render_audit_note, requested_files


def test_requested_files_extracts_common_artifacts_in_order() -> None:
    task = "Create index.html, styles.css, app.js, and README.md. Then inspect app.js."

    assert requested_files(task) == ["index.html", "styles.css", "app.js", "README.md"]


def test_audit_reports_missing_files_and_permission_failures(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    audit = audit_one_shot_task(
        "Create index.html and app.js",
        tmp_path,
        {"files_touched": [], "permission_failures": ["run_shell: Permission required"]},
    )

    assert audit["ok"] is False
    assert audit["existing_requested_files"] == ["index.html"]
    assert audit["missing_requested_files"] == ["app.js"]
    assert "missing requested files: app.js" in render_audit_note(audit)
    assert "permission required: run_shell: Permission required" in render_audit_note(audit)
