"""Tests for the permission model."""

from magent.permissions import (
    RiskTier,
    classify_file_op,
    classify_shell_command,
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
