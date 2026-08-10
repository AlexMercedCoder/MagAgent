# AGS 1.0 Authoring Reference

Node types are `task`, `decision`, `gate`, `loop`, `map`, and `subgraph`. Conformance levels are cumulative: level 0 validates and plans; level 1 executes tasks and gates; level 2 adds decisions, conditions, budgets, and parallelism; level 3 adds composition, judges, compensation, records, and resume.

Use `${{ expression }}` in templates and plain AGX expressions in `when`, decision branches, expression criteria, loop conditions, and map `over`. AGX is strictly typed and supports no host-language evaluation.

Useful commands:

```bash
magent graph validate plan.agraph.yaml --strict
magent graph plan plan.agraph.yaml --json
magent graph add plan.agraph.yaml
magent graph run plan.agraph.yaml --params '{"target":"v2"}'
magent graph status <run-id>
magent graph resume <run-id> --file plan.agraph.yaml
magent graph export-plan <plan-id> --out exported.agraph.yaml
magent graph export-recipe docs-audit --out docs-audit.fragment.json
```

MagAgent records the requested and effective route for every attempt. Graph permissions are requests and are always intersected with local MagAgent policy.
