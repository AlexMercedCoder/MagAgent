# MagAgent 1.2.0

Release candidate prepared on 2026-09-06.

This release makes WebMCP a governed, reusable browser capability. MagAgent discovers tools from
reviewed exact HTTPS origins, isolates authenticated browser state per origin, binds calls to the
registry revision the user or agent inspected, and rejects a call when that registry has changed.
The bundled `https://alexmerced.app` integration remains available out of the box.

Users can manage origins and inspect the live registry with `magent webmcp`. Normal agent sessions
receive open, list, call, status, and close tools through the existing profile, permission, AAIS,
and audit boundaries. Read-only hints can reduce friction; mutating and destructive calls remain
confirmation governed.

## Validation

- Complete Python unit and integration suite, including sequential verification of tests affected
  by shared process state.
- Focused WebMCP, tool-safety, CLI-surface, and architecture regression suites.
- Ruff checks and formatting for every modified Python module.
- Wheel and source archive build, Twine metadata validation, and installed-wheel smoke test.

See [WebMCP](WEBMCP.md) for setup, origin policy, command examples, and the security model.
