"""Tests for the permission model."""

from magent.permissions import (
    RiskTier,
    classify_file_op,
    classify_shell_command,
    shell_pattern_matches,
)


class TestClassifyShellCommand:
    def test_silent_commands(self):
        assert classify_shell_command("git status") == RiskTier.SILENT
        assert classify_shell_command("ls -la") == RiskTier.SILENT
        assert classify_shell_command("cat README.md") == RiskTier.SILENT
        assert classify_shell_command("rg 'def main'") == RiskTier.SILENT
        assert classify_shell_command("find /tmp/project -type f | sort") == RiskTier.SILENT
        assert classify_shell_command("which npx && npx --version") == RiskTier.SILENT
        assert classify_shell_command("which npm && npm --version 2>&1") == RiskTier.SILENT
        assert classify_shell_command("curl -s https://example.com | grep title | head -5") == RiskTier.AUTO
        assert classify_shell_command("curl -s https://example.com | sed -n '1,5p' | cut -c1-80") == RiskTier.AUTO

    def test_auto_commands(self):
        assert classify_shell_command("git add -A") == RiskTier.AUTO
        assert classify_shell_command("npm install") == RiskTier.AUTO
        assert classify_shell_command("cargo build") == RiskTier.AUTO
        assert classify_shell_command("pytest tests/") == RiskTier.AUTO
        assert classify_shell_command("curl https://example.com") == RiskTier.AUTO

    def test_confirm_commands(self):
        assert classify_shell_command("git push origin main") == RiskTier.CONFIRM
        assert classify_shell_command("curl -X POST https://example.com") == RiskTier.CONFIRM
        assert classify_shell_command("npm publish") == RiskTier.CONFIRM

    def test_block_commands(self):
        assert classify_shell_command("rm -rf /") == RiskTier.BLOCK
        assert classify_shell_command("sudo apt install curl") == RiskTier.BLOCK
        assert classify_shell_command("rm -rf node_modules") == RiskTier.BLOCK

    def test_allowlist_overrides(self):
        # Ordinary git commands can be allowlisted to AUTO.
        tier = classify_shell_command("git status --short", allowlist=["git *"])
        assert tier == RiskTier.AUTO

    def test_allowlist_does_not_override_confirm_or_shell_control(self):
        assert classify_shell_command("git push origin main", allowlist=["git *"]) == RiskTier.CONFIRM
        assert classify_shell_command("git status; rm -rf /tmp/x", allowlist=["git *"]) == RiskTier.BLOCK

    def test_unknown_command_defaults_to_confirm(self):
        tier = classify_shell_command("my-custom-deploy-script --prod")
        assert tier == RiskTier.CONFIRM

    def test_python_and_pip_commands_distinguish_probes_from_installs(self):
        assert classify_shell_command("python -m pip list") == RiskTier.SILENT
        assert classify_shell_command("python3 -m pip install demo") == RiskTier.AUTO
        assert classify_shell_command("pip3 list") == RiskTier.SILENT
        assert classify_shell_command("pip install demo") == RiskTier.AUTO
        assert classify_shell_command("python -c 'print(2 + 2)'") == RiskTier.SILENT
        assert classify_shell_command("python -c 'print(open(\"x\").read())'") == RiskTier.CONFIRM
        assert classify_shell_command("python -c ''") == RiskTier.CONFIRM
        assert classify_shell_command("python -c 'x = 1'") == RiskTier.CONFIRM
        assert classify_shell_command("python -c 'print(x=len([]))'") == RiskTier.CONFIRM
        assert classify_shell_command("python -c 'not valid python'") == RiskTier.CONFIRM

    def test_network_flag_shapes_are_classified_explicitly(self):
        assert classify_shell_command("curl --request GET https://example.com") == RiskTier.AUTO
        assert classify_shell_command("curl --request POST https://example.com") == RiskTier.CONFIRM
        assert classify_shell_command("wget --output-document=- https://example.com") == RiskTier.AUTO
        assert classify_shell_command("wget --spider https://example.com") == RiskTier.AUTO
        assert classify_shell_command("curl --silent https://example.com") == RiskTier.AUTO
        assert classify_shell_command("curl --connect-timeout 2 https://example.com") == RiskTier.AUTO
        assert classify_shell_command("curl --frobnicate https://example.com") == RiskTier.CONFIRM
        assert classify_shell_command("curl -XGET https://example.com") == RiskTier.AUTO
        assert classify_shell_command("curl -XPOST https://example.com") == RiskTier.CONFIRM
        assert classify_shell_command("curl -H 'Accept: text/plain' https://example.com") == RiskTier.AUTO
        assert classify_shell_command("curl -Z https://example.com") == RiskTier.CONFIRM

    def test_empty_and_output_commands_fail_toward_confirmation(self):
        assert classify_shell_command("") == RiskTier.CONFIRM
        assert classify_shell_command("sort -o result.txt input.txt") == RiskTier.CONFIRM
        assert shell_pattern_matches("git *", "git status $(rm -rf /tmp/x)") is False
        assert shell_pattern_matches("'", "git status") is False


class TestClassifyFileOp:
    def test_read_always_silent(self):
        assert classify_file_op("read", "src/main.py", "/project") == RiskTier.SILENT

    def test_write_in_cwd_is_auto(self):
        assert classify_file_op("write", "output.txt", "/project") == RiskTier.AUTO

    def test_write_outside_cwd_is_confirm(self):
        assert classify_file_op("write", "/etc/hosts", "/project") == RiskTier.CONFIRM

    def test_delete_in_cwd_is_confirm(self):
        assert classify_file_op("delete", "old_file.txt", "/project") == RiskTier.CONFIRM

    def test_delete_outside_cwd_is_block(self):
        assert classify_file_op("delete", "/etc/passwd", "/project") == RiskTier.BLOCK

    def test_unknown_operation_defaults_to_confirmation(self):
        assert classify_file_op("chmod", "script.py", "/project") == RiskTier.CONFIRM


# --- asking a front end that has no console ----------------------------------


def test_a_non_interactive_caller_without_a_way_to_ask_can_only_refuse() -> None:
    """This was the local Web UI's whole problem: no console, so no tool ran."""
    from magent.permissions import RiskTier, check_permission

    result = check_permission("delete a file", RiskTier.CONFIRM, "balanced", interactive=False)

    assert result.approved is False
    assert result.reason == "permission-required"


def test_a_callback_lets_a_non_interactive_caller_decide() -> None:
    from magent.permissions import RiskTier, check_permission

    seen: list[tuple[str, int]] = []

    def ask(description: str, tier: int) -> bool:
        seen.append((description, int(tier)))
        return True

    result = check_permission(
        "delete a file", RiskTier.CONFIRM, "balanced", interactive=False, ask=ask
    )

    assert result.approved is True
    assert result.reason == "asked"
    # The callback is shown the same description and tier the console prompt is.
    assert seen == [("delete a file", int(RiskTier.CONFIRM))]


def test_a_callback_that_refuses_is_a_denial() -> None:
    from magent.permissions import RiskTier, check_permission

    result = check_permission(
        "delete a file", RiskTier.CONFIRM, "balanced", interactive=False, ask=lambda *_: False
    )
    assert result.approved is False


def test_the_callback_is_not_consulted_below_the_auto_threshold() -> None:
    """Prompting for something the mode already auto-approves is noise."""
    from magent.permissions import RiskTier, check_permission

    calls: list[str] = []
    result = check_permission(
        "read a file",
        RiskTier.AUTO,
        "balanced",
        interactive=False,
        ask=lambda description, _tier: calls.append(description) or True,
    )

    assert result.approved is True
    assert result.reason == "auto"
    assert calls == []


def test_the_callback_answers_the_high_risk_prompt_in_yolo_mode() -> None:
    from magent.permissions import RiskTier, check_permission

    result = check_permission(
        "wipe the disk", RiskTier.BLOCK, "yolo", interactive=False, ask=lambda *_: False
    )

    assert result.approved is False
    assert result.reason == "yolo-prompt"
