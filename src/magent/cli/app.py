"""Typer app and command-group composition for MagAgent."""

from __future__ import annotations

import typer

app = typer.Typer(
    name="magent",
    help="MagAgent — CLI AI coding agent powered by MagGraph persistent memory",
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
provider_app = typer.Typer(help="Provider setup and diagnostics", name="provider")
model_app = typer.Typer(help="Model role configuration", name="model")
subagent_app = typer.Typer(help="Sub-agent configuration and runs", name="subagent")
profile_app = typer.Typer(help="Guided UX configuration profiles", name="profile")

app.add_typer(user_app, name="user")
app.add_typer(memory_app, name="memory")
memory_app.add_typer(memory_semantic_app, name="semantic")
app.add_typer(gateway_app, name="gateway")
app.add_typer(mcp_app, name="mcp")

for _name, _typer in [
    ("task", task_app),
    ("artifact", artifact_app),
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
    ("provider", provider_app),
    ("model", model_app),
    ("subagent", subagent_app),
    ("profile", profile_app),
]:
    app.add_typer(_typer, name=_name)

__all__ = [
    "api_app",
    "app",
    "artifact_app",
    "checkpoint_app",
    "browser_app",
    "code_app",
    "context_app",
    "config_app",
    "data_app",
    "docs_app",
    "followup_app",
    "gateway_app",
    "eval_app",
    "github_app",
    "inbox_app",
    "knowledge_app",
    "mcp_app",
    "memory_app",
    "memory_semantic_app",
    "patch_app",
    "policy_app",
    "provider_app",
    "profile_app",
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
    "user_app",
    "workspace_app",
]
