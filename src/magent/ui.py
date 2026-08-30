"""Local operations dashboard for MagAgent."""

from __future__ import annotations

import asyncio
import json
import mimetypes
import secrets
import threading
import urllib.parse
import webbrowser
from collections.abc import Callable
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
from magent.web_conversations import ConversationStore, folder_catalog
from magent.web_graphs import (
    GraphDraftManager,
    GraphRunManager,
    blank_graph_document,
    generate_web_graph,
    graph_catalog,
    preview_web_graph,
    read_web_graph,
    save_web_graph,
    web_task_node,
)
from magent.web_runs import STREAM_WAIT_SECONDS, TERMINAL_STATES, RunCancelled, RunStore
from magent.web_schedules import ScheduleStore
from magent.web_workspace import WorkspaceError, WorkspaceService, extension_inventory
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

WEBUI_DIR = Path(__file__).with_name("webui")
# Vite writes the built bundle here. It is committed and ships inside the
# wheel, so installed users never need Node.
STATIC_DIR = WEBUI_DIR / "static"
MAX_REQUEST_BYTES = 8 * 1024 * 1024


def _turn_worker(
    conversations: Any,
    conversation: dict[str, Any],
    prompt: str,
    *,
    username: str,
    root: Path,
    release: Callable[[], None],
    context_refs: list[dict[str, Any]] | None = None,
) -> Callable[[Any], None]:
    """Build the body of a chat run.

    Every message is written from inside the run, not from the request handler,
    so a reply survives the browser that asked for it going away.
    """
    conversation_id = str(conversation.get("id") or "")

    def work(run: Any) -> None:
        from magent.web_chat import WebChatRunner

        # Kept so a cancelled turn can save what it had already said. Watching
        # text appear and then vanish is worse than an incomplete answer.
        partial: dict[str, list[str]] = {"speaker": [], "text": []}

        def chunk(speaker: str, text: str) -> None:
            partial["speaker"] = [speaker]
            partial["text"].append(text)
            run.append({"type": "chunk", "speaker": speaker, "content": text})

        try:
            results = WebChatRunner(
                username,
                root,
                on_approval=lambda description, tier: run.request_approval(description, int(tier)),
                permission_mode=str(conversation.get("permission_mode") or "balanced"),
            ).run(
                conversation,
                prompt,
                on_chunk=chunk,
                should_continue=run.raise_if_cancelled,
            )
            for result in results:
                conversations.append_message(
                    conversation_id,
                    role="assistant",
                    content=result["content"],
                    speaker=result["speaker"],
                    metadata={
                        **{key: value for key, value in result.items() if key != "content"},
                        "context": list(context_refs or []),
                    },
                )
            run.append({"type": "done", "conversation": conversations.get(conversation_id)})
        except RunCancelled:
            # A cancelled turn still leaves a trace in the transcript, or the
            # conversation shows a question with no visible outcome. Whatever
            # was already said is kept: it was on screen, and dropping it makes
            # cancelling look like it erased the answer.
            said = "".join(partial["text"]).strip()
            conversations.append_message(
                conversation_id,
                role="assistant",
                content=f"{said}\n\n_(cancelled)_" if said else "This turn was cancelled.",
                speaker=(partial["speaker"] or ["MagAgent"])[0],
                status="cancelled",
            )
            run.append({"type": "conversation", "conversation": conversations.get(conversation_id)})
            raise
        except Exception as problem:
            # A raw repr in a chat bubble tells the user nothing they can act
            # on; name the state and the recovery step.
            from magent.webui_errors import describe

            friendly = describe(problem)
            conversations.append_message(
                conversation_id,
                role="assistant",
                content=friendly.as_message(),
                speaker="MagAgent",
                status="error",
                metadata={"error_kind": friendly.kind, "detail": friendly.detail},
            )
            run.append({"type": "conversation", "conversation": conversations.get(conversation_id)})
            raise
        finally:
            release()

    return work


def _int_or(raw: str, fallback: int) -> int:
    """A junk query parameter is a bad value, not a server fault."""
    try:
        return int(raw)
    except (TypeError, ValueError):
        return fallback


def ui_state(
    store: WorkbenchStore, project: str | Path = ".", username: str | None = None
) -> dict[str, Any]:
    root = Path(project).resolve()
    memory_quality = {"ok": False, "error": "username unavailable"}
    if username:
        try:
            from magent.config import user_memory_dir
            from magent.memory import MemoryManager

            memory_quality = MemoryManager(
                user_memory_dir(username), username=username
            ).quality_report()
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


def render_ui_html(token: str = "") -> str:
    """Return the packaged shell. ``token`` remains a compatibility argument."""
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


def serve_ui(
    store: WorkbenchStore,
    project: str | Path = ".",
    username: str | None = None,
    port: int = 7830,
    open_browser: bool = False,
) -> dict[str, Any]:
    """Serve the local ops UI.

    Binding to loopback is not access control: any web page the user visits can
    fire `<img src="http://127.0.0.1:7830/api/memory/promote?id=…">`, and a
    DNS-rebound host can read `/api/state` (project paths, command history).
    So every request must carry a per-launch token and a loopback `Host`, and
    the endpoints that change state are POST-only.
    """
    root = Path(project).resolve()
    token = secrets.token_urlsafe(32)
    conversations = ConversationStore(store)
    conversation_locks: dict[str, threading.Lock] = {}
    runs = RunStore()
    graph_runs = GraphRunManager(store, username, root) if username else None
    graph_drafts = GraphDraftManager(root, username) if username else None
    workspace = WorkspaceService(root)
    schedules = ScheduleStore(store, graph_runs, root) if graph_runs else None
    if schedules:
        schedules.start()

    # Endpoints that mutate state or spend money. GET must not reach these.
    # Paths whose POST mutates state: they demand the CSRF header, and a bare
    # GET is refused so a cross-origin <img> or <link> cannot trigger them.
    mutating_paths = {
        "/api/memory/promote",
        "/api/provider/smoke",
        "/api/release/check",
        "/api/conversations",
        "/api/conversations/update",
        "/api/conversations/delete",
        "/api/conversations/message",
        "/api/profiles",
        "/api/profiles/import",
        "/api/profiles/delete",
        "/api/profiles/clone",
        "/api/profiles/generate",
        "/api/graphs/run",
        "/api/graphs/draft",
        "/api/graphs/draft/start",
        "/api/graphs/draft/cancel",
        "/api/graphs/preview-draft",
        "/api/graphs/save",
        "/api/settings",
        "/api/onboarding/configure",
        "/api/runs/cancel",
        "/api/runs/approve",
        "/api/workspace/upload",
        "/api/workspace/git",
        "/api/workspace/worktrees",
        "/api/workspace/terminal",
        "/api/extensions/plugins",
        "/api/extensions/manage",
        "/api/extensions/mcp/test",
        "/api/memory/nodes",
        "/api/tasks/action",
        "/api/schedules",
        "/api/schedules/action",
    }

    # Dual-purpose paths: POST mutates and still needs CSRF, but GET is a plain
    # read and must be allowed. Only paths with a real GET branch below belong
    # here; /api/profiles and /api/settings are POST-only and must keep
    # refusing GET, or the request would fall into their write handlers.
    readable_paths = {"/api/conversations", "/api/schedules", "/api/workspace/git"}

    class Handler(BaseHTTPRequestHandler):
        def _authorized(self, parsed: urllib.parse.ParseResult) -> bool:
            host = (self.headers.get("Host") or "").split(":")[0]
            if host not in {"127.0.0.1", "localhost", "[::1]", "::1"}:
                return False  # DNS rebinding
            origin = self.headers.get("Origin")
            if origin and urllib.parse.urlparse(origin).hostname not in {
                "127.0.0.1",
                "localhost",
                "::1",
            }:
                return False
            supplied = urllib.parse.parse_qs(parsed.query).get("token", [""])[0]
            if not supplied:
                supplied = (self.headers.get("X-Magent-Token") or "").strip()
            if not supplied:
                cookies = {}
                for pair in (self.headers.get("Cookie") or "").split(";"):
                    key, separator, value = pair.strip().partition("=")
                    if separator:
                        cookies[key] = value
                supplied = cookies.get("magent_ui", "")
            return secrets.compare_digest(supplied, token)

        def _security_headers(self) -> None:
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; style-src 'self'; script-src 'self'; "
                "connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'",
            )

        def _json(self, data: Any, status: int = 200) -> None:
            payload = json.dumps(data, default=str).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self._security_headers()
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _body(self) -> dict[str, Any]:
            raw_length = self.headers.get("Content-Length", "0")
            try:
                length = int(raw_length)
            except ValueError as exc:
                raise ValueError("invalid Content-Length") from exc
            if length < 0 or length > MAX_REQUEST_BYTES:
                raise ValueError("request body is too large")
            if length and "application/json" not in (self.headers.get("Content-Type") or ""):
                raise ValueError("Content-Type must be application/json")
            if not length:
                return {}
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("JSON body must be an object")
            return data

        def _root_asset(self, name: str) -> None:
            self._serve_file(STATIC_DIR / Path(name).name)

        def _asset(self, name: str) -> None:
            self._serve_file(STATIC_DIR / "assets" / Path(name).name)

        def _serve_file(self, path: Path) -> None:
            if not path.is_file():
                self._json({"ok": False, "error": "not found"}, status=404)
                return
            payload = path.read_bytes()
            self.send_response(200)
            self.send_header(
                "Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            )
            self._security_headers()
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _stream_event(self, data: dict[str, Any]) -> None:
            self.wfile.write((json.dumps(data, default=str) + "\n").encode("utf-8"))
            self.wfile.flush()

        def _stream_run(self, run: Any, *, after: int = 0) -> None:
            """Stream a run's event log from a cursor until the run ends.

            Reading from a cursor is what makes reattachment work: a browser
            that reloads mid-turn asks for everything past what it already has
            and gets the missed chunks, rather than a truncated reply.
            """
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self._security_headers()
            self.end_headers()

            cursor = max(0, after)
            # The run id goes first so a client that loses the socket can come
            # back to this exact run instead of guessing.
            self._stream_event({"type": "run", **run.snapshot(), "cursor": cursor})
            while True:
                for event in run.since(cursor):
                    self._stream_event(event)
                    cursor += 1
                if run.state in TERMINAL_STATES and cursor >= run.cursor:
                    break
                # Block on the run rather than polling, so a chunk reaches the
                # browser as soon as it is appended.
                run.wait(cursor, STREAM_WAIT_SECONDS)
            self._stream_event({"type": "run", **run.snapshot(), "cursor": cursor})

        def do_POST(self) -> None:  # noqa: N802
            self._dispatch(method="POST")

        def do_GET(self) -> None:  # noqa: N802
            self._dispatch(method="GET")

        def _dispatch(self, method: str) -> None:
            parsed = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(parsed.query)

            if not self._authorized(parsed):
                self._json({"ok": False, "error": "unauthorized"}, status=403)
                return
            if method == "GET" and parsed.path in mutating_paths - readable_paths:
                self._json({"ok": False, "error": "use POST for this endpoint"}, status=405)
                return
            if method == "POST" and parsed.path in mutating_paths:
                csrf = (self.headers.get("X-Magent-CSRF") or "").strip()
                if not secrets.compare_digest(csrf, token):
                    self._json({"ok": False, "error": "invalid CSRF token"}, status=403)
                    return

            try:
                if parsed.path == "/":
                    payload = render_ui_html(token).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header(
                        "Set-Cookie", f"magent_ui={token}; HttpOnly; SameSite=Strict; Path=/"
                    )
                    self._security_headers()
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                elif parsed.path.startswith("/assets/"):
                    self._asset(parsed.path.removeprefix("/assets/"))
                elif parsed.path == "/theme-init.js":
                    # Sits at the bundle root, not under /assets/, because it
                    # must run before the module bundle parses.
                    self._root_asset("theme-init.js")
                elif parsed.path == "/api/bootstrap":
                    from magent.config import load_config
                    from magent.desktop_api import agent_profiles, config_schema

                    configured_mode = (
                        load_config(username).permission_mode if username else "balanced"
                    )

                    self._json(
                        {
                            "ok": True,
                            "csrf_token": token,
                            "project": str(root),
                            "permission_mode": configured_mode,
                            "conversations": conversations.list(),
                            "profiles": agent_profiles(str(root)),
                            "settings": config_schema(username),
                        }
                    )
                elif parsed.path == "/api/folders":
                    self._json(folder_catalog(query.get("path", [""])[0], project=root))
                elif parsed.path == "/api/workspace/files":
                    self._json(
                        workspace.list_files(
                            query.get("q", [""])[0],
                            _int_or(query.get("limit", ["500"])[0], 500),
                        )
                    )
                elif parsed.path == "/api/workspace/file":
                    self._json(workspace.preview(query.get("path", [""])[0]))
                elif parsed.path == "/api/workspace/diff":
                    self._json(workspace.diff(query.get("staged", ["false"])[0] == "true"))
                elif parsed.path == "/api/workspace/git" and method == "GET":
                    self._json(workspace.git())
                elif parsed.path == "/api/workspace/git":
                    body = self._body()
                    self._json(
                        workspace.git_action(str(body.get("action", "")), str(body.get("path", "")))
                    )
                elif parsed.path == "/api/workspace/upload":
                    body = self._body()
                    self._json(
                        workspace.upload(
                            str(body.get("name", "")),
                            str(body.get("data", "")),
                            str(body.get("conversation_id", "shared")),
                        ),
                        status=201,
                    )
                elif parsed.path == "/api/workspace/terminal":
                    body = self._body()
                    self._json(workspace.terminal(str(body.get("command", ""))))
                elif parsed.path == "/api/workspace/worktrees":
                    body = self._body()
                    action = str(body.get("action", "create"))
                    if action == "remove":
                        self._json(workspace.remove_worktree(str(body.get("directory", ""))))
                    else:
                        self._json(
                            workspace.create_worktree(
                                str(body.get("branch", "")),
                                str(body.get("directory", "")),
                                bool(body.get("create_branch", False)),
                            )
                        )
                elif parsed.path == "/api/extensions":
                    self._json(extension_inventory(username, root))
                elif parsed.path == "/api/extensions/plugins":
                    from magent.plugins import set_plugin_enabled

                    body = self._body()
                    result = set_plugin_enabled(
                        str(body.get("name", "")), bool(body.get("enabled"))
                    )
                    self._json(result, status=200 if result.get("ok") else 400)
                elif parsed.path == "/api/extensions/manage":
                    from magent.web_extensions import manage_mcp, manage_plugin, manage_skill

                    body = self._body()
                    kind = str(body.get("kind") or "")
                    if kind == "plugin":
                        result = manage_plugin(body)
                    elif kind == "skill":
                        result = manage_skill(root, body)
                    elif kind == "mcp":
                        result = manage_mcp(body)
                    else:
                        result = {"ok": False, "error": "Unknown extension type."}
                    self._json(result, status=200 if result.get("ok") else 400)
                elif parsed.path == "/api/extensions/mcp/test":
                    from magent.web_extensions import test_mcp

                    result = test_mcp(self._body())
                    self._json(result, status=200 if result.get("ok") else 400)
                elif parsed.path == "/api/tasks":
                    if not username:
                        self._json({"ok": False, "error": "username unavailable"}, status=400)
                    else:
                        from magent.desktop_api import execution_tasks

                        self._json(
                            execution_tasks(
                                username, limit=_int_or(query.get("limit", ["100"])[0], 100)
                            )
                        )
                elif parsed.path == "/api/tasks/action":
                    if not username:
                        self._json({"ok": False, "error": "username unavailable"}, status=400)
                    else:
                        from magent.desktop_api import execution_task_action

                        body = self._body()
                        result = execution_task_action(
                            username,
                            str(body.get("task_id", "")),
                            str(body.get("action", "")),
                            reason="Requested from the local Web UI",
                        )
                        self._json(result, status=200 if result.get("ok") else 400)
                elif parsed.path == "/api/run-center":
                    graph_data = graph_catalog(store, root)
                    self._json(
                        {
                            "ok": True,
                            "chat_runs": runs.list(),
                            "graph_runs": graph_data.get("runs", []),
                            "schedules": schedules.list().get("schedules", []) if schedules else [],
                        }
                    )
                elif parsed.path == "/api/schedules" and method == "GET":
                    self._json(
                        schedules.list()
                        if schedules
                        else {"ok": False, "error": "username unavailable"}
                    )
                elif parsed.path == "/api/schedules":
                    if schedules is None:
                        self._json({"ok": False, "error": "username unavailable"}, status=400)
                    else:
                        body = self._body()
                        self._json(
                            schedules.create(
                                str(body.get("path", "")),
                                int(body.get("interval_minutes", 60)),
                                params=dict(body.get("params") or {}),
                                approved_gates=list(body.get("approved_gates") or []),
                            ),
                            status=201,
                        )
                elif parsed.path == "/api/schedules/action":
                    if schedules is None:
                        self._json({"ok": False, "error": "username unavailable"}, status=400)
                    else:
                        body = self._body()
                        result = schedules.action(
                            str(body.get("id", "")), str(body.get("action", ""))
                        )
                        self._json(result, status=200 if result.get("ok") else 404)
                elif parsed.path == "/api/conversations" and method == "GET":
                    self._json({"ok": True, "conversations": conversations.list()})
                elif parsed.path == "/api/graphs":
                    self._json(graph_catalog(store, root))
                elif parsed.path == "/api/graphs/draft/status" and method == "GET":
                    if graph_drafts is None:
                        self._json({"ok": False, "error": "username unavailable"}, status=400)
                    else:
                        result = graph_drafts.status(query.get("job_id", [""])[0])
                        self._json(result, status=200 if result.get("ok") else 404)
                elif parsed.path == "/api/graphs/preview":
                    if graph_runs is None:
                        self._json({"ok": False, "error": "username unavailable"}, status=400)
                    else:
                        self._json(graph_runs.preview(query.get("path", [""])[0]))
                elif parsed.path == "/api/graphs/draft/start":
                    if graph_drafts is None:
                        self._json({"ok": False, "error": "username unavailable"}, status=400)
                    else:
                        result = graph_drafts.start(str(self._body().get("goal", "")))
                        self._json(result, status=202 if result.get("ok") else 400)
                elif parsed.path == "/api/graphs/draft/cancel":
                    if graph_drafts is None:
                        self._json({"ok": False, "error": "username unavailable"}, status=400)
                    else:
                        result = graph_drafts.cancel(str(self._body().get("job_id", "")))
                        self._json(result, status=200 if result.get("ok") else 404)
                elif parsed.path == "/api/graphs/draft":
                    if not username:
                        self._json({"ok": False, "error": "username unavailable"}, status=400)
                    else:
                        body = self._body()
                        goal = str(body.get("goal", ""))
                        if body.get("mode") == "ai":
                            self._json(
                                asyncio.run(
                                    generate_web_graph(goal, project=root, username=username)
                                )
                            )
                        else:
                            self._json(
                                {
                                    "ok": True,
                                    "document": blank_graph_document(goal),
                                    "node_template": web_task_node(),
                                }
                            )
                elif parsed.path == "/api/graphs/preview-draft":
                    if not username:
                        self._json({"ok": False, "error": "username unavailable"}, status=400)
                    else:
                        body = self._body()
                        document = body.get("document")
                        if not isinstance(document, dict):
                            self._json(
                                {"ok": False, "error": "document must be an object"}, status=400
                            )
                            return
                        result = preview_web_graph(document, project=root, username=username)
                        self._json(result, status=200 if result.get("ok") else 400)
                elif parsed.path == "/api/graphs/save":
                    if not username:
                        self._json({"ok": False, "error": "username unavailable"}, status=400)
                    else:
                        body = self._body()
                        document = body.get("document")
                        if not isinstance(document, dict):
                            self._json(
                                {"ok": False, "error": "document must be an object"}, status=400
                            )
                            return
                        result = save_web_graph(
                            document,
                            str(body.get("path", "")),
                            project=root,
                            username=username,
                            expected_digest=str(body.get("expected_digest", "")),
                        )
                        self._json(
                            result,
                            status=200
                            if result.get("ok")
                            else (409 if result.get("conflict") else 400),
                        )
                elif parsed.path == "/api/graphs/status":
                    if graph_runs is None:
                        self._json({"ok": False, "error": "username unavailable"}, status=400)
                    else:
                        snapshot = graph_runs.status(query.get("job_id", [""])[0])
                        self._json(
                            snapshot or {"ok": False, "error": "graph run not found"},
                            status=200 if snapshot else 404,
                        )
                elif parsed.path == "/api/graphs/run":
                    if graph_runs is None:
                        self._json({"ok": False, "error": "username unavailable"}, status=400)
                    else:
                        body = self._body()
                        params = body.get("params") or {}
                        if not isinstance(params, dict):
                            self._json(
                                {"ok": False, "error": "params must be an object"}, status=400
                            )
                            return
                        result = graph_runs.start(
                            str(body.get("path", "")),
                            params=params,
                            approved_gates=list(body.get("approved_gates") or []),
                        )
                        self._json(result, status=202)
                elif parsed.path == "/api/conversations" and method == "POST":
                    body = self._body()
                    selected_root = Path(str(body.get("project") or root)).expanduser().resolve()
                    if not selected_root.is_dir():
                        self._json(
                            {"ok": False, "error": "Choose an existing project folder."}, status=400
                        )
                        return
                    record = conversations.create(
                        title=str(body.get("title", "New conversation")),
                        kind=str(body.get("kind", "chat")),
                        project=str(selected_root),
                        profiles=list(body.get("profiles") or []),
                        coordinator=str(body.get("coordinator", "")),
                        permission_mode=str(body.get("permission_mode") or "balanced"),
                    )
                    self._json({"ok": True, "conversation": record}, status=201)
                elif parsed.path == "/api/conversations/update":
                    body = self._body()
                    updates: dict[str, Any] = {}
                    if "title" in body:
                        updates["title"] = body.get("title")
                    if "archived" in body:
                        updates["archived"] = bool(body.get("archived"))
                    if "project" in body:
                        selected_root = Path(str(body.get("project") or "")).expanduser().resolve()
                        if not selected_root.is_dir():
                            self._json(
                                {"ok": False, "error": "Choose an existing project folder."},
                                status=400,
                            )
                            return
                        updates["project"] = str(selected_root)
                    if "permission_mode" in body:
                        updates["permission_mode"] = body.get("permission_mode")
                    record = conversations.update(
                        str(body.get("conversation_id", "")),
                        **updates,
                    )
                    self._json({"ok": True, "conversation": record})
                elif parsed.path == "/api/conversations/delete":
                    body = self._body()
                    conversation_id = str(body.get("conversation_id", ""))
                    removed = conversations.delete(conversation_id)
                    conversation_locks.pop(conversation_id, None)
                    self._json(
                        {
                            "ok": removed,
                            "conversation_id": conversation_id,
                            **({} if removed else {"error": "conversation not found"}),
                        },
                        status=200 if removed else 404,
                    )
                elif parsed.path == "/api/conversations/message":
                    if not username:
                        self._json({"ok": False, "error": "username unavailable"}, status=400)
                        return
                    body = self._body()
                    conversation_id = str(body.get("conversation_id", ""))
                    content = str(body.get("content", "")).strip()
                    if not content or len(content) > 32000:
                        self._json(
                            {"ok": False, "error": "message must contain 1 to 32000 characters"},
                            status=400,
                        )
                        return
                    conversation = conversations.get(conversation_id)
                    if conversation is None:
                        self._json({"ok": False, "error": "conversation not found"}, status=404)
                        return
                    turn_lock = conversation_locks.setdefault(conversation_id, threading.Lock())
                    if not turn_lock.acquire(blocking=False):
                        self._json(
                            {
                                "ok": False,
                                "error": "a turn is already running for this conversation",
                            },
                            status=409,
                        )
                        return
                    conversation_root = Path(str(conversation.get("project") or root)).resolve()
                    if not conversation_root.is_dir():
                        self._json(
                            {
                                "ok": False,
                                "error": "This conversation's project folder no longer exists. Edit the conversation and choose an existing folder.",
                            },
                            status=400,
                        )
                        return
                    conversation_workspace = WorkspaceService(conversation_root)
                    context_prompt, context_refs = conversation_workspace.context_prompt(
                        body.get("context") or []
                    )
                    conversations.append_message(
                        conversation_id,
                        role="user",
                        content=content,
                        speaker="You",
                        metadata={"context": context_refs},
                    )
                    conversation = conversations.get(conversation_id) or conversation

                    # The turn runs on its own thread and records its reply
                    # whether or not anyone is watching. Closing the tab used to
                    # kill the work with the socket, leaving the conversation
                    # holding a question that never got an answer.
                    run = runs.start(
                        conversation_id,
                        _turn_worker(
                            conversations,
                            conversation,
                            content + context_prompt,
                            username=username,
                            root=conversation_root,
                            release=turn_lock.release,
                            context_refs=context_refs,
                        ),
                    )
                    self._stream_run(run, after=0)
                elif parsed.path == "/api/profile":
                    from magent.agent_profiles.desktop import inspect_profile
                    from magent.config import load_config

                    config = load_config(username) if username else None
                    self._json(
                        inspect_profile(query.get("name", [""])[0], project=root, config=config)
                    )
                elif parsed.path == "/api/profiles/contract":
                    from magent.agent_profiles.desktop import profile_contract
                    from magent.config import load_config

                    self._json(
                        profile_contract(
                            project=root,
                            config=load_config(username) if username else None,
                        )
                    )
                elif parsed.path == "/api/profiles/export":
                    from magent.config import load_config
                    from magent.web_profiles import export_document

                    config = load_config(username) if username else None
                    self._json(
                        export_document(query.get("name", [""])[0], project=root, config=config)
                    )
                elif parsed.path == "/api/onboarding/readiness":
                    from magent.web_onboarding import readiness

                    self._json(readiness())
                elif parsed.path == "/api/onboarding/providers":
                    from magent.web_onboarding import providers as onboarding_providers

                    self._json(onboarding_providers())
                elif parsed.path == "/api/graphs/document":
                    # The raw document, for editing on the board or exporting.
                    self._json(read_web_graph(query.get("path", [""])[0], project=root))
                elif parsed.path == "/api/onboarding/configure":
                    from magent.web_onboarding import configure

                    body = self._body()
                    try:
                        self._json(
                            configure(
                                str(body.get("provider", "")),
                                str(body.get("model", "")),
                                credential=str(body.get("credential", "")),
                                credential_storage=str(body.get("credential_storage", "keyring")),
                            )
                        )
                    except ValueError as problem:
                        # A bad provider name is the user's mistake, not a
                        # server fault; raising here would surface as a 500.
                        self._json({"ok": False, "error": str(problem)}, status=400)
                elif parsed.path == "/api/profiles/generate":
                    if not username:
                        self._json({"ok": False, "error": "username unavailable"}, status=400)
                        return
                    from magent.agent_profiles.generation import generate_profile_proposal
                    from magent.config import load_config

                    body = self._body()
                    result = asyncio.run(
                        generate_profile_proposal(
                            str(body.get("prompt") or ""),
                            project=root,
                            config=load_config(username),
                            name=str(body.get("name") or ""),
                            extends=str(body.get("extends") or ""),
                        )
                    )
                    self._json(result, status=200 if result.get("ok") else 400)
                elif parsed.path == "/api/profiles":
                    if not username:
                        self._json({"ok": False, "error": "username unavailable"}, status=400)
                        return
                    from magent.agent_profiles.authoring import build_profile_document
                    from magent.agent_profiles.desktop import apply_profile
                    from magent.config import load_config

                    body = self._body()
                    route = dict(body.get("model") or {})
                    try:
                        document = build_profile_document(
                            name=str(body.get("name", "")),
                            description=str(body.get("description", "")),
                            role={"instructions": str(body.get("instructions", "")).strip()},
                            model={
                                "provider": route.get("provider"),
                                "id": route.get("id") or route.get("model"),
                            },
                            tools={
                                "allow": list(body.get("tools") or []),
                                "skills": list(body.get("skills") or []),
                                "mcp_servers": list(body.get("mcp_servers") or []),
                            },
                            permissions={
                                "default": body.get("permission_mode"),
                                "network": body.get("network_mode"),
                            },
                            lifecycle={"writeback": "off"},
                        )
                    except ValueError as problem:
                        self._json({"ok": False, "error": str(problem)}, status=400)
                        return
                    result = apply_profile(
                        document,
                        scope=str(body.get("scope", "project")),
                        project=root,
                        config=load_config(username),
                        expected_digest=str(body.get("expected_digest", "")),
                    )
                    self._json(
                        result,
                        status=(200 if result.get("operation") == "update" else 201)
                        if result.get("ok")
                        else (409 if result.get("conflict") else 400),
                    )
                elif parsed.path == "/api/profiles/clone":
                    if not username:
                        self._json({"ok": False, "error": "username unavailable"}, status=400)
                    else:
                        from magent.agent_profiles.desktop import clone_profile
                        from magent.config import load_config

                        body = self._body()
                        result = clone_profile(
                            str(body.get("source") or ""),
                            str(body.get("name") or ""),
                            scope=str(body.get("scope") or "project"),
                            project=root,
                            config=load_config(username),
                        )
                        self._json(result, status=201 if result.get("ok") else 400)
                elif parsed.path == "/api/profiles/import":
                    if not username:
                        self._json({"ok": False, "error": "username unavailable"}, status=400)
                    else:
                        from magent.config import load_config
                        from magent.web_profiles import import_document

                        body = self._body()
                        result = import_document(
                            body.get("document"),
                            scope=str(body.get("scope") or "project"),
                            name=str(body.get("name") or ""),
                            project=root,
                            config=load_config(username),
                        )
                        self._json(result, status=200 if result.get("ok") else 400)
                elif parsed.path == "/api/profiles/delete":
                    if not username:
                        self._json({"ok": False, "error": "username unavailable"}, status=400)
                    else:
                        from magent.agent_profiles.desktop import delete_profile
                        from magent.config import load_config

                        body = self._body()
                        result = delete_profile(
                            str(body.get("name", "")),
                            project=root,
                            config=load_config(username),
                            expected_digest=str(body.get("expected_digest", "")),
                        )
                        self._json(
                            result,
                            status=200
                            if result.get("ok")
                            else (409 if result.get("conflict") else 400),
                        )
                elif parsed.path == "/api/settings":
                    from magent.desktop_api import CONFIG_SCHEMA, config_set

                    body = self._body()
                    setting_path = str(body.get("path", ""))
                    allowed = {str(item["path"]): item for item in CONFIG_SCHEMA}
                    if setting_path not in allowed:
                        self._json(
                            {"ok": False, "error": "setting is not editable in the guided UI"},
                            status=400,
                        )
                    else:
                        field = allowed[setting_path]
                        value = body.get("value")
                        field_type = field.get("type")
                        invalid = bool(
                            (field_type == "boolean" and not isinstance(value, bool))
                            or (
                                field_type == "integer"
                                and (not isinstance(value, int) or isinstance(value, bool))
                            )
                            or (field_type in {"string", "enum"} and not isinstance(value, str))
                            or (field.get("choices") and value not in field["choices"])
                        )
                        minimum = field.get("min")
                        if (
                            field_type == "integer"
                            and isinstance(value, int)
                            and not isinstance(value, bool)
                            and minimum is not None
                            and value < int(minimum)
                        ):
                            invalid = True
                        if invalid:
                            self._json(
                                {"ok": False, "error": f"invalid value for {setting_path}"},
                                status=400,
                            )
                            return
                        self._json(
                            config_set(
                                setting_path,
                                value,
                                username=username,
                                scope=str(
                                    body.get("scope", allowed[setting_path].get("scope", "global"))
                                ),
                            )
                        )
                elif parsed.path == "/api/state":
                    self._json(ui_state(store, root, username=username))
                elif parsed.path == "/api/cockpit":
                    self._json(cockpit_state(store, root))
                elif parsed.path == "/api/docs/search":
                    self._json(search_docs(query.get("q", [""])[0]))
                elif parsed.path == "/api/docs/topic":
                    self._json(
                        {
                            "ok": True,
                            "topic": query.get("slug", [""])[0],
                            "content": read_topic(query.get("slug", [""])[0]),
                        }
                    )
                elif parsed.path == "/api/release/check":
                    self._json(run_release_check(store, root))
                elif parsed.path == "/api/readiness":
                    if not username:
                        self._json({"ok": False, "error": "username unavailable"}, status=400)
                    else:
                        from magent.config import load_config

                        self._json(
                            readiness_report(username, load_config(username), store, project=root)
                        )
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
                elif parsed.path == "/api/runs":
                    # A reloading tab knows its conversation, not the run id it
                    # lost, so reattachment is looked up by conversation.
                    active = runs.active_for(query.get("conversation_id", [""])[0])
                    self._json({"ok": True, "run": active.snapshot() if active else None})
                elif parsed.path == "/api/runs/events":
                    found = runs.get(query.get("id", [""])[0])
                    if found is None:
                        self._json({"ok": False, "error": "run not found"}, status=404)
                        return
                    self._stream_run(found, after=_int_or(query.get("after", ["0"])[0], 0))
                elif parsed.path == "/api/runs/cancel":
                    body = self._body()
                    self._json(runs.cancel(str(body.get("id", ""))))
                elif parsed.path == "/api/runs/approve":
                    body = self._body()
                    found = runs.get(str(body.get("id", "")))
                    if found is None:
                        self._json({"ok": False, "error": "run not found"}, status=404)
                        return
                    decided = found.decide_approval(
                        str(body.get("request_id", "")), bool(body.get("approved"))
                    )
                    self._json(
                        {"ok": decided}
                        if decided
                        else {
                            "ok": False,
                            # Answering a stale prompt is a race, not a fault:
                            # say which, so the UI can just drop the card.
                            "error": "That approval is no longer waiting for an answer.",
                        }
                    )
                elif parsed.path == "/api/memory/overview":
                    from magent.web_memory import overview

                    self._json(overview(username or ""))
                elif parsed.path == "/api/memory/search":
                    from magent.web_memory import search as memory_search

                    self._json(
                        memory_search(
                            username or "",
                            query.get("q", [""])[0],
                            mode=query.get("mode", ["keyword"])[0],
                            # A junk limit is a bad request, not a 500.
                            limit=_int_or(query.get("limit", ["20"])[0], 20),
                        )
                    )
                elif parsed.path == "/api/memory/node":
                    from magent.web_memory import node as memory_node

                    self._json(memory_node(username or "", query.get("id", [""])[0]))
                elif parsed.path == "/api/memory/nodes":
                    from magent import web_memory

                    body = self._body()
                    action = str(body.get("action") or "create")
                    if action == "create":
                        result = web_memory.create(username or "", body)
                    elif action == "update":
                        result = web_memory.update(username or "", body)
                    elif action == "delete":
                        result = web_memory.delete(username or "", str(body.get("id") or ""))
                    else:
                        result = {"ok": False, "error": "Unknown memory action."}
                    self._json(result, status=200 if result.get("ok") else 400)
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
            except WorkspaceError as e:
                self._json({"ok": False, "error": str(e)}, status=400)
            except Exception as e:
                self._json({"ok": False, "error": str(e)}, status=500)

        def log_message(self, format: str, *args: Any) -> None:
            return None

    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError as e:
        return {"ok": False, "error": f"Could not bind 127.0.0.1:{port}: {e}", "port": port}

    if schedules:
        shutdown_server = server.shutdown

        def shutdown() -> None:
            schedules.stop()
            shutdown_server()

        server.shutdown = shutdown  # type: ignore[method-assign]

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    # The token travels in the opened URL; without it every request is refused.
    url = f"http://127.0.0.1:{port}/?token={token}"
    if open_browser:
        webbrowser.open(url)
    # Returning the server lets callers shut it down instead of leaking it.
    return {
        "ok": True,
        "url": url,
        "project": str(root),
        "token": token,
        "server": server,
        "schedules": schedules,
    }
