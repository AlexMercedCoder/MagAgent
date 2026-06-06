# Project Playbooks

Project playbooks live at `.magent/playbook.toml`. They describe commands and routines that are specific to a repository.

Create a starter file:

```bash
magent project playbook --init
```

Inspect the loaded playbook:

```bash
magent project playbook
```

Example:

```toml
[commands]
test = ["pytest -q"]
lint = "ruff check src tests"
build = "python -m build"

[release]
checklist = ["Run checks", "Update docs", "Build artifacts"]

[review]
rules = ["Source changes should include focused tests"]

[context]
briefing_topics = ["architecture", "testing", "commands"]
```

Playbook commands are included in `magent project commands`, project roles when applicable, `magent context map`, and the `project-playbook` workflow recipe.
