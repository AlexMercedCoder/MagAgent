# Evals

MagAgent includes a small local eval harness for repeatable repository tasks.

Commands:

- `magent eval init`
- `magent eval list`
- `magent eval run evals/magagent-evals.json`
- `magent eval report`

An eval suite is a JSON file with tasks, prompts, and verification commands. The harness does not judge model quality by itself; it gives you a repeatable task/check scaffold so MagAgent changes can be compared over time.

Commands can be legacy shell strings or structured argv specs. Prefer structured argv specs for repeatable checks because they avoid shell expansion and still pass through MagAgent's shared command policy.

Example:

```json
{
  "name": "sample-python-repair",
  "tasks": [
    {
      "id": "unit-tests",
      "prompt": "Fix the failing unit tests without changing public behavior.",
      "commands": [
        {"argv": ["python", "-m", "pytest", "-q"]}
      ]
    }
  ]
}
```

Legacy shell strings such as `"python -m pytest -q"` still work for existing suites, but risky commands are classified and blocked before execution.

Run evals before and after agent changes to build a local confidence trail.
