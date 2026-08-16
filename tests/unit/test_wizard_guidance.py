from rich.console import Console

from magent.cli.wizard_guidance import explain_field, explain_options


def test_wizard_guidance_explains_choices_and_notes() -> None:
    console = Console(record=True, width=90, color_system=None)

    explain_options(
        console,
        "Isolation",
        [("copy", "Use a filesystem copy."), ("worktree", "Use a Git worktree.")],
        note="Choose based on project and runtime support.",
    )
    explain_field(console, "Model role", "Controls which configured model is selected.")

    output = console.export_text()
    assert "Isolation" in output
    assert "filesystem copy" in output
    assert "Git worktree" in output
    assert "Choose based" in output
    assert "Model role" in output
