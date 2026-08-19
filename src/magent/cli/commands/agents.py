"""Open Agent Profile and legacy agent command registrations."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

console = Console()


def _load_document_input(path: str) -> dict:
    """Read one JSON OAP document from stdin or a file."""
    text = sys.stdin.read() if path == "-" else Path(path).expanduser().read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Profile input must be a JSON object")
    return data


def _registry(project: str):
    from magent.agent_profiles.registry import AgentProfileRegistry

    try:
        from magent.config import get_current_user, load_config

        user = get_current_user()
        config = load_config(user) if user else None
    except Exception:
        config = None
    return AgentProfileRegistry(project, config), config


def _require_profile(name: str, project: str):
    registry, config = _registry(project)
    profile = registry.get(name)
    if profile is None:
        console.print_json(data={"ok": False, "error": f"Agent profile not found: {name}"})
        raise typer.Exit(1)
    return profile, config


def register_agent_commands(agent_app: typer.Typer) -> None:
    @agent_app.command("schema")
    def agent_schema_cmd(project: str = typer.Option(".", "--project", "-p")) -> None:
        """Return the versioned OAP editor contract and local choices."""
        from magent.agent_profiles.desktop import profile_contract

        _registry_instance, config = _registry(project)
        console.print_json(data=profile_contract(project, config))

    @agent_app.command("preview")
    def agent_preview_cmd(
        input_path: str = typer.Option("-", "--input", help="JSON document path, or - for stdin."),
        project: str = typer.Option(".", "--project", "-p"),
    ) -> None:
        """Validate and resolve an OAP document without writing it."""
        from magent.agent_profiles.desktop import preview_profile

        try:
            _registry_instance, config = _registry(project)
            result = preview_profile(_load_document_input(input_path), project=project, config=config)
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

    @agent_app.command("apply")
    def agent_apply_cmd(
        input_path: str = typer.Option("-", "--input", help="JSON document path, or - for stdin."),
        scope: str = typer.Option("user", "--scope", help="user, project, or portable"),
        project: str = typer.Option(".", "--project", "-p"),
        expected_digest: str = typer.Option("", "--expected-digest"),
    ) -> None:
        """Create or conflict-safely update an OAP document."""
        from magent.agent_profiles.desktop import apply_profile

        try:
            _registry_instance, config = _registry(project)
            result = apply_profile(
                _load_document_input(input_path),
                scope=scope,
                project=project,
                config=config,
                expected_digest=expected_digest,
            )
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

    @agent_app.command("clone")
    def agent_clone_cmd(
        source: str,
        name: str,
        scope: str = typer.Option("user", "--scope"),
        project: str = typer.Option(".", "--project", "-p"),
    ) -> None:
        """Copy a profile without carrying state or history."""
        from magent.agent_profiles.desktop import clone_profile

        _registry_instance, config = _registry(project)
        result = clone_profile(source, name, scope=scope, project=project, config=config)
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

    @agent_app.command("import")
    def agent_import_cmd(
        source: Path,
        scope: str = typer.Option("user", "--scope"),
        project: str = typer.Option(".", "--project", "-p"),
        name: str = typer.Option("", "--name"),
        dry_run: bool = typer.Option(False, "--dry-run"),
    ) -> None:
        """Preview or import an OAP document."""
        from magent.agent_profiles.desktop import import_profile

        _registry_instance, config = _registry(project)
        result = import_profile(
            source, scope=scope, project=project, config=config, name=name, dry_run=dry_run
        )
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

    @agent_app.command("export")
    def agent_export_cmd(
        name: str,
        output: Annotated[Path, typer.Option("--output", "-o")],
        project: str = typer.Option(".", "--project", "-p"),
    ) -> None:
        """Export a portable profile with secret-like extension fields removed."""
        from magent.agent_profiles.desktop import export_profile

        _registry_instance, config = _registry(project)
        result = export_profile(name, output, project=project, config=config)
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

    @agent_app.command("delete")
    def agent_delete_cmd(
        name: str,
        expected_digest: str = typer.Option(..., "--expected-digest"),
        project: str = typer.Option(".", "--project", "-p"),
        yes: bool = typer.Option(False, "--yes", help="Confirm permanent deletion."),
    ) -> None:
        """Delete a user-owned profile after digest and confirmation checks."""
        from magent.agent_profiles.desktop import delete_profile

        if not yes:
            console.print_json(data={"ok": False, "error": "Pass --yes after reviewing the profile."})
            raise typer.Exit(1)
        _registry_instance, config = _registry(project)
        result = delete_profile(
            name, project=project, config=config, expected_digest=expected_digest
        )
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

    @agent_app.command("revisions")
    def agent_revisions_cmd(
        name: str, project: str = typer.Option(".", "--project", "-p")
    ) -> None:
        """List restorable authoring revisions for an OAP profile."""
        from magent.agent_profiles.desktop import profile_checkpoints

        _registry_instance, config = _registry(project)
        result = profile_checkpoints(name, project=project, config=config)
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

    @agent_app.command("detail")
    def agent_detail_cmd(
        name: str, project: str = typer.Option(".", "--project", "-p")
    ) -> None:
        """Return profile document, effective authority, and revision history."""
        from magent.agent_profiles.desktop import inspect_profile

        _registry_instance, config = _registry(project)
        result = inspect_profile(name, project=project, config=config)
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

    @agent_app.command("restore-revision")
    def agent_restore_revision_cmd(
        name: str,
        checkpoint: Path,
        expected_digest: str = typer.Option(..., "--expected-digest"),
        project: str = typer.Option(".", "--project", "-p"),
        yes: bool = typer.Option(False, "--yes"),
    ) -> None:
        """Conflict-safely restore a profile revision created by MagAgent."""
        from magent.agent_profiles.desktop import rollback_profile

        if not yes:
            console.print_json(data={"ok": False, "error": "Pass --yes after reviewing the revision."})
            raise typer.Exit(1)
        _registry_instance, config = _registry(project)
        result = rollback_profile(
            name,
            checkpoint,
            project=project,
            config=config,
            expected_digest=expected_digest,
        )
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)

    @agent_app.command("list")
    def agent_list_cmd(project: str = typer.Option(".", "--project", "-p")) -> None:
        """List profiles with revision, trust, source, and digest."""
        registry, _ = _registry(project)
        console.print_json(data=registry.list())

    @agent_app.command("show")
    def agent_show_cmd(name: str, project: str = typer.Option(".", "--project", "-p")) -> None:
        """Show a resolved profile document."""
        profile, _ = _require_profile(name, project)
        console.print_json(data={"ok": True, "profile": profile.as_dict()})

    @agent_app.command("explain")
    def agent_explain_cmd(name: str, project: str = typer.Option(".", "--project", "-p")) -> None:
        """Explain the capabilities this profile actually receives."""
        from magent.agent_profiles.effective import resolve_effective_profile
        from magent.tools.catalog import built_in_tool_definitions

        profile, config = _require_profile(name, project)
        if config is None:
            console.print_json(data={"ok": False, "error": "Configure a MagAgent user before resolving effective policy"})
            raise typer.Exit(1)
        granted = {item.get("function", {}).get("name", "") for item in built_in_tool_definitions()}
        effective = resolve_effective_profile(profile, config, granted)
        console.print_json(data={"ok": True, "effective_profile": effective.as_dict()})

    @agent_app.command("validate")
    def agent_validate_cmd(path: Path) -> None:
        """Validate an OAP or legacy agent document without modifying it."""
        from magent.agent_profiles.registry import AgentProfileRegistry

        try:
            profile = AgentProfileRegistry(path.parent).load_path(path)
            console.print_json(data={"ok": True, "profile": profile.as_dict(include_document=False)})
        except Exception as exc:
            console.print_json(data={"ok": False, "error": str(exc)})
            raise typer.Exit(1) from exc

    @agent_app.command("create")
    def agent_create_cmd(
        name: str,
        project: str = typer.Option(".", "--project", "-p"),
        description: str = typer.Option("", "--description"),
        mode: str = typer.Option("subagent", "--mode"),
        prompt: str = typer.Option("", "--prompt"),
        force: bool = typer.Option(False, "--force"),
    ) -> None:
        """Create a portable OAP Markdown profile."""
        from magent.agent_profiles.documents import atomic_write, render_document

        normalized = name.strip().lower()
        path = Path(project).resolve() / ".magent" / "agents" / f"{normalized}.md"
        if path.exists() and not force:
            console.print_json(data={"ok": False, "error": f"Agent already exists: {path}"})
            raise typer.Exit(1)
        document = {
            "oap": "1.0",
            "metadata": {"name": normalized, "description": description or normalized, "revision": 1},
            "spec": {"role": {"instructions": prompt or f"You are the {normalized} agent. Describe your specialty here."}, "runtime": {"mode": mode}},
            "state": [], "history": [], "proposals": [], "lifecycle": {"writeback": "propose"},
        }
        atomic_write(path, render_document(document, "md"))
        console.print_json(data={"ok": True, "path": str(path), "profile": document})

    @agent_app.command("convert")
    def agent_convert_cmd(path: Path, write: bool = typer.Option(False, "--write")) -> None:
        """Preview legacy-to-OAP conversion; write only when explicitly requested."""
        from magent.agent_profiles.documents import atomic_write, render_document
        from magent.agent_profiles.registry import AgentProfileRegistry

        profile = AgentProfileRegistry(path.parent).load_path(path)
        rendered = render_document(profile.document, "md")
        if not write:
            console.print(rendered)
            return
        if not profile.legacy:
            console.print_json(data={"ok": False, "error": "Document is already OAP"})
            raise typer.Exit(1)
        backup = path.with_suffix(path.suffix + ".legacy.bak")
        shutil.copy2(path, backup)
        atomic_write(path, rendered)
        console.print_json(data={"ok": True, "path": str(path), "backup": str(backup)})

    @agent_app.command("state")
    def agent_state_cmd(name: str, project: str = typer.Option(".", "--project", "-p")) -> None:
        """Show durable, untrusted state for a profile."""
        profile, _ = _require_profile(name, project)
        console.print_json(data={"ok": True, "name": profile.name, "revision": profile.revision, "state": profile.document.get("state", [])})

    @agent_app.command("history")
    def agent_history_cmd(name: str, project: str = typer.Option(".", "--project", "-p")) -> None:
        """Show profile state revision history."""
        profile, _ = _require_profile(name, project)
        console.print_json(data={"ok": True, "name": profile.name, "history": profile.document.get("history", [])})

    @agent_app.command("rollback")
    def agent_rollback_cmd(name: str, checkpoint: Path, project: str = typer.Option(".", "--project", "-p")) -> None:
        """Restore a validated profile checkpoint."""
        from magent.agent_profiles.delta import restore_checkpoint

        profile, _ = _require_profile(name, project)
        if profile.source_path is None:
            console.print_json(data={"ok": False, "error": "Managed profiles cannot be modified"})
            raise typer.Exit(1)
        result = restore_checkpoint(profile.source_path, checkpoint)
        console.print_json(data=result)

    @agent_app.command("forget")
    def agent_forget_cmd(name: str, entry_id: str, project: str = typer.Option(".", "--project", "-p")) -> None:
        """Queue removal of one profile state entry for review."""
        from magent.agent_profiles.delta import ProfileDeltaInbox, make_delta

        profile, _ = _require_profile(name, project)
        delta = make_delta(profile, [{"op": "remove", "path": f"/state/{entry_id}"}], evidence="Explicit CLI forget request")
        ProfileDeltaInbox(project).add(delta)
        console.print_json(data={"ok": True, "delta": delta})

    @agent_app.command("inbox")
    def agent_inbox_cmd(project: str = typer.Option(".", "--project", "-p")) -> None:
        """List pending profile state changes."""
        from magent.agent_profiles.delta import ProfileDeltaInbox

        console.print_json(data={"ok": True, "deltas": ProfileDeltaInbox(project).pending()})

    @agent_app.command("accept")
    def agent_accept_cmd(
        delta_id: str,
        project: str = typer.Option(".", "--project", "-p"),
        rebase: bool = typer.Option(True, "--rebase/--no-rebase", help="Rebase when unrelated profile state changed."),
    ) -> None:
        """Apply a reviewed profile state delta."""
        from magent.agent_profiles.delta import ProfileDeltaInbox

        try:
            item = ProfileDeltaInbox(project).decide(delta_id, "accepted", auto_rebase=rebase)
            console.print_json(data={"ok": True, "delta": item})
        except Exception as exc:
            console.print_json(data={"ok": False, "error": str(exc)})
            raise typer.Exit(1) from exc

    @agent_app.command("reject")
    def agent_reject_cmd(delta_id: str, reason: str = typer.Option("", "--reason"), project: str = typer.Option(".", "--project", "-p")) -> None:
        """Reject a proposed profile state delta."""
        from magent.agent_profiles.delta import ProfileDeltaInbox

        item = ProfileDeltaInbox(project).decide(delta_id, "rejected", reason)
        console.print_json(data={"ok": True, "delta": item})

    @agent_app.command("digest")
    def agent_digest_cmd(name: str, project: str = typer.Option(".", "--project", "-p")) -> None:
        """Show full and spec-only canonical digests."""
        profile, _ = _require_profile(name, project)
        console.print_json(data={"ok": True, "name": profile.name, "profile_digest": profile.profile_digest, "spec_digest": profile.spec_digest})

    @agent_app.command("conformance")
    def agent_conformance_cmd() -> None:
        """Run the packaged offline OAP Level 3 harness conformance suite."""
        from magent.agent_profiles.conformance import run_conformance

        result = run_conformance()
        console.print_json(data=result)
        if not result["ok"]:
            raise typer.Exit(1)

    @agent_app.command("run")
    def agent_run_cmd(name: str, task: str, project: str = typer.Option(".", "--project", "-p")) -> None:
        """Render a manual @agent invocation for compatibility."""
        from magent.agent_defs import resolve_invocation

        result = resolve_invocation(f"@{name} {task}", project)
        console.print_json(data=result)
        if not result.get("ok"):
            raise typer.Exit(1)
