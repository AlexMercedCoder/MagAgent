"""Typer app and command-group composition for MagAgent."""

from __future__ import annotations

import typer

app = typer.Typer(
    name="magent",
    help=(
        "MagAgent — CLI AI coding agent powered by MagGraph persistent memory.\n\n"
        "[bold]Start here:[/bold] `magent configure`, `magent tutorial`, `magent doctor`, "
        "`magent ask \"task\"`, or just run `magent` for an interactive session."
    ),
    epilog=(
        "Common first moves:\n"
        "  magent configure                  Set up user, provider, model, and memory\n"
        "  magent tutorial                   Learn the workflow\n"
        "  magent doctor                     Check setup health\n"
        "  magent ask \"fix the failing test\"  Run one task\n"
        "  magent plan --save \"ship fix\"     Save a reusable plan\n"
        "  magent next                       Get context-aware next actions"
    ),
    no_args_is_help=False,
    rich_markup_mode="rich",
)

user_app = typer.Typer(help="Manage user profiles", name="user")
memory_app = typer.Typer(help="Inspect and manage memory graph", name="memory")
memory_semantic_app = typer.Typer(help="Semantic memory sidecar", name="semantic")
gateway_app = typer.Typer(help="Remote gateway (Slack / Discord / Telegram)", name="gateway")
mcp_app = typer.Typer(help="Manage MCP (Model Context Protocol) servers", name="mcp")
task_app = typer.Typer(help="Persistent task ledger", name="task")
artifact_app = typer.Typer(help="Track generated artifacts", name="artifact")
agent_app = typer.Typer(help="Project and user agent definitions", name="agent")
project_app = typer.Typer(help="Project profiles and routines", name="project")
inbox_app = typer.Typer(help="Local command/task inbox", name="inbox")
routine_app = typer.Typer(help="Recurring routine registry", name="routine")
followup_app = typer.Typer(help="Follow-up reminders registry", name="followup")
knowledge_app = typer.Typer(help="Personal knowledge commands", name="knowledge")
api_app = typer.Typer(help="API workflow bookmarks", name="api")
patch_app = typer.Typer(help="Patch queue", name="patch")
session_app = typer.Typer(help="Session timeline and replay", name="session")
data_app = typer.Typer(help="Data workspace helpers", name="data")
policy_app = typer.Typer(help="Policy profiles", name="policy")
docs_app = typer.Typer(help="Built-in MagAgent documentation", name="docs")
events_app = typer.Typer(help="Workbench event log", name="events")
checkpoint_app = typer.Typer(help="File write checkpoints", name="checkpoint")
code_app = typer.Typer(help="Code intelligence index", name="code")
test_app = typer.Typer(help="Test intelligence helpers", name="test")
workspace_app = typer.Typer(help="Workspace status and cleanup reports", name="workspace")
release_app = typer.Typer(help="Release checks and notes", name="release")
context_app = typer.Typer(help="Current project context map", name="context")
config_app = typer.Typer(help="Inspect, backup, diff, and restore MagAgent config", name="config")
recipe_app = typer.Typer(help="Reusable workflow recipes", name="recipe")
tools_app = typer.Typer(help="Tool capability packs", name="tools")
eval_app = typer.Typer(help="Local benchmark/eval suites", name="eval")
github_app = typer.Typer(help="GitHub PR and issue workflows", name="github")
browser_app = typer.Typer(help="Browser automation helpers", name="browser")
cache_app = typer.Typer(help="Prompt cache diagnostics", name="cache")
hook_app = typer.Typer(help="Project workflow hooks", name="hook")
lsp_app = typer.Typer(help="LSP-backed code intelligence", name="lsp")
daemon_app = typer.Typer(help="Background worker queue", name="daemon")
plugin_app = typer.Typer(help="Installable extension packs", name="plugin")
provider_app = typer.Typer(help="Provider setup and diagnostics", name="provider")
model_app = typer.Typer(help="Model role configuration", name="model")
auth_app = typer.Typer(help="Credential storage and keyring helpers", name="auth")
subagent_app = typer.Typer(help="Sub-agent configuration and runs", name="subagent")
skill_app = typer.Typer(help="Browse and inspect local skills", name="skill")
profile_app = typer.Typer(help="Guided UX configuration profiles", name="profile")
permission_app = typer.Typer(help="Permission profile UX", name="permission")
performance_app = typer.Typer(help="Local performance diagnostics", name="performance")
workbench_app = typer.Typer(help="Workbench storage maintenance", name="workbench")
system_app = typer.Typer(help="Machine-readable system and desktop integration info", name="system")

app.add_typer(user_app, name="user", rich_help_panel="Setup & Configuration")
app.add_typer(memory_app, name="memory", rich_help_panel="Memory & Context")
memory_app.add_typer(memory_semantic_app, name="semantic")
app.add_typer(gateway_app, name="gateway", rich_help_panel="Integrations")
app.add_typer(mcp_app, name="mcp", rich_help_panel="Integrations")

_HELP_PANELS = {
    "task": "Workbench & Productivity",
    "artifact": "Workbench & Productivity",
    "agent": "Agents & Automation",
    "project": "Project Workflow",
    "inbox": "Workbench & Productivity",
    "routine": "Workbench & Productivity",
    "followup": "Workbench & Productivity",
    "knowledge": "Memory & Context",
    "api": "Workbench & Productivity",
    "patch": "Planning, Review & Release",
    "session": "Memory & Context",
    "data": "Data & Local UI",
    "policy": "Setup & Configuration",
    "docs": "Help & Learning",
    "events": "Workbench & Productivity",
    "checkpoint": "Project Workflow",
    "code": "Code Intelligence & Testing",
    "test": "Code Intelligence & Testing",
    "workspace": "Project Workflow",
    "release": "Planning, Review & Release",
    "context": "Memory & Context",
    "config": "Setup & Configuration",
    "recipe": "Agents & Automation",
    "tools": "Setup & Configuration",
    "eval": "Code Intelligence & Testing",
    "github": "Integrations",
    "browser": "Integrations",
    "cache": "Performance & Diagnostics",
    "hook": "Agents & Automation",
    "lsp": "Code Intelligence & Testing",
    "daemon": "Agents & Automation",
    "plugin": "Agents & Automation",
    "provider": "Setup & Configuration",
    "model": "Setup & Configuration",
    "auth": "Setup & Configuration",
    "subagent": "Agents & Automation",
    "skill": "Agents & Automation",
    "profile": "Setup & Configuration",
    "permission": "Setup & Configuration",
    "performance": "Performance & Diagnostics",
    "workbench": "Workbench & Productivity",
    "system": "Performance & Diagnostics",
}

for _name, _typer in [
    ("task", task_app),
    ("artifact", artifact_app),
    ("agent", agent_app),
    ("project", project_app),
    ("inbox", inbox_app),
    ("routine", routine_app),
    ("followup", followup_app),
    ("knowledge", knowledge_app),
    ("api", api_app),
    ("patch", patch_app),
    ("session", session_app),
    ("data", data_app),
    ("policy", policy_app),
    ("docs", docs_app),
    ("events", events_app),
    ("checkpoint", checkpoint_app),
    ("code", code_app),
    ("test", test_app),
    ("workspace", workspace_app),
    ("release", release_app),
    ("context", context_app),
    ("config", config_app),
    ("recipe", recipe_app),
    ("tools", tools_app),
    ("eval", eval_app),
    ("github", github_app),
    ("browser", browser_app),
    ("cache", cache_app),
    ("hook", hook_app),
    ("lsp", lsp_app),
    ("daemon", daemon_app),
    ("plugin", plugin_app),
    ("provider", provider_app),
    ("model", model_app),
    ("auth", auth_app),
    ("subagent", subagent_app),
    ("skill", skill_app),
    ("profile", profile_app),
    ("permission", permission_app),
    ("performance", performance_app),
    ("workbench", workbench_app),
    ("system", system_app),
]:
    app.add_typer(_typer, name=_name, rich_help_panel=_HELP_PANELS.get(_name, "Advanced"))

__all__ = [
    "api_app",
    "app",
    "agent_app",
    "auth_app",
    "artifact_app",
    "checkpoint_app",
    "browser_app",
    "cache_app",
    "code_app",
    "context_app",
    "config_app",
    "data_app",
    "daemon_app",
    "docs_app",
    "events_app",
    "followup_app",
    "gateway_app",
    "eval_app",
    "github_app",
    "hook_app",
    "inbox_app",
    "knowledge_app",
    "mcp_app",
    "memory_app",
    "memory_semantic_app",
    "lsp_app",
    "patch_app",
    "policy_app",
    "plugin_app",
    "provider_app",
    "profile_app",
    "permission_app",
    "performance_app",
    "project_app",
    "release_app",
    "recipe_app",
    "routine_app",
    "session_app",
    "task_app",
    "test_app",
    "tools_app",
    "model_app",
    "subagent_app",
    "skill_app",
    "user_app",
    "workspace_app",
    "workbench_app",
    "system_app",
]
