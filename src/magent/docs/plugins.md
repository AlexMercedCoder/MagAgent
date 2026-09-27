# Plugins

Plugins are installable local extension packs for MagAgent.

## Commands

- `magent plugin list`
- `magent plugin install ./my-pack`
- `magent plugin enable my-pack`
- `magent plugin disable my-pack`
- `magent plugin metadata ./my-pack`
- `magent plugin validate ./my-pack`
- `magent plugin verify ./my-pack`
- `magent plugin grant my-pack --scope project --project . --permissions files,web`
- `magent plugin schema --output magent-plugin-v1.json`
- `magent plugin registry-index ./pack-one ./pack-two --output registry.json`
- `magent plugin mcp import ./mcp.toml --name filesystem`
- `magent plugin mcp apply filesystem`
- `magent plugin import opencode ./opencode-pack`
- `magent plugin import claude ./claude-project`
- `magent plugin import codex-skill ./SKILL.md`
- `magent plugin import gemini ./gemini-extension`
- `magent plugin import pi ./pi-package`
- `magent plugin pi bridge pi-package --project . --dry-run`

Installed plugins live under `~/.config/magent/plugins`, and enabled state is recorded in `~/.config/magent/plugins.toml`.
Plugin names are validated before install/import and may contain only letters,
numbers, dots, underscores, and dashes. Path separators are rejected so imported
manifests cannot write outside the plugin directory.

## Pack Layout

```text
my-pack/
  magent-plugin.toml
  agents/
  recipes/
  skills/
  tools/
  mcp.toml
```

`magent-plugin.toml` can use either root fields or a `[plugin]` table:

```toml
[plugin]
name = "my-pack"
version = "1.0.0"
api_version = "1"
magent = ">=0.34.0"
description = "Project workflow helpers"
source_url = "https://example.com/my-pack"
compatibility = ["magent", "mcp"]
capabilities = ["agents", "recipes", "mcp"]
permissions = ["external_process"]
trust = "local"
maintainers = ["your-github-handle"]
```

## Plugin SDK v1

`magent-plugin.toml` is the stable authoring surface for SDK v1. `plugin validate`
checks required fields, known capabilities and permissions, contribution layouts,
MCP and hook TOML, file-size limits, symbolic links, and whether declared permissions
cover the pack's inferred behavior. Compatibility mode warns for omissions in older
packs; newly installed native packs must pass strict validation.

MagAgent calculates one deterministic SHA-256 digest over contribution paths and
contents. Installed/imported packs record that checksum in the manifest. `plugin
verify` detects edits before a pack is enabled. A signature is metadata only until a
trusted signing-root implementation lands; MagAgent never labels an unsigned local
pack as cryptographically verified.

Plugin instructions do not grant authority. `plugin grant` records reviewed
permissions at user or canonical project scope. Built-in tool permissions and MCP
approval policies still apply at execution time. Registry indexes contain source,
compatibility, capability, permission, trust, and digest metadata; they do not install
or execute remote code.

The complete reference pack is in `examples/plugin-sdk/review-pack`.

## Compatibility Imports

MagAgent can normalize and import common agent ecosystem shapes:

- OpenCode-style `agents/*.md`, `.opencode/agents/*.md`, `commands/*.md`, and MCP config.
- Claude-style `CLAUDE.md`, `.claude/agents/*.md`, `.claude/commands/*.md`, and MCP config.
- Gemini-style agents, commands, skills, project instructions, and MCP config.
- Codex-style `SKILL.md` files or skill directories.
- Pi package `skills`, Markdown prompt templates, context files, package metadata, and MCP config.
- MCP configs using `[mcp.servers]`, `[servers]`, or JSON `mcpServers`.
- Foreign metadata from `plugin.json`, `package.json`, `AGENTS.md`, `CLAUDE.md`, and `SKILL.md`.

Imported packs are converted into MagAgent-native `agents/`, `recipes/`, `skills/`, and `mcp.toml` surfaces.

### Pi Runtime Boundary

Pi skills use the Agent Skills standard and import directly. Pi Markdown prompt templates become
MagAgent recipes, while `AGENTS.md`, `CLAUDE.md`, `SYSTEM.md`, and `APPEND_SYSTEM.md` become agent
instructions. Pi TypeScript/JavaScript extensions and themes are preserved under
`compatibility/pi/` and described in `report.json`; MagAgent never imports or executes that code
inside its Python process.

To run preserved extensions, enable the imported plugin, grant `external_process` at user or
canonical project scope, inspect the generated command with `--dry-run`, and then launch the
bridge. The bridge invokes the installed `pi` executable with extension discovery disabled and
only the imported resources passed explicitly:

```bash
magent plugin enable pi-package
magent plugin grant pi-package --scope project --project . --permissions external_process
magent plugin pi bridge pi-package --project . --dry-run
magent plugin pi bridge pi-package --project .
```

The bridge is compatibility through Pi's runtime, not a source-level translation of Pi's
`ExtensionAPI`. Imported packages do not install Node dependencies automatically; review the
package and prepare its dependencies before bridging when required.

Native manifests may also declare `agentic_graph` and `schemas` capabilities. `magent graph export-plugin` creates a valid native pack containing the AGS schemas and bundled authoring skill. An enabled, reviewed plugin may provide `agraph_checkers.py` with a `register(register_external_checker)` function to add named `external` success criteria; enabling that plugin is the explicit trust boundary for loading its Python code.

## MCP Contribution

Enabled plugins with `mcp.toml` contribute MCP servers to runtime config at load time. Existing server names are protected by collision-safe prefixes. To permanently write plugin MCP servers into `~/.config/magent/config.toml`, run `magent plugin mcp apply <name>`.

## Current Integrations

Enabled plugin `agents/` directories are included in agent discovery. Enabled plugin `mcp.toml` files are included in runtime MCP config. Plugin metadata records source URLs, compatibility tags, capabilities, permissions, and trust status so MagAgent can be careful about broader ecosystem installs.

Use plugins for shareable team conventions, specialist agents, reusable recipes, and local MCP/tool configuration bundles.

## Signed plugins and registries

Plugin packs can be signed with Ed25519. A signature covers every file in the pack, the manifest
(so declared permissions cannot change after signing), and the name and version.

Publishers:

```bash
magent plugin keygen ~/keys/acme-plugins.pem          # keep this file private, never commit it
magent plugin sign ./release-kit --key ~/keys/acme-plugins.pem --key-id acme
magent plugin registry build ./release-kit ./docs-kit --out ./site/plugins --name acme
# upload ./site/plugins (index.json and the .tar.gz archives) to any static host
```

Users:

```bash
magent plugin registry add acme https://example.com/plugins/index.json
magent plugin search release
magent plugin install release-kit@1.2.0          # asks before trusting a new signing key
magent plugin trust list
magent plugin verify ~/.config/magent/plugins/release-kit --require-signature
```

Installing from a registry checks the archive's sha256, unpacks it without allowing links,
paths outside the pack, more than 5,000 entries or more than 200 MiB, checks the pack digest
against the index, checks that the archive holds the name and version the index claims, and
verifies the signature on the installed copy. Versions compare numerically (1.10.0 is newer
than 1.9.0); a plain `install NAME` never downgrades an installed plugin (name the version to do
that), and a plugin offered by more than one registry needs `--registry`. Redirects are checked
at every hop, so an HTTPS registry cannot be redirected to plain HTTP. A pack signed by a key
you have not trusted shows the key's fingerprint and the permissions from the signed manifest
(not from the index) and asks before trusting it (`--yes` trusts it without asking; in a
non-interactive shell it refuses). Unsigned packs need `--allow-unsigned`. Registries must use
HTTPS (plain HTTP only on loopback). MagAgent only reads registries: there is no hosted
registry, and nothing is published for you.

A signed pack is installed with its manifest unchanged, so `plugin verify --require-signature`
works on the installed copy, and `plugin enable` refuses a signed pack whose signature no longer
verifies. Signed packs may not contain symlinks. Trusting a key never replaces a different key
already trusted under the same name: remove the old one first.

Trusted keys live in `~/.config/magent/trusted-plugin-keys.json`; registries in
`~/.config/magent/plugin-registries.json`. Private keys are never stored by MagAgent.
