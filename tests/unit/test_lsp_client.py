from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from magent.lsp_client import LspClient, LspError


@pytest.fixture
def client(tmp_path: Path) -> LspClient:
    source = tmp_path / "demo.py"
    source.write_text("def demo():\n    return 1\n", encoding="utf-8")
    server = Path(__file__).parents[1] / "fixtures" / "fake_lsp_server.py"
    value = LspClient([sys.executable, str(server)], tmp_path, timeout=0.25)
    yield value
    value.stop()


def test_lsp_client_lifecycle_and_documents(client: LspClient) -> None:
    capabilities = client.start()
    assert capabilities["definitionProvider"] is True
    assert client.supports("hoverProvider")

    source = client.root / "demo.py"
    uri = client.open_document(source, "python")
    notice = client.wait_for_notification(
        "textDocument/publishDiagnostics",
        predicate=lambda event: event["params"]["uri"] == uri,
    )
    assert notice["params"]["diagnostics"][0]["message"] == "fake warning"

    client.change_document(source, "def demo():\n    return 2\n")
    client.close_document(source)
    client.restart()
    assert client.process is not None


def test_lsp_client_requests_and_timeout(client: LspClient) -> None:
    client.start()
    assert client.request("textDocument/hover", {})["contents"] == "demo hover"
    with pytest.raises(LspError, match="timed out"):
        client.request("test/slow")


def test_lsp_client_collects_notifications_in_one_window(client: LspClient) -> None:
    client.start()
    client.open_document(client.root / "demo.py", "python")
    notices = client.collect_notifications("textDocument/publishDiagnostics", timeout=0.5)
    assert len(notices) == 1


def test_lsp_client_requires_running_process(client: LspClient) -> None:
    with pytest.raises(LspError, match="not running"):
        client.request("workspace/symbol")


def test_lsp_client_drains_server_stderr(client: LspClient) -> None:
    client.start()
    deadline = time.monotonic() + 0.5
    while not client._stderr_lines and time.monotonic() < deadline:
        time.sleep(0.01)
    assert list(client._stderr_lines) == ["fake server ready"]
