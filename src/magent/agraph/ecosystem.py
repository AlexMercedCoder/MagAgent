"""Export MagAgent's AGS assets as an installable plugin pack."""

from __future__ import annotations

import shutil
from pathlib import Path

from magent.agraph.constants import CONFORMANCE_LEVEL, SUPPORTED_FEATURES


def export_plugin_pack(output: str | Path) -> dict[str, str]:
    root = Path(output).expanduser().resolve()
    skill_source = Path(__file__).resolve().parent.parent / "builtin_skills" / "agentic-graphs"
    schema_source = Path(__file__).resolve().parent / "schema"
    skill_target = root / "skills" / "agentic-graphs"
    schema_target = root / "schemas"
    skill_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(skill_source, skill_target, dirs_exist_ok=True)
    shutil.copytree(schema_source, schema_target, dirs_exist_ok=True)
    features = ", ".join(f'"{item}"' for item in SUPPORTED_FEATURES)
    manifest = f'''[plugin]
api_version = "1"
name = "magent-agentic-graphs"
version = "1.0.0"
description = "AGS 1.0 authoring skill and canonical schemas from MagAgent."
capabilities = ["skills", "agentic_graph", "schemas"]
compatibility = ["magent>=0.35.0", "ags=1.0"]
permissions = []
trust = "reviewed"

[agentic_graph]
conformance_level = {CONFORMANCE_LEVEL}
supported_features = [{features}]
'''
    manifest_path = root / "magent-plugin.toml"
    manifest_path.write_text(manifest, encoding="utf-8")
    return {"root": str(root), "manifest": str(manifest_path)}
