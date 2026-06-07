"""Local operations dashboard for MagAgent."""

from __future__ import annotations

import json
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from magent.docs import list_topics, read_topic, search_docs
from magent.model_health import model_health_report
from magent.readiness import readiness_report
from magent.ui_actions import (
    inspect_checkpoint_diff,
    inspect_patch,
    list_memory_inbox,
    promote_memory_candidate,
    run_release_check,
)
from magent.workbench import (
    WorkbenchStore,
    checkpoint_sessions,
    command_history,
    list_plans,
    project_doctor,
    usage_stats,
    workspace_clean_report,
    workspace_status,
)
from magent.workbench_cockpit import cockpit_state


def ui_state(store: WorkbenchStore, project: str | Path = ".", username: str | None = None) -> dict[str, Any]:
    root = Path(project).resolve()
    memory_quality = {"ok": False, "error": "username unavailable"}
    if username:
        try:
            from magent.config import user_memory_dir
            from magent.memory import MemoryManager

            memory_quality = MemoryManager(user_memory_dir(username), username=username).quality_report()
        except Exception as e:
            memory_quality = {"ok": False, "error": str(e)}
    workspace = workspace_status(store, root)
    clean_report = workspace_clean_report(store, root, status=workspace)
    doctor = project_doctor(root, store)
    readiness = None
    model_health = model_health_report(store)
    if username:
        try:
            from magent.config import load_config

            readiness = readiness_report(username, load_config(username), store, project=root)
        except Exception as e:
            readiness = {"ok": False, "error": str(e)}
    return {
        "ok": True,
        "project": str(root),
        "workspace": workspace,
        "clean_report": clean_report,
        "project_doctor": doctor,
        "tasks": store.read("tasks", []),
        "plans": list_plans(store),
        "patches": store.read("patches", []),
        "reviews": store.read("reviews", []),
        "checkpoints": checkpoint_sessions(store),
        "command_history": command_history(store, root)[:20],
        "memory_quality": memory_quality,
        "model_health": model_health,
        "readiness": readiness,
        "usage": usage_stats(),
        "cockpit": cockpit_state(
            store,
            root,
            workspace=workspace,
            clean_report=clean_report,
            project_doctor_result=doctor,
        ),
        "docs": [{"slug": topic.slug, "title": topic.title} for topic in list_topics()],
    }


def render_ui_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MagAgent UI</title>
<style>
:root{color-scheme:light dark;font-family:Inter,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
body{margin:0;background:#f6f7f9;color:#171923}
header{background:#1f2937;color:#fff;padding:18px 24px}
main{padding:20px;display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}
section{background:#fff;border:1px solid #d8dde6;border-radius:8px;padding:16px;box-shadow:0 1px 2px #0001}
h1{margin:0;font-size:22px} h2{margin:0 0 12px;font-size:16px}
button{border:1px solid #9aa4b2;background:#fff;border-radius:6px;padding:7px 10px;cursor:pointer}
pre{white-space:pre-wrap;word-break:break-word;background:#f1f3f6;border-radius:6px;padding:10px;max-height:320px;overflow:auto}
.row{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0}.metric{font-size:28px;font-weight:700}.muted{color:#667085}
@media (prefers-color-scheme:dark){body{background:#111827;color:#e5e7eb}section{background:#1f2937;border-color:#374151}button{background:#111827;color:#e5e7eb;border-color:#4b5563}pre{background:#111827}.muted{color:#9ca3af}}
</style>
</head>
<body>
<header><h1>MagAgent UI</h1><div id="project" class="muted"></div></header>
<main>
<section><h2>Workspace</h2><div class="row"><button onclick="refresh()">Refresh</button><button onclick="loadReleaseCheck()">Release Check</button><button onclick="loadReadiness()">Readiness</button></div><pre id="workspace">Loading...</pre></section>
<section><h2>Cockpit</h2><div class="row"><button onclick="loadCockpit()">Refresh Cockpit</button></div><pre id="cockpit">Loading...</pre></section>
<section><h2>Model Health</h2><div class="row"><input id="smokeProvider" placeholder="Provider"><input id="smokeModel" placeholder="Model"><button onclick="loadModelHealth()">Health</button><button onclick="runProviderSmoke()">Smoke</button></div><pre id="modelHealth">Loading...</pre></section>
<section><h2>Plans</h2><div class="metric" id="planCount">0</div><pre id="plans"></pre></section>
<section><h2>Patches</h2><div class="metric" id="patchCount">0</div><div class="row"><input id="patchId" placeholder="Patch ID"><button onclick="inspectPatch()">Inspect</button></div><pre id="patches"></pre></section>
<section><h2>Checkpoints</h2><div class="metric" id="checkpointCount">0</div><div class="row"><input id="checkpointId" placeholder="Checkpoint ID"><button onclick="inspectCheckpoint()">Diff</button></div><pre id="checkpoints"></pre></section>
<section><h2>Project Doctor</h2><pre id="doctor"></pre></section>
<section><h2>Memory Inbox</h2><div class="row"><input id="memoryId" placeholder="Candidate ID"><button onclick="loadMemoryInbox()">Inbox</button><button onclick="promoteMemory()">Promote</button></div><pre id="memory"></pre></section>
<section><h2>Command History</h2><pre id="commands"></pre></section>
<section><h2>Docs</h2><div class="row"><input id="docQuery" placeholder="Search docs"><button onclick="searchDocs()">Search</button></div><pre id="docs"></pre></section>
</main>
<script>
async function getJson(path){const r=await fetch(path);return await r.json()}
function show(id,data){document.getElementById(id).textContent=JSON.stringify(data,null,2)}
async function refresh(){
 const data=await getJson('/api/state');
 document.getElementById('project').textContent=data.project;
 show('workspace',data.workspace); show('plans',data.plans); show('patches',data.patches);
 show('cockpit',data.cockpit);
 show('modelHealth',data.model_health);
 show('checkpoints',data.checkpoints); show('doctor',data.project_doctor); show('memory',data.memory_quality);
 show('commands',data.command_history); show('docs',data.docs);
 document.getElementById('planCount').textContent=data.plans.length;
 document.getElementById('patchCount').textContent=data.patches.length;
 document.getElementById('checkpointCount').textContent=data.checkpoints.length;
}
async function searchDocs(){const q=encodeURIComponent(document.getElementById('docQuery').value);show('docs',await getJson('/api/docs/search?q='+q))}
async function loadReleaseCheck(){show('workspace',await getJson('/api/release/check'))}
async function loadReadiness(){show('workspace',await getJson('/api/readiness'))}
async function loadCockpit(){show('cockpit',await getJson('/api/cockpit'))}
async function loadModelHealth(){show('modelHealth',await getJson('/api/model/health'))}
async function runProviderSmoke(){const p=encodeURIComponent(document.getElementById('smokeProvider').value);const m=encodeURIComponent(document.getElementById('smokeModel').value);show('modelHealth',await getJson('/api/provider/smoke?provider='+p+'&model='+m))}
async function loadMemoryInbox(){show('memory',await getJson('/api/memory/inbox'))}
async function promoteMemory(){const id=encodeURIComponent(document.getElementById('memoryId').value);show('memory',await getJson('/api/memory/promote?id='+id))}
async function inspectPatch(){const id=encodeURIComponent(document.getElementById('patchId').value);show('patches',await getJson('/api/patch/preview?id='+id))}
async function inspectCheckpoint(){const id=encodeURIComponent(document.getElementById('checkpointId').value);show('checkpoints',await getJson('/api/checkpoint/diff?id='+id))}
refresh()
</script>
</body>
</html>
"""


def serve_ui(
    store: WorkbenchStore,
    project: str | Path = ".",
    username: str | None = None,
    port: int = 7830,
    open_browser: bool = False,
) -> dict[str, Any]:
    root = Path(project).resolve()

    class Handler(BaseHTTPRequestHandler):
        def _json(self, data: Any, status: int = 200) -> None:
            payload = json.dumps(data, default=str).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(parsed.query)
            try:
                if parsed.path == "/":
                    payload = render_ui_html().encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                elif parsed.path == "/api/state":
                    self._json(ui_state(store, root, username=username))
                elif parsed.path == "/api/cockpit":
                    self._json(cockpit_state(store, root))
                elif parsed.path == "/api/docs/search":
                    self._json(search_docs(query.get("q", [""])[0]))
                elif parsed.path == "/api/docs/topic":
                    self._json({"ok": True, "topic": query.get("slug", [""])[0], "content": read_topic(query.get("slug", [""])[0])})
                elif parsed.path == "/api/release/check":
                    self._json(run_release_check(store, root))
                elif parsed.path == "/api/readiness":
                    if not username:
                        self._json({"ok": False, "error": "username unavailable"}, status=400)
                    else:
                        from magent.config import load_config

                        self._json(readiness_report(username, load_config(username), store, project=root))
                elif parsed.path == "/api/model/health":
                    self._json(model_health_report(store))
                elif parsed.path == "/api/provider/smoke":
                    if not username:
                        self._json({"ok": False, "error": "username unavailable"}, status=400)
                    else:
                        from magent.config import load_config
                        from magent.provider_smoke import run_provider_tool_smoke

                        provider_id = query.get("provider", [""])[0]
                        model = query.get("model", [""])[0] or None
                        if not provider_id:
                            self._json({"ok": False, "error": "provider is required"}, status=400)
                        else:
                            self._json(
                                run_provider_tool_smoke(
                                    username,
                                    load_config(username),
                                    store,
                                    provider_id,
                                    model=model,
                                    project=root / ".magent" / "ui-smoke",
                                    timeout_seconds=90,
                                )
                            )
                elif parsed.path == "/api/release/notes":
                    from magent.workbench import release_notes

                    self._json(release_notes(root))
                elif parsed.path == "/api/memory/inbox":
                    self._json(list_memory_inbox(store, root))
                elif parsed.path == "/api/memory/promote":
                    candidate_id = query.get("id", [""])[0]
                    if not username:
                        self._json({"ok": False, "error": "username unavailable"}, status=400)
                    else:
                        self._json(promote_memory_candidate(store, username, candidate_id, root))
                elif parsed.path == "/api/patch/preview":
                    self._json(inspect_patch(store, query.get("id", [""])[0]))
                elif parsed.path == "/api/checkpoint/diff":
                    self._json(inspect_checkpoint_diff(store, query.get("id", [""])[0]))
                else:
                    self._json({"ok": False, "error": "not found"}, status=404)
            except Exception as e:
                self._json({"ok": False, "error": str(e)}, status=500)

        def log_message(self, format: str, *args: Any) -> None:
            return None

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}/"
    if open_browser:
        webbrowser.open(url)
    return {"ok": True, "url": url, "project": str(root)}
