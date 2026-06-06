"""Action handlers shared by the local UI and tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from magent.config import user_memory_dir
from magent.memory import MemoryManager
from magent.memory_inbox import accept_candidate, memory_inbox
from magent.workbench_domains.checkpoints import checkpoint_diff
from magent.workbench_domains.patches import patch_preview
from magent.workbench_domains.release import release_check


def run_release_check(store: Any, project: str | Path = ".") -> dict[str, Any]:
    """Run the domain release check for the local UI."""
    return release_check(store, project)


def promote_memory_candidate(store: Any, username: str, candidate_id: str, project: str | Path = ".") -> dict[str, Any]:
    """Accept a memory candidate from the UI."""
    manager = MemoryManager(user_memory_dir(username), username=username)
    return accept_candidate(store, manager, candidate_id, project)


def list_memory_inbox(store: Any, project: str | Path = ".") -> dict[str, Any]:
    """List UI-visible memory inbox candidates."""
    return memory_inbox(store, project)


def inspect_patch(store: Any, patch_id: str) -> dict[str, Any]:
    """Preview a saved patch for UI inspection."""
    return patch_preview(store, patch_id)


def inspect_checkpoint_diff(store: Any, checkpoint_id: str) -> dict[str, Any]:
    """Show a checkpoint diff for UI inspection."""
    return checkpoint_diff(store, checkpoint_id)
