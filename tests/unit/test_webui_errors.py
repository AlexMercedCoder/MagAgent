"""A failed turn should name the state and the fix, not print a Python repr."""

from __future__ import annotations

import pytest

from magent.webui_errors import describe


class ProviderError(Exception):
    pass


@pytest.mark.parametrize(
    ("exc", "kind"),
    [
        (ProviderError("Incorrect API key provided: sk-***"), "missing_credential"),
        (ProviderError("401 Unauthorized"), "missing_credential"),
        (ProviderError("Rate limit reached for gpt-5.6"), "rate_limited"),
        (ProviderError("429 Too Many Requests"), "rate_limited"),
        (TimeoutError("Request timed out after 60s"), "timeout"),
        (ConnectionError("getaddrinfo failed"), "provider_unreachable"),
        (ProviderError("Connection refused"), "provider_unreachable"),
        (PermissionError("shell:exec denied by policy"), "permission_denied"),
        (ProviderError("maximum context length is 128000 tokens"), "budget_exhausted"),
        (ProviderError("The model `gpt-9` does not exist"), "model_unavailable"),
        (ProviderError("run cancelled by user"), "cancelled"),
        (ProviderError("agent not found: reviewer"), "profile_problem"),
    ],
)
def test_common_failures_are_named(exc: Exception, kind: str) -> None:
    assert describe(exc).kind == kind


def test_unknown_failures_fall_back_without_losing_the_detail() -> None:
    friendly = describe(RuntimeError("something entirely new"))
    assert friendly.kind == "unexpected"
    assert friendly.detail == "something entirely new"
    assert "doctor" in friendly.action


def test_the_original_text_is_always_preserved() -> None:
    friendly = describe(ProviderError("Incorrect API key provided: sk-abc"))
    assert friendly.detail == "Incorrect API key provided: sk-abc"
    # ...but it is not what the user reads first.
    assert "sk-abc" not in friendly.as_message()


def test_message_names_the_state_and_the_action() -> None:
    friendly = describe(ConnectionError("network unreachable"))
    assert friendly.message.endswith(".")
    assert "magent doctor" in friendly.action
    assert friendly.as_message().startswith("MagAgent could not reach the provider.")


def test_an_empty_exception_still_produces_something_useful() -> None:
    friendly = describe(RuntimeError())
    assert friendly.detail == "RuntimeError"
    assert friendly.message


def test_cancellation_offers_no_recovery_step() -> None:
    """Cancelling is a choice, not a fault; it should not nag."""
    friendly = describe(ProviderError("cancelled"))
    assert friendly.action == ""
    assert friendly.as_message() == "The turn was cancelled."


def test_event_payload_is_machine_readable() -> None:
    event = describe(ProviderError("rate limit")).as_event()
    assert event["kind"] == "rate_limited"
    assert set(event) == {"kind", "error", "action", "detail"}
