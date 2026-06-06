# Evals

MagAgent includes a small local eval harness for repeatable repository tasks.

Commands:

- `magent eval init`
- `magent eval list`
- `magent eval run evals/magagent-evals.json`
- `magent eval report`

An eval suite is a JSON file with tasks, prompts, and verification commands. The harness does not judge model quality by itself; it gives you a repeatable task/check scaffold so MagAgent changes can be compared over time.

Example:

```json
{
  "name": "sample-python-repair",
  "tasks": [
    {
      "id": "unit-tests",
      "prompt": "Fix the failing unit tests without changing public behavior.",
      "commands": ["python -m pytest -q"]
    }
  ]
}
```

Run evals before and after agent changes to build a local confidence trail.
