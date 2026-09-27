"""Regenerate lifecycle.json: recorded magent.rpc.v1 exchanges for client tests.

Mag Command Center (and any other client) can replay these request/response
pairs to test its remote transport without a running MagAgent. Volatile values
(timestamps, paths, versions, the token) are normalized. Run from the repo root:
`python tests/fixtures/rpc_gateway/generate.py`.
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from magent.rpc_gateway import Gateway  # noqa: E402
from tests.unit.test_rpc_gateway import TOKEN, fake_command  # noqa: E402

DECISION = {
    "aais": "1.0",
    "type": "approval.decided",
    "id": "evt_fixture",
    "occurred_at": "2026-09-27T00:00:00Z",
    "sequence": 1,
    "decision": {
        "id": "dec_fixture",
        "request_id": "apr_1",
        "action_digest": "sha256:" + "0" * 64,
        "decided_at": "2026-09-27T00:00:00Z",
        "decision": "approve",
        "scope": "once",
        "actor": {"id": "fixture-user", "type": "human"},
    },
}


def normalize(value, root: str):
    if isinstance(value, dict):
        return {
            key: (0 if key == "started_at" else normalize(item, root)) for key, item in value.items()
        }
    if isinstance(value, list):
        return [normalize(item, root) for item in value]
    if isinstance(value, str):
        return value.replace(root, "/workspace").replace(sys.executable, "python")
    return value


def main() -> None:
    root = tempfile.mkdtemp(prefix="rpc-fixture-")
    gateway = Gateway(token=TOKEN, roots=[Path(root)], command=fake_command)
    exchanges = []
    counter = 0

    def call(name: str, method: str, params: dict, auth: str = f"Bearer {TOKEN}") -> dict:
        nonlocal counter
        counter += 1
        request = {"jsonrpc": "2.0", "id": f"req-{counter}", "method": method, "params": params}
        response = gateway.handle(json.dumps(request).encode(), auth)
        if method == "runtime_info" and "result" in response:
            response["result"]["version"] = "<magent version>"
        exchanges.append(
            {
                "name": name,
                "authorization": "Bearer <token>" if auth.endswith(TOKEN) else auth,
                "request": request,
                "response": normalize(response, root),
            }
        )
        return response

    call("runtime_info", "runtime_info", {})
    call("unauthorized", "runtime_info", {}, auth="Bearer wrong-token-value")
    call("run_magent", "run_magent", {"args": ["system", "info"]})
    call("run_magent_input", "run_magent_input", {"args": ["echo-input"], "input": "profile"})
    call("stream_start", "stream.start", {"id": "fixture-run", "args": ["approve"]})
    after = 0
    for _ in range(40):
        page = gateway.stream_events({"id": "fixture-run", "after": after, "wait_ms": 2000})
        after = page["next"]
        if any("approval.requested" in event["line"] for event in page["events"]):
            break
    call("stream_events_until_approval", "stream.events", {"id": "fixture-run", "after": 0})
    call(
        "write_decision",
        "write_magent_stream",
        {"id": "fixture-run", "line": json.dumps(DECISION)},
    )
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and not gateway.streams["fixture-run"].result:
        time.sleep(0.05)
    call("stream_events_done", "stream.events", {"id": "fixture-run", "after": after})
    call("stream_start_for_cancel", "stream.start", {"id": "fixture-cancel", "args": ["sleep"]})
    call("cancel", "cancel_magent_stream", {"id": "fixture-cancel"})
    call("forbidden_command", "run_magent", {"args": ["serve", "--rpc"]})
    call("project_outside_roots", "run_magent", {"args": ["ask", "x", "--project", "/"]})
    call("unknown_method", "inspect_project", {"path": "/"})
    call("unknown_stream", "stream.events", {"id": "missing"})
    gateway.shutdown()
    target = Path(__file__).with_name("lifecycle.json")
    document = {
        "protocol": "magent.rpc.v1",
        "note": "Recorded with a scripted stand-in for `python -m magent`; see generate.py.",
        "exchanges": exchanges,
    }
    target.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {target} ({len(exchanges)} exchanges)")


if __name__ == "__main__":
    main()
