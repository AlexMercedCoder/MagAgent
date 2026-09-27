"""Phase 6: team MagGraph with review-gated merge."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from magent.team_memory import REVIEWS_FILE, TeamMemory, TeamMemoryError

NODE = '---\nid: "{id}"\ntype: "preference"\nlinks: []\n---\n# {id}\n\n{body}\n'


def _personal(root: Path, **nodes: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for node_id, body in nodes.items():
        (root / f"{node_id}.md").write_text(NODE.format(id=node_id, body=body), encoding="utf-8")
    return root


@pytest.fixture
def team(tmp_path: Path) -> tuple[TeamMemory, TeamMemory, Path]:
    remote = tmp_path / "shared" / "team.git"
    alice = TeamMemory("alice", root=tmp_path / "alice" / "team")
    alice.init(str(remote), create=True)
    bob = TeamMemory("bob", root=tmp_path / "bob" / "team")
    bob.init(str(remote.resolve()))
    return alice, bob, tmp_path


def test_propose_review_accept_round_trip(team) -> None:
    alice, bob, tmp = team
    personal = _personal(tmp / "alice-mem", runner="Use pytest with xdist -n 4.")
    proposal = alice.propose(["runner"], personal_dir=personal, message="Test runner convention")
    assert proposal["branch"] == f"proposals/alice/{proposal['id']}"

    inbox = bob.inbox()["proposals"]
    assert [item["id"] for item in inbox] == [proposal["id"]]
    assert inbox[0]["author"] == "alice"
    assert inbox[0]["changes"] == [{"status": "A", "path": "nodes/runner.md"}]
    shown = bob.show(proposal["id"])
    assert shown["checks"] == {"ok": True, "problems": []}
    assert "+Use pytest with xdist -n 4." in shown["diff"]

    with pytest.raises(TeamMemoryError, match="a teammate has to accept"):
        alice.decide(proposal["id"], decision="accept")

    assert bob.decide(proposal["id"], decision="accept", reason="agreed")["decision"] == "accept"
    assert bob.inbox()["proposals"] == []
    alice.sync()
    assert (alice.nodes_dir / "runner.md").exists()
    [review] = alice.reviews()
    assert review["decision"] == "accept" and review["reviewer"] == "bob"
    assert review["author"] == "alice" and review["reason"] == "agreed"


def test_reject_leaves_main_untouched_and_is_recorded(team) -> None:
    alice, bob, tmp = team
    personal = _personal(tmp / "alice-mem", idea="Maybe tabs.")
    proposal = alice.propose(["idea"], personal_dir=personal)
    bob.decide(proposal["id"], decision="reject", reason="we use spaces")
    alice.sync()
    assert not (alice.nodes_dir / "idea.md").exists()
    assert alice.reviews()[-1]["decision"] == "reject"
    assert bob.inbox()["proposals"] == []


def test_nodes_with_secrets_or_no_front_matter_are_refused(team) -> None:
    alice, _bob, tmp = team
    personal = _personal(
        tmp / "alice-mem", leaky="token sk-proj-abcdefghijklmnopqrstuvwxyz0123456789"
    )
    with pytest.raises(TeamMemoryError, match="secret"):
        alice.propose(["leaky"], personal_dir=personal)
    (personal / "bare.md").write_text("no front matter\n", encoding="utf-8")
    with pytest.raises(TeamMemoryError, match="front matter"):
        alice.propose(["bare"], personal_dir=personal)
    with pytest.raises(TeamMemoryError, match="Not in your memory graph"):
        alice.propose(["missing"], personal_dir=personal)


def test_self_review_needs_an_explicit_flag(team) -> None:
    alice, _bob, tmp = team
    personal = _personal(tmp / "alice-mem", solo="One-person team.")
    proposal = alice.propose(["solo"], personal_dir=personal)
    result = alice.decide(proposal["id"], decision="accept", allow_self_review=True)
    assert result["decision"] == "accept"
    assert (alice.root / REVIEWS_FILE).read_text().count('"accept"') == 1


def test_uninitialized_team_explains_next_step(tmp_path: Path) -> None:
    with pytest.raises(TeamMemoryError, match="magent memory team init"):
        TeamMemory("carol", root=tmp_path / "none").inbox()


def test_cli_and_recall_evidence_label_team_nodes(monkeypatch, tmp_path: Path) -> None:
    from types import SimpleNamespace

    from magent.cli import main as cli_main
    from magent.config import load_config, user_memory_dir
    from tests.unit.test_cli import redirect_config

    redirect_config(monkeypatch, tmp_path)
    runner = CliRunner()
    assert runner.invoke(cli_main.app, ["user", "create", "alice"]).exit_code == 0
    remote = tmp_path / "shared.git"
    created = runner.invoke(
        cli_main.app, ["memory", "team", "init", str(remote), "--create", "--json"]
    )
    assert created.exit_code == 0, created.output
    assert json.loads(created.output)["nodes"] == 0
    _personal(user_memory_dir("alice"), deploy_window="Deploys happen on Tuesdays only.")
    proposed = runner.invoke(cli_main.app, ["memory", "team", "propose", "deploy_window", "--json"])
    assert proposed.exit_code == 0, proposed.output
    proposal_id = json.loads(proposed.output)["id"]
    inbox = runner.invoke(cli_main.app, ["memory", "team", "inbox"])
    assert proposal_id in inbox.output
    own = runner.invoke(cli_main.app, ["memory", "team", "accept", proposal_id])
    assert own.exit_code == 1 and "teammate" in own.output
    accepted = runner.invoke(
        cli_main.app, ["memory", "team", "accept", proposal_id, "--allow-self-review"]
    )
    assert accepted.exit_code == 0, accepted.output

    from magent.agent import _team_memory_manager
    from magent.agent_runtime.context import ContextRuntimeMixin

    team_memory = _team_memory_manager(load_config("alice"), "alice", None)
    assert team_memory is not None and team_memory.available
    runtime = ContextRuntimeMixin()
    runtime.config = SimpleNamespace(
        memory_budget_tokens=4000, repo_map_budget_tokens=0, skill_budget_tokens=0
    )
    runtime.profile = None
    runtime.memory = SimpleNamespace(available=True, recall=lambda _q: "", last_recall_evidence={})
    runtime.team_memory = team_memory
    runtime.repo_map = SimpleNamespace(relevant_slice=lambda *_args: "")
    runtime.skill_registry = SimpleNamespace(build_skill_context=lambda *_a, **_k: "")
    runtime.cwd = "."
    runtime.compacted_summary = ""
    runtime.scratchpad = {}
    runtime.turn_count = 1
    runtime.logger = SimpleNamespace(log_activity_event=lambda _event: None)
    monkeypatch.setattr("magent.config_validation.load_ambient_instructions", lambda *_a: "")
    prompt = runtime._build_context_prompt("When do deploys happen? Tuesdays?")
    assert "Team Memory" in prompt
    record = runtime.last_memory_evidence
    assert record["status"] == "used"
    assert {node["source"] for node in record["nodes"]} == {"team"}


def test_web_api_helpers(monkeypatch, tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from magent import web_memory
    from magent.cli import main as cli_main
    from tests.unit.test_cli import redirect_config

    redirect_config(monkeypatch, tmp_path)
    CliRunner().invoke(cli_main.app, ["user", "create", "bob"])
    unconfigured = web_memory.team_inbox("bob")
    assert unconfigured["configured"] is False and "magent memory team init" in unconfigured["note"]
    remote = tmp_path / "shared.git"
    TeamMemory("bob").init(str(remote), create=True)
    alice = TeamMemory("alice", root=tmp_path / "alice-team")
    alice.init(str(remote))
    personal = _personal(tmp_path / "alice-mem", rule="Two reviewers for migrations.")
    proposal = alice.propose(["rule"], personal_dir=personal)
    inbox = web_memory.team_inbox("bob")
    assert inbox["configured"] is True and inbox["user"] == "bob"
    assert inbox["proposals"][0]["id"] == proposal["id"]
    assert web_memory.team_proposal("bob", proposal["id"])["checks"]["ok"] is True
    assert web_memory.team_decide("bob", proposal["id"], "maybe")["ok"] is False
    assert web_memory.team_decide("bob", proposal["id"], "accept")["ok"] is True
