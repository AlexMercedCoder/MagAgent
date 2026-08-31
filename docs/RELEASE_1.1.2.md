# MagAgent 1.1.2

Released on 2026-08-31.

This patch makes generated Agentic Graph work more reliable and easier to diagnose. Logical
file-read capability declarations now authorize every bounded MagAgent read tool. When a card
successfully satisfies independent file-backed acceptance criteria but returns its single text or
Markdown summary normally, MagAgent records that response as the declared output instead of
reporting a false failure. Unverified prose still fails the graph output contract.

The Graphs UI now includes an expandable, downloadable audit log with lifecycle activity, tool
authorization decisions, retries, criterion evidence, and final status. The exported log omits
tool arguments and secrets. Shell validation also distinguishes quoted HTML/XML comparisons from
real redirection, while continuing to block redirects and heredocs in favor of native file tools.

## Validation

- Full Python unit suite: 1,066 passed and 6 skipped in the restricted sandbox; the 16 loopback
  socket tests that require local networking passed outside it.
- Focused graph execution, Web graph, and shell-policy suite: 106 passed.
- Web UI unit suite: 30 passed, followed by a production build with matching committed assets.
- Targeted Ruff and MyPy checks for the modified Python modules.
- Wheel and source archive build, Twine metadata validation, and clean-wheel smoke testing.
