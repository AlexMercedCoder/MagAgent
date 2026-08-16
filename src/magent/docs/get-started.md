# Get Started With MagAgent

MagAgent is a terminal assistant that can discuss a project, inspect files, make edits, run
commands, research the web, create documents, and remember useful information. You remain in
control of its provider, tools, permissions, profiles, and memory.

## 1. Set Up MagAgent

Run the guided setup once:

```bash
magent configure
```

Choose a local or cloud provider, a model, and how MagAgent should find credentials. The wizard
explains each choice and tests the connection. Then check the installation:

```bash
magent doctor
```

If a check fails, follow its suggested command. `magent provider wizard` changes the provider or
model later without editing configuration files.

## 2. Open A Project And Start Working

Change into a project directory and start an interactive session:

```bash
cd path/to/project
magent
```

Write requests as you would explain work to a teammate. State the desired result and important
constraints. For example:

```text
Find why the login test fails, fix the smallest root cause, run the related tests, and summarize the changed files.
```

Use `/compose` for a formatted multiline prompt, `/help` for session commands, and `/exit` when
finished. For one task without entering the interactive session:

```bash
magent ask "Explain this repository and identify the main test command"
```

## 3. Understand Permissions

MagAgent shows tool activity and asks before actions that exceed the current permission policy.
Start with `balanced`. It runs low-risk inspection automatically and asks about consequential work.

```bash
magent permission explain balanced
magent permission status
magent mode balanced
```

Profiles can only make permissions more restrictive. A profile that needs web research must allow
the web tools and set network access to `read` or `full`. `read` is sufficient for web search,
research, page fetching, and browser inspection. Use `full` only when arbitrary API methods or
network writes are part of the job.

## 4. Create A Personality Or Specialist

The default `magagent` profile is a general coding and productivity assistant. Create a specialist
without writing an OAP file by hand:

```bash
magent profile wizard
magent profile default
magent profile set-default my-profile
```

The wizard explains personality, model selection, tools, network access, skills, memory, subagents,
and permission ceilings. Run one session with a different profile using `magent --agent NAME`, or
temporarily disable profile injection using `magent --agent none`.

## 5. Research And Memory

Ask for current information directly in chat, or run a dedicated research command:

```bash
magent research "topic" --write
magent memory inbox
magent memory quality
```

Research writes only when you request `--write`. Memory candidates can be reviewed before they
become durable MagGraph knowledge. The memory wizard explains automatic, inbox-first, and manual
modes:

```bash
magent memory wizard
```

## 6. Larger And Repeatable Work

Use a plan when you want to review an approach before implementation. Use a goal for bounded
implementation and verification loops. Use an Agentic Graph for a portable workflow with explicit
dependencies, tool requirements, permissions, budgets, and durable run records.

```bash
magent plan --save "add CSV export and tests"
magent goal "repair the test suite" --orchestrated
magent graph generate "add CSV export and tests" --out work.agraph.yaml
magent graph validate work.agraph.yaml --strict
magent graph plan work.agraph.yaml
magent graph run work.agraph.yaml --project .
```

Review graph files before running them. Graph permissions can restrict MagAgent but cannot grant
more authority than the active user and profile already have.

## 7. Find Help

These commands are safe places to orient yourself:

```bash
magent next
magent --help
magent docs list
magent docs search permissions
magent docs show agents
magent get-started
```

The most useful first habit is simple: ask for a concrete result, let MagAgent show its work, and
check the files or tests it reports before moving on.
