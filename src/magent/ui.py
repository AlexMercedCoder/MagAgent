"""Local operations dashboard for MagAgent."""

from __future__ import annotations

import asyncio
import json
import mimetypes
import secrets
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
from magent.web_conversations import ConversationStore
from magent.web_graphs import (
    GraphRunManager,
    blank_graph_document,
    generate_web_graph,
    graph_catalog,
    preview_web_graph,
    read_web_graph,
    save_web_graph,
    web_task_node,
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

WEBUI_DIR = Path(__file__).with_name("webui")
# Vite writes the built bundle here. It is committed and ships inside the
# wheel, so installed users never need Node.
STATIC_DIR = WEBUI_DIR / "static"
MAX_REQUEST_BYTES = 128 * 1024


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
    graph_runs = GraphRunManager(store, username, root) if username else None

    # Endpoints that mutate state or spend money. GET must not reach these.
    # Paths whose POST mutates state: they demand the CSRF header, and a bare
    # GET is refused so a cross-origin <img> or <link> cannot trigger them.
    mutating_paths = {
        "/api/memory/promote",
        "/api/provider/smoke",
        "/api/release/check",
        "/api/conversations",
        "/api/conversations/update",
        "/api/conversations/message",
        "/api/profiles",
        "/api/profiles/import",
        "/api/graphs/run",
        "/api/graphs/draft",
        "/api/graphs/preview-draft",
        "/api/graphs/save",
        "/api/settings",
        "/api/onboarding/configure",
    }

    # Dual-purpose paths: POST mutates and still needs CSRF, but GET is a plain
    # read and must be allowed. Only paths with a real GET branch below belong
    # here; /api/profiles and /api/settings are POST-only and must keep
    # refusing GET, or the request would fall into their write handlers.
    readable_paths = {"/api/conversations"}

    class Handler(BaseHTTPRequestHandler):
        def _authorized(self, parsed: urllib.parse.ParseResult) -> bool:
            host = (self.headers.get("Host") or "").split(":")[0]
            if host not in {"127.0.0.1", "localhost", "[::1]", "::1"}:
                return False  # DNS rebinding
            origin = self.headers.get("Origin")
            if origin and urllib.parse.urlparse(origin).hostname not in {"127.0.0.1", "localhost", "::1"}:
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
            self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            self._security_headers()
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _stream_event(self, data: dict[str, Any]) -> None:
            self.wfile.write((json.dumps(data, default=str) + "\n").encode("utf-8"))
            self.wfile.flush()

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
                    self.send_header("Set-Cookie", f"magent_ui={token}; HttpOnly; SameSite=Strict; Path=/")
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
                    from magent.desktop_api import agent_profiles, config_schema

                    self._json(
                        {
                            "ok": True,
                            "csrf_token": token,
                            "project": str(root),
                            "conversations": conversations.list(),
                            "profiles": agent_profiles(str(root)),
                            "settings": config_schema(username),
                        }
                    )
                elif parsed.path == "/api/conversations" and method == "GET":
                    self._json({"ok": True, "conversations": conversations.list()})
                elif parsed.path == "/api/graphs":
                    self._json(graph_catalog(store, root))
                elif parsed.path == "/api/graphs/preview":
                    if graph_runs is None:
                        self._json({"ok": False, "error": "username unavailable"}, status=400)
                    else:
                        self._json(graph_runs.preview(query.get("path", [""])[0]))
                elif parsed.path == "/api/graphs/draft":
                    if not username:
                        self._json({"ok": False, "error": "username unavailable"}, status=400)
                    else:
                        body = self._body()
                        goal = str(body.get("goal", ""))
                        if body.get("mode") == "ai":
                            self._json(asyncio.run(generate_web_graph(goal, project=root, username=username)))
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
                            self._json({"ok": False, "error": "document must be an object"}, status=400)
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
                            self._json({"ok": False, "error": "document must be an object"}, status=400)
                            return
                        result = save_web_graph(
                            document,
                            str(body.get("path", "")),
                            project=root,
                            username=username,
                            expected_digest=str(body.get("expected_digest", "")),
                        )
                        self._json(result, status=200 if result.get("ok") else (409 if result.get("conflict") else 400))
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
                            self._json({"ok": False, "error": "params must be an object"}, status=400)
                            return
                        result = graph_runs.start(
                            str(body.get("path", "")),
                            params=params,
                            approved_gates=list(body.get("approved_gates") or []),
                        )
                        self._json(result, status=202)
                elif parsed.path == "/api/conversations" and method == "POST":
                    body = self._body()
                    record = conversations.create(
                        title=str(body.get("title", "New conversation")),
                        kind=str(body.get("kind", "chat")),
                        project=str(root),
                        profiles=list(body.get("profiles") or []),
                        coordinator=str(body.get("coordinator", "")),
                    )
                    self._json({"ok": True, "conversation": record}, status=201)
                elif parsed.path == "/api/conversations/update":
                    body = self._body()
                    record = conversations.update(
                        str(body.get("conversation_id", "")),
                        title=body.get("title"),
                        archived=bool(body.get("archived", False)),
                    )
                    self._json({"ok": True, "conversation": record})
                elif parsed.path == "/api/conversations/message":
                    if not username:
                        self._json({"ok": False, "error": "username unavailable"}, status=400)
                        return
                    body = self._body()
                    conversation_id = str(body.get("conversation_id", ""))
                    content = str(body.get("content", "")).strip()
                    if not content or len(content) > 32000:
                        self._json({"ok": False, "error": "message must contain 1 to 32000 characters"}, status=400)
                        return
                    conversation = conversations.get(conversation_id)
                    if conversation is None:
                        self._json({"ok": False, "error": "conversation not found"}, status=404)
                        return
                    turn_lock = conversation_locks.setdefault(conversation_id, threading.Lock())
                    if not turn_lock.acquire(blocking=False):
                        self._json(
                            {"ok": False, "error": "a turn is already running for this conversation"},
                            status=409,
                        )
                        return
                    conversations.append_message(conversation_id, role="user", content=content, speaker="You")
                    conversation = conversations.get(conversation_id) or conversation
                    self.send_response(200)
                    self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
                    self._security_headers()
                    self.end_headers()

                    from magent.web_chat import WebChatRunner

                    def chunk(speaker: str, text: str) -> None:
                        self._stream_event({"type": "chunk", "speaker": speaker, "content": text})

                    try:
                        results = WebChatRunner(username, root).run(conversation, content, on_chunk=chunk)
                        for result in results:
                            conversations.append_message(
                                conversation_id,
                                role="assistant",
                                content=result["content"],
                                speaker=result["speaker"],
                                metadata={key: value for key, value in result.items() if key != "content"},
                            )
                        self._stream_event(
                            {"type": "done", "conversation": conversations.get(conversation_id)}
                        )
                    except Exception as exc:
                        # A raw repr in a chat bubble tells the user nothing they
                        # can act on; name the state and the recovery step.
                        from magent.webui_errors import describe

                        friendly = describe(exc)
                        conversations.append_message(
                            conversation_id,
                            role="assistant",
                            content=friendly.as_message(),
                            speaker="MagAgent",
                            status="error",
                            metadata={"error_kind": friendly.kind, "detail": friendly.detail},
                        )
                        self._stream_event({"type": "error", **friendly.as_event()})
                    finally:
                        turn_lock.release()
                elif parsed.path == "/api/profile":
                    from magent.agent_profiles.desktop import inspect_profile
                    from magent.config import load_config

                    config = load_config(username) if username else None
                    self._json(
                        inspect_profile(
                            query.get("name", [""])[0], project=root, config=config
                        )
                    )
                elif parsed.path == "/api/profiles/export":
                    from magent.config import load_config
                    from magent.web_profiles import export_document

                    config = load_config(username) if username else None
                    self._json(
                        export_document(
                            query.get("name", [""])[0], project=root, config=config
                        )
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
                        self._json(configure(str(body.get("provider", "")), str(body.get("model", ""))))
                    except ValueError as problem:
                        # A bad provider name is the user's mistake, not a
                        # server fault; raising here would surface as a 500.
                        self._json({"ok": False, "error": str(problem)}, status=400)
                elif parsed.path == "/api/profiles":
                    if not username:
                        self._json({"ok": False, "error": "username unavailable"}, status=400)
                        return
                    from magent.agent_profiles.desktop import apply_profile
                    from magent.config import load_config

                    body = self._body()
                    document = {
                        "oap": "1.0",
                        "metadata": {
                            "name": str(body.get("name", "")).strip(),
                            "description": str(body.get("description", "")).strip(),
                            "revision": 1,
                        },
                        "spec": {
                            "role": {"instructions": str(body.get("instructions", "")).strip()},
                            "permissions": {"default": str(body.get("permission_mode", "balanced"))},
                        },
                        "state": [],
                        "history": [],
                        "proposals": [],
                        "lifecycle": {"writeback": "off"},
                    }
                    result = apply_profile(
                        document,
                        scope=str(body.get("scope", "project")),
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
                elif parsed.path == "/api/settings":
                    from magent.desktop_api import CONFIG_SCHEMA, config_set

                    body = self._body()
                    setting_path = str(body.get("path", ""))
                    allowed = {str(item["path"]): item for item in CONFIG_SCHEMA}
                    if setting_path not in allowed:
                        self._json({"ok": False, "error": "setting is not editable in the guided UI"}, status=400)
                    else:
                        field = allowed[setting_path]
                        value = body.get("value")
                        field_type = field.get("type")
                        invalid = bool(
                            (field_type == "boolean" and not isinstance(value, bool))
                            or (field_type == "integer" and (not isinstance(value, int) or isinstance(value, bool)))
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
                                scope=str(body.get("scope", allowed[setting_path].get("scope", "global"))),
                            )
                        )
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

    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError as e:
        return {"ok": False, "error": f"Could not bind 127.0.0.1:{port}: {e}", "port": port}

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    # The token travels in the opened URL; without it every request is refused.
    url = f"http://127.0.0.1:{port}/?token={token}"
    if open_browser:
        webbrowser.open(url)
    # Returning the server lets callers shut it down instead of leaking it.
    return {"ok": True, "url": url, "project": str(root), "token": token, "server": server}
