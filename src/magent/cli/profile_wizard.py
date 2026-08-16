"""Interactive Open Agent Profile authoring flow."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table

from magent.agent_profiles.authoring import build_profile_document, write_profile
from magent.cli.wizard_guidance import explain_field, explain_options
from magent.config_ux import DEFAULT_MODELS, provider_choices


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _numbered_choice(
    label: str,
    choices: list[tuple[str, str]],
    *,
    default: str,
    console: Console,
) -> str:
    table = Table("#", label, show_header=True)
    for index, (_value, display) in enumerate(choices, 1):
        table.add_row(str(index), display)
    console.print(table)
    default_index = next(
        (str(index) for index, (value, _display) in enumerate(choices, 1) if value == default),
        "1",
    )
    while True:
        answer = Prompt.ask(label, default=default_index).strip()
        if answer.isdigit() and 1 <= int(answer) <= len(choices):
            return choices[int(answer) - 1][0]
        for value, _display in choices:
            if answer.lower() == value.lower():
                return value
        console.print(f"[yellow]Choose 1-{len(choices)} or enter a listed value.[/yellow]")


def _available_skills() -> list[str]:
    from magent.skills import SkillRegistry

    registry = SkillRegistry()
    registry.load()
    return sorted({str(item["name"]) for item in registry.list_all()})


def _select_references(label: str, names: list[str], *, console: Console) -> list[str] | None:
    """Return None for unrestricted, [] for none, or an explicit allowlist."""
    if not names:
        console.print(f"[dim]No configured {label.lower()} were discovered.[/dim]")
        return None
    explain_options(
        console,
        f"{label} selection",
        [
            ("all", "Do not add a profile restriction; any locally enabled entry remains available."),
            ("none", "Explicitly deny every entry in this category."),
            ("select", "Allow only the comma-separated names you choose."),
        ],
    )
    console.print(f"[dim]Available {label.lower()}: {', '.join(names)}[/dim]")
    mode = Prompt.ask(
        f"{label} access (all/none/select)", choices=["all", "none", "select"], default="all"
    )
    if mode == "all":
        return None
    if mode == "none":
        return []
    selected = _csv(Prompt.ask(f"Allowed {label.lower()} (comma-separated names)", default=""))
    unknown = sorted(set(selected) - set(names))
    if unknown:
        console.print(f"[yellow]Keeping unrecognized names for portable use: {', '.join(unknown)}[/yellow]")
    return selected


def run_profile_wizard(
    *,
    username: str,
    config: Any,
    store: Any,
    project: str | Path = ".",
    console: Console | None = None,
) -> dict[str, Any]:
    """Guide a user through a complete, validated OAP profile."""
    output = console or Console()
    root = Path(project).expanduser().resolve()
    output.print(
        Panel(
            "Create a reusable personality and capability profile. Profile requests can narrow "
            "MagAgent permissions, but cannot widen the harness policy.",
            title="Open Agent Profile Wizard",
        )
    )

    explain_field(
        output,
        "Identity",
        "The name is the stable CLI ID used by --agent and @name. The description helps people choose it.",
    )
    name = Prompt.ask("Profile name").strip()
    description = Prompt.ask("Short description", default=f"{name} agent profile").strip()
    explain_field(
        output,
        "Annotations",
        "Optional portable metadata for owners, teams, versions, or catalogs. It does not change behavior.",
    )
    annotations = {
        key.strip(): value.strip()
        for item in _csv(Prompt.ask("Metadata annotations (key=value, comma-separated, optional)", default=""))
        if "=" in item
        for key, value in [item.split("=", 1)]
    }
    explain_options(
        output,
        "Where should this profile live?",
        [
            ("user", "Available to you in every project on this machine."),
            ("project", "Stored in .magent/agents for this project only."),
            ("portable", "Stored in .agents for tools that share the portable convention."),
        ],
        note="Project and portable profiles can be committed; user profiles remain personal.",
    )
    scope = Prompt.ask(
        "Save scope (user/project/portable)",
        choices=["user", "project", "portable"],
        default="user",
    )
    explain_field(
        output,
        "Inheritance",
        "Extending another profile reuses its personality and limits. Child profiles may narrow authority, never widen it.",
    )
    extends = _csv(
        Prompt.ask(
            "Profiles to extend (comma-separated, blank for none)",
            default="",
        )
    )

    output.print("[bold]Personality and system behavior[/bold]")
    output.print(
        "[dim]Instructions define the job; persona defines voice; objectives define success; "
        "constraints define boundaries; examples demonstrate preferred behavior.[/dim]"
    )
    instructions = Prompt.ask(
        "Core instructions",
        default=f"Act as the {name} agent and help the user complete work end to end.",
    )
    persona = Prompt.ask("Persona and communication style", default="Pragmatic, clear, and collaborative")
    objectives = _csv(Prompt.ask("Objectives (comma-separated)", default="Complete requested work,Verify important results"))
    constraints = _csv(
        Prompt.ask(
            "Profile constraints (comma-separated)",
            default="Do not claim success without verification",
        )
    )
    examples = _csv(Prompt.ask("Example behaviors (comma-separated, optional)", default=""))

    model_config: dict[str, Any] = {}
    output.print(
        "[dim]A dedicated model makes this profile predictable. Choose no to inherit the active "
        "user/provider configuration and change models centrally.[/dim]"
    )
    if Confirm.ask("Choose a dedicated provider and model for this profile?", default=False):
        choices = [(item["id"], item["label"]) for item in provider_choices()]
        provider_id = _numbered_choice(
            "Provider", choices, default=config.default_provider, console=output
        )
        from magent.cli.model_picker import prompt_for_provider_model

        default_model = (
            config.default_model
            if provider_id == config.default_provider
            else DEFAULT_MODELS.get(provider_id, "")
        )
        model_id = prompt_for_provider_model(
            config,
            store,
            provider_id,
            default_model=default_model,
            console=output,
        )
        model_config = {"provider": provider_id, "id": model_id}

    output.print("[bold]Tools, skills, and permissions[/bold]")
    explain_options(
        output,
        "Tool policy presets",
        [
            ("all", "Request every locally enabled tool, including destructive tools."),
            ("coding", "Read, edit, run commands, and use the web; deny file deletion."),
            ("read-only", "Inspect and research without edits or shell execution."),
            ("custom", "Enter exact tool names, aliases, or glob patterns."),
        ],
        note="A profile only narrows the tools and permissions granted by MagAgent's harness policy.",
    )
    tool_policy = Prompt.ask(
        "Tool policy (all/coding/read-only/custom)",
        choices=["all", "coding", "read-only", "custom"],
        default="coding",
    )
    tool_allow: list[str]
    tool_deny: list[str]
    if tool_policy == "all":
        tool_allow, tool_deny = ["*"], []
    elif tool_policy == "coding":
        tool_allow, tool_deny = ["read", "write", "edit", "search", "shell", "web"], ["delete"]
    elif tool_policy == "read-only":
        tool_allow, tool_deny = ["read", "search", "web"], ["write", "edit", "delete", "shell"]
    else:
        tool_allow = _csv(Prompt.ask("Allowed tool names, aliases, or globs", default="*"))
        tool_deny = _csv(Prompt.ask("Denied tool names, aliases, or globs", default=""))

    mcp_config = config.mcp_servers if isinstance(config.mcp_servers, dict) else {}
    mcp_container = mcp_config.get("servers", mcp_config)
    mcp_names = sorted(mcp_container.keys()) if isinstance(mcp_container, dict) else []
    selected_mcp = _select_references("MCP servers", mcp_names, console=output)
    selected_skills = _select_references("Skills", _available_skills(), console=output)
    explain_options(
        output,
        "Permission modes",
        [
            ("paranoid", "Confirm most consequential tool actions."),
            ("balanced", "Auto-run low-risk actions and confirm higher-risk ones."),
            ("silent", "Auto-run broadly within configured policy; destructive boundaries remain."),
            ("yolo", "Request minimal confirmation. Use only in a trusted sandbox."),
        ],
        note=f"Current harness ceiling: {config.permission_mode}. A profile cannot make it more permissive.",
    )
    permission_mode = Prompt.ask(
        "Requested permission mode",
        choices=["paranoid", "balanced", "silent", "yolo"],
        default=config.permission_mode,
    )
    explain_options(
        output,
        "Network access",
        [
            ("none", "Remove web search, page fetching, browser inspection, and HTTP tools."),
            ("read", "Allow web search, research, page fetching, and browser inspection. Recommended."),
            ("full", "Also allow arbitrary HTTP methods for APIs and network writes."),
        ],
        note="Web search needs both network access read/full and a tool policy that includes web tools. The harness and tool-pack settings remain the ceiling.",
    )
    network_access = Prompt.ask(
        "Network access", choices=["none", "read", "full"], default="read"
    )

    output.print("[bold]Memory, runtime, and delegation[/bold]")
    explain_options(
        output,
        "Memory access",
        [
            ("off", "Do not read or write profile state or MagGraph memory."),
            ("read", "Recall existing memory but do not add new memory."),
            ("write", "Allow writes without recalling existing memory."),
            ("read_write", "Recall memory and propose or perform permitted updates."),
        ],
    )
    memory_mode = Prompt.ask(
        "Memory access", choices=["off", "read", "write", "read_write"], default="read_write"
    )
    explain_options(
        output,
        "Runtime role",
        [
            ("primary", "Can lead user sessions and optionally delegate work."),
            ("subagent", "A focused worker intended to receive bounded delegated tasks."),
        ],
    )
    runtime_mode = Prompt.ask("Runtime role", choices=["primary", "subagent"], default="primary")
    explain_field(
        output,
        "Model rounds",
        "Maximum provider/tool-loop rounds for one user turn. Lower values control cost; complex coding may need more.",
    )
    max_turns = IntPrompt.ask(
        "Maximum model rounds per user turn",
        default=int(config.get("agent", "max_model_rounds_per_turn", default=16)),
    )
    subagents: dict[str, Any] = {}
    if runtime_mode == "primary" and Confirm.ask("Allow this profile to delegate to subagents?", default=True):
        output.print(
            "[dim]An empty subagent allowlist permits any locally available profile, still bounded "
            "by the caps below and the parent profile's authority.[/dim]"
        )
        allowed_profiles = _csv(
            Prompt.ask("Allowed subagent profiles (comma-separated, blank for any)", default="")
        )
        if allowed_profiles:
            subagents["allow"] = allowed_profiles
        subagents.update(
            {
                "max_subagents": IntPrompt.ask(
                    "Maximum subagents", default=int(getattr(config, "max_subagents", 3))
                ),
                "max_parallel": IntPrompt.ask(
                    "Maximum parallel subagents",
                    default=int(getattr(config, "max_parallel_subagents", 2)),
                ),
                "max_depth": IntPrompt.ask(
                    "Maximum delegation depth",
                    default=int(config.get("agent_profiles", "max_delegation_depth", default=3)),
                ),
            }
        )
    else:
        subagents = {"max_subagents": 0, "max_parallel": 0, "max_depth": 0}

    explain_field(
        output,
        "Profile-state budget",
        "Caps durable profile-specific context injected into prompts. Project facts remain in MagGraph.",
    )
    max_state_tokens = IntPrompt.ask(
        "Maximum profile-state context tokens",
        default=int(config.get("agent_profiles", "max_state_tokens", default=1200)),
    )
    explain_options(
        output,
        "Profile state writeback",
        [
            ("off", "Never create profile-state updates."),
            ("propose", "Queue learned profile changes for human review. Recommended."),
            ("auto", "Request automatic writeback where harness policy permits it."),
        ],
        note="MagAgent's global writeback policy remains the ceiling; sensitive changes remain reviewable.",
    )
    writeback = Prompt.ask(
        "Profile state writeback", choices=["off", "propose", "auto"], default="propose"
    )
    lifecycle: dict[str, Any] = {"writeback": writeback}
    output.print(
        "[dim]Lifecycle hooks reference names already defined in .magent/hooks.toml. Profiles never "
        "embed shell commands directly.[/dim]"
    )
    if Confirm.ask("Configure named lifecycle hooks?", default=False):
        on_start = Prompt.ask("on_start hook name (optional)", default="").strip()
        on_end = Prompt.ask("on_end hook name (optional)", default="").strip()
        if on_start:
            lifecycle["on_start"] = on_start
        if on_end:
            lifecycle["on_end"] = on_end

    tools: dict[str, Any] = {"allow": tool_allow, "deny": tool_deny}
    if selected_mcp is not None:
        tools["mcp_servers"] = selected_mcp
    if selected_skills is not None:
        tools["skills"] = selected_skills
    role = {
        "instructions": instructions,
        "persona": persona,
        "objectives": objectives,
        "constraints": constraints,
        "examples": examples,
    }
    memory = {
        "mode": memory_mode,
        "stores": [
            {"name": "profile-state", "kind": "oap-state", "mode": memory_mode},
            {"name": "user-graph", "kind": "maggraph", "mode": memory_mode},
        ],
    }
    document = build_profile_document(
        name=name,
        description=description,
        role=role,
        model=model_config,
        tools=tools,
        permissions={"default": permission_mode, "network": network_access},
        runtime={"mode": runtime_mode, "max_turns": max(1, max_turns), "subagents": subagents},
        memory=memory,
        context={"budget": {"max_state_tokens": max(0, max_state_tokens)}},
        lifecycle=lifecycle,
        extends=extends,
        annotations=annotations,
    )

    output.print(
        Panel(
            f"Name: {document['metadata']['name']}\nScope: {scope}\n"
            f"Provider/model: {model_config.get('provider', 'inherit')} / "
            f"{model_config.get('id', 'inherit')}\nPermissions: {permission_mode}\n"
            f"Tools: {tool_policy}\nNetwork: {network_access}\n"
            f"Memory: {memory_mode}\nRuntime: {runtime_mode}",
            title="Profile Summary",
        )
    )
    if not Confirm.ask("Write this profile?", default=True):
        return {"ok": False, "cancelled": True}
    target = root if scope != "user" else project
    result = write_profile(document, scope=scope, project=target)
    if (
        not result.get("ok")
        and "already exists" in str(result.get("error", ""))
        and Confirm.ask("That profile already exists. Replace it?", default=False)
    ):
        result = write_profile(document, scope=scope, project=target, overwrite=True)
    if not result.get("ok"):
        return result
    output.print(
        "[dim]The default profile supplies personality and bounded capabilities to ordinary REPL "
        "and ask sessions. --agent NAME still overrides it for one run.[/dim]"
    )
    result["make_default"] = Confirm.ask("Make this the default profile?", default=True)
    return result
