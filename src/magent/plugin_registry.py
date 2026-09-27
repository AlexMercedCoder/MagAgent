"""Static plugin registries: search, fetch, verify and install signed packs.

A registry is a static JSON file (``magent.plugin-registry.v2``) served from any
web host, a Git repository's raw files, or a local directory. MagAgent only
reads registries; it has no hosted registry and nothing publishes to one::

    {
      "schema": "magent.plugin-registry.v2",
      "name": "acme",
      "plugins": [
        {"name": "release-kit", "version": "1.2.0", "description": "...",
         "archive": "release-kit-1.2.0.tar.gz",        # relative to the index, or a URL
         "digest": "sha256:...",                        # the pack's content digest
         "archive_sha256": "...",                       # the archive file's sha256
         "permissions": ["shell"], "capabilities": ["recipes"],
         "signature": {"key_id": "acme", "public_key": "ed25519:...", "fingerprint": "SHA256:..."}}
      ]
    }

``build_registry`` produces that file (and the archives) from local packs;
``install_from_registry`` downloads an archive, checks its sha256, unpacks it
safely, checks the pack digest and signature, and only then installs it.
"""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from magent import config as _config

REGISTRY_SCHEMA = "magent.plugin-registry.v2"
REGISTRIES_FILE = "plugin-registries.json"
MAX_INDEX_BYTES = 4 * 1024 * 1024
MAX_ARCHIVE_BYTES = 50 * 1024 * 1024


class RegistryError(RuntimeError):
    """A registry operation that cannot proceed; the message says what to do."""


def registries_file() -> Path:
    return _config.CONFIG_DIR / REGISTRIES_FILE


def list_registries() -> dict[str, str]:
    path = registries_file()
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(key): str(value) for key, value in (data.get("registries") or {}).items()}


def add_registry(name: str, location: str) -> dict[str, Any]:
    from magent.plugins import PLUGIN_NAME_RE

    if not PLUGIN_NAME_RE.fullmatch(name):
        raise RegistryError("Registry names use letters, digits, '.', '_' or '-'.")
    fetch_index(location)  # fail now, not at the first search
    registries = list_registries()
    registries[name] = location
    _save(registries)
    return {"ok": True, "name": name, "location": location}


def remove_registry(name: str) -> dict[str, Any]:
    registries = list_registries()
    if name not in registries:
        raise RegistryError(f"No registry called {name!r}. See `magent plugin registry list`.")
    del registries[name]
    _save(registries)
    return {"ok": True, "removed": name}


def _save(registries: dict[str, str]) -> None:
    path = registries_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": "magent.plugin-registries.v1", "registries": registries}, indent=2)
        + "\n",
        encoding="utf-8",
    )


def _is_url(location: str) -> bool:
    return urlparse(location).scheme in {"http", "https"}


def _read(location: str, limit: int) -> bytes:
    if _is_url(location):
        parsed = urlparse(location)
        if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise RegistryError("Registries must use HTTPS (plain HTTP only on loopback).")
        import httpx

        with httpx.stream("GET", location, timeout=60, follow_redirects=True) as response:
            if response.status_code >= 400:
                raise RegistryError(f"{location} returned HTTP {response.status_code}")
            chunks = bytearray()
            for chunk in response.iter_bytes():
                chunks.extend(chunk)
                if len(chunks) > limit:
                    raise RegistryError(f"{location} is larger than {limit} bytes")
            return bytes(chunks)
    path = Path(location).expanduser()
    if path.is_dir():
        path = path / "index.json"
    if not path.exists():
        raise RegistryError(f"{path} does not exist")
    if path.stat().st_size > limit:
        raise RegistryError(f"{path} is larger than {limit} bytes")
    return path.read_bytes()


def fetch_index(location: str) -> dict[str, Any]:
    try:
        index = json.loads(_read(location, MAX_INDEX_BYTES).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as error:
        raise RegistryError(f"{location} is not a registry index: {error}") from error
    if not isinstance(index, dict) or index.get("schema") != REGISTRY_SCHEMA:
        raise RegistryError(f"{location} is not a {REGISTRY_SCHEMA} index")
    if not isinstance(index.get("plugins"), list):
        raise RegistryError(f"{location} has no plugin list")
    return index


def _index_base(location: str) -> str:
    if _is_url(location):
        return location if location.endswith("/") else location.rsplit("/", 1)[0] + "/"
    path = Path(location).expanduser()
    return str(path if path.is_dir() else path.parent)


def search(query: str = "", *, registry: str = "") -> list[dict[str, Any]]:
    registries = list_registries()
    if registry:
        if registry not in registries:
            raise RegistryError(f"No registry called {registry!r}.")
        registries = {registry: registries[registry]}
    if not registries:
        raise RegistryError(
            "No plugin registries are configured. Add one with "
            "`magent plugin registry add <name> <url-or-path>`."
        )
    needle = query.strip().lower()
    results: list[dict[str, Any]] = []
    for name, location in sorted(registries.items()):
        for plugin in fetch_index(location)["plugins"]:
            haystack = " ".join(
                str(plugin.get(key, "")) for key in ("name", "description", "capabilities")
            ).lower()
            if not needle or needle in haystack:
                results.append({**plugin, "registry": name})
    return sorted(results, key=lambda item: (str(item.get("name")), str(item.get("version"))))


def _safe_extract(archive: bytes, target: Path) -> Path:
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as bundle:
        members = bundle.getmembers()
        for member in members:
            if member.issym() or member.islnk() or member.isdev():
                raise RegistryError(f"archive entry {member.name!r} is a link or device")
            destination = (target / member.name).resolve()
            if target.resolve() not in destination.parents and destination != target.resolve():
                raise RegistryError(f"archive entry {member.name!r} escapes the plugin directory")
        try:
            bundle.extractall(target, filter="data")
        except TypeError:  # pragma: no cover - Python without extraction filters
            bundle.extractall(target)  # noqa: S202 - members were checked above
    roots = [item for item in target.iterdir() if item.is_dir()]
    if (target / "magent-plugin.toml").exists():
        return target
    if len(roots) == 1 and (roots[0] / "magent-plugin.toml").exists():
        return roots[0]
    raise RegistryError("the archive does not contain a magent-plugin.toml")


def install_from_registry(
    spec: str,
    *,
    registry: str = "",
    allow_untrusted: bool = False,
    allow_unsigned: bool = False,
    confirm_key: Any = None,
    force: bool = False,
) -> dict[str, Any]:
    """Install ``name`` or ``name@version`` from a configured registry.

    ``confirm_key(entry, verification) -> bool`` is asked when the pack is
    signed by a key that is not trusted yet (the trust prompt); approving adds
    the key to the trust store.
    """

    from magent.plugin_sdk import plugin_digest
    from magent.plugin_signing import trust_key, verify_signature
    from magent.plugins import install_plugin

    name, _, version = spec.partition("@")
    matches = [item for item in search(name, registry=registry) if item.get("name") == name]
    if version:
        matches = [item for item in matches if item.get("version") == version]
    if not matches:
        raise RegistryError(f"No plugin {spec!r} in the configured registries.")
    entry = matches[-1]
    location = list_registries()[entry["registry"]]
    archive_ref = str(entry.get("archive") or "")
    if not archive_ref:
        raise RegistryError(f"{spec} has no archive in its registry entry")
    source = (
        archive_ref
        if _is_url(archive_ref)
        else (
            urljoin(_index_base(location), archive_ref)
            if _is_url(location)
            else str(Path(_index_base(location)) / archive_ref)
        )
    )
    archive = _read(source, MAX_ARCHIVE_BYTES)
    if (
        entry.get("archive_sha256")
        and hashlib.sha256(archive).hexdigest() != entry["archive_sha256"]
    ):
        raise RegistryError("the downloaded archive does not match the registry's sha256")
    with tempfile.TemporaryDirectory(prefix="magent-plugin-") as directory:
        root = _safe_extract(archive, Path(directory))
        digest = plugin_digest(root)
        if entry.get("digest") and digest != entry["digest"]:
            raise RegistryError("the unpacked plugin does not match the registry's digest")
        verification = verify_signature(root)
        status = verification["status"]
        if status == "invalid":
            raise RegistryError(f"signature check failed: {verification.get('reason')}")
        if status == "unsigned" and not allow_unsigned:
            raise RegistryError(
                f"{spec} is not signed. Install it anyway only if you trust its source: "
                "pass --allow-unsigned."
            )
        if status == "untrusted":
            approved = allow_untrusted or bool(confirm_key and confirm_key(entry, verification))
            if not approved:
                raise RegistryError(
                    f"{spec} is signed by key {verification['key_id']!r} "
                    f"({verification['fingerprint']}), which you do not trust. Trust it with "
                    f"`magent plugin trust add {verification['key_id']} {verification['public_key']}` "
                    "after checking the fingerprint with its publisher."
                )
            trust_key(
                str(verification["key_id"] or entry["registry"]),
                verification["public_key"],
                note=f"trusted while installing {spec}",
            )
            verification = verify_signature(root)
        result = install_plugin(root, force=force)
    if not result.get("ok"):
        return result
    return {
        **result,
        "registry": entry["registry"],
        "version": entry.get("version"),
        "signature": verification,
    }


def build_registry(
    packs: list[Path],
    output_dir: Path,
    *,
    name: str,
    sign_key: Path | None = None,
    key_id: str = "",
) -> dict[str, Any]:
    """Write index.json plus one .tar.gz per pack (optionally signing each pack first)."""

    from magent.plugin_sdk import _manifest, plugin_digest, validate_plugin
    from magent.plugin_signing import sign_plugin, verify_signature

    output_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    for pack in packs:
        root = pack.expanduser().resolve()
        report = validate_plugin(root, strict=True)
        if not report["ok"]:
            raise RegistryError(f"{root.name} fails validation: {'; '.join(report['errors'])}")
        if sign_key is not None:
            sign_plugin(root, sign_key, key_id=key_id or name)
        manifest = _manifest(root)
        archive_name = f"{manifest['name']}-{manifest['version']}.tar.gz"
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
            bundle.add(root, arcname=str(manifest["name"]), filter=_strip_owner)
        data = buffer.getvalue()
        (output_dir / archive_name).write_bytes(data)
        signature = verify_signature(root, trusted={})
        entries.append(
            {
                "name": manifest["name"],
                "version": manifest["version"],
                "description": manifest.get("description", ""),
                "archive": archive_name,
                "archive_sha256": hashlib.sha256(data).hexdigest(),
                "digest": plugin_digest(root),
                "permissions": manifest.get("permissions", []),
                "capabilities": manifest.get("capabilities", []),
                "signature": (
                    {
                        "key_id": signature.get("key_id"),
                        "public_key": signature.get("public_key"),
                        "fingerprint": signature.get("fingerprint"),
                    }
                    if signature["status"] != "unsigned"
                    else None
                ),
            }
        )
    index = {
        "schema": REGISTRY_SCHEMA,
        "name": name,
        "generated_at": datetime.now(UTC).isoformat(),
        "plugins": sorted(entries, key=lambda item: (item["name"], item["version"])),
    }
    (output_dir / "index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "index": str(output_dir / "index.json"), "plugins": len(entries)}


def _strip_owner(member: tarfile.TarInfo) -> tarfile.TarInfo:
    member.uid = member.gid = 0
    member.uname = member.gname = ""
    member.mtime = 0
    return member
