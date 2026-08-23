from __future__ import annotations

from pathlib import Path

import pytest

from magent import workbench_store
from magent.web_conversations import ConversationStore
from magent.workbench_store import WorkbenchStore


@pytest.fixture
def conversations(tmp_path: Path, monkeypatch) -> ConversationStore:
    monkeypatch.setattr(workbench_store, "USERS_DIR", tmp_path / "users")
    return ConversationStore(WorkbenchStore("web-ui-test"))


def test_conversation_crud_is_durable(conversations: ConversationStore) -> None:
    created = conversations.create(title="API review", kind="chat", project="/tmp/project")
    message = conversations.append_message(
        created["id"], role="user", content="Review this API", speaker="You"
    )

    loaded = conversations.get(created["id"])
    assert loaded is not None
    assert loaded["schema"] == "magent.web-conversation.v1"
    assert loaded["messages"] == [message]
    assert conversations.list()[0]["title"] == "API review"

    conversations.update(created["id"], title="Reviewed API", archived=True)
    assert conversations.list() == []
    assert conversations.list(include_archived=True)[0]["title"] == "Reviewed API"


def test_bot_conversation_requires_one_profile(conversations: ConversationStore) -> None:
    with pytest.raises(ValueError, match="exactly one"):
        conversations.create(title="Bot", kind="bot", project=".", profiles=[])

    created = conversations.create(
        title="Review bot", kind="bot", project=".", profiles=["review"]
    )
    assert created["profiles"] == ["review"]


def test_group_conversation_requires_bounded_members_and_coordinator(
    conversations: ConversationStore,
) -> None:
    with pytest.raises(ValueError, match="2 to 5"):
        conversations.create(
            title="Group", kind="group", project=".", profiles=["review"], coordinator="review"
        )
    with pytest.raises(ValueError, match="coordinator"):
        conversations.create(
            title="Group",
            kind="group",
            project=".",
            profiles=["review", "docs"],
            coordinator="explore",
        )

    created = conversations.create(
        title="Group",
        kind="group",
        project=".",
        profiles=["review", "docs", "review"],
        coordinator="review",
    )
    assert created["profiles"] == ["review", "docs"]
