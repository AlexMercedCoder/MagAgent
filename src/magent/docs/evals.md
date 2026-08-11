# Evals

MagAgent has two eval paths. Legacy verification suites run deterministic commands;
`magent.agent-eval.v1` suites create an isolated repository, run the real AgentSession and
native tool loop, capture lifecycle and usage metrics, and validate results independently.

```bash
magent eval run evals/reliability-offline.json --profile core \
  --report-out core-agent-eval-report.json
magent eval run evals/reliability-offline.json --profile full \
  --report-out full-agent-eval-report.json
magent eval run evals/reliability-live.json --provider nous-portal \
  --model deepseek/deepseek-v4-flash --report-out provider-eval-report.json
```

The offline suite contains 32 representative tasks and does not spend provider quota. The
`core` profile skips document, spreadsheet, presentation, and media tasks that require
optional install extras; CI runs it from a clean base wheel. The `full` profile runs every
task and is the release qualification default. Reports identify the selected profile and
every skipped task so reduced coverage cannot be mistaken for a full pass.

The live suite is intentionally small and qualifies model planning and tool-call
behavior. Reports include success and artifact rates, retries, tool calls, elapsed time,
time to first activity, token/cache/cost data when supplied by the provider, changed files,
and validator evidence. Eval workspaces use temporary logs and memory and are deleted unless
`--keep-workspaces` is supplied.

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

Provider responses formatted as errors, including compatibility adapters that return
`[Provider error: ...]`, fail the task and suite. Existing artifacts cannot turn a provider
failure into a passing result.
