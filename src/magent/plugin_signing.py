"""Ed25519 signatures and a local trust store for plugin packs.

A signature covers the pack's content digest (every file except the manifest
and the signature itself), a digest of the manifest (so declared permissions
cannot be changed after signing), and the plugin's name and version. It lives
next to the manifest as ``magent-plugin.sig``::

    {"schema": "magent.plugin-signature.v1", "algorithm": "ed25519",
     "key_id": "acme", "public_key": "ed25519:<base64>", "name": "...",
     "version": "...", "digest": "sha256:...", "manifest_digest": "sha256:...",
     "signature": "<base64>"}

Signing keys are ordinary Ed25519 private keys in PEM files you keep yourself
(``magent plugin keygen``). MagAgent never stores private keys. Public keys you
decide to trust live in ``~/.config/magent/trusted-plugin-keys.json``.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from magent import config as _config

SIGNATURE_FILE = "magent-plugin.sig"
MANIFEST_FILE = "magent-plugin.toml"
SIGNATURE_SCHEMA = "magent.plugin-signature.v1"
TRUST_FILE_NAME = "trusted-plugin-keys.json"
KEY_PREFIX = "ed25519:"


def trust_file() -> Path:
    return _config.CONFIG_DIR / TRUST_FILE_NAME


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"), validate=True)


def fingerprint(public_key: str) -> str:
    """Short, human-comparable fingerprint of an ``ed25519:`` public key."""

    raw = _unb64(public_key.removeprefix(KEY_PREFIX))
    return "SHA256:" + base64.b64encode(hashlib.sha256(raw).digest()).decode().rstrip("=")[:22]


def manifest_digest(root: Path) -> str:
    path = root / MANIFEST_FILE
    data = path.read_bytes() if path.exists() else b""
    return "sha256:" + hashlib.sha256(data).hexdigest()


def signed_message(name: str, version: str, digest: str, manifest: str) -> bytes:
    return f"magent-plugin-v1\n{name}\n{version}\n{digest}\n{manifest}\n".encode()


def generate_key(path: Path) -> dict[str, Any]:
    """Write a new Ed25519 private key (PEM, mode 0600) and return its public key."""

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    if path.exists():
        raise FileExistsError(f"{path} already exists; refusing to overwrite a key")
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(pem)
    public = KEY_PREFIX + _b64(
        key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    )
    return {
        "ok": True,
        "private_key": str(path),
        "public_key": public,
        "fingerprint": fingerprint(public),
    }


def _load_private(path: Path) -> Any:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError(f"{path} is not an Ed25519 private key")
    return key


def sign_plugin(root: Path, key_path: Path, *, key_id: str) -> dict[str, Any]:
    """Sign a plugin directory in place (writes magent-plugin.sig)."""

    from cryptography.hazmat.primitives import serialization

    from magent.plugin_sdk import _manifest, plugin_digest

    manifest = _manifest(root)
    name = str(manifest.get("name") or "")
    version = str(manifest.get("version") or "")
    if not name or not version:
        raise ValueError("the manifest needs a name and a version before it can be signed")
    key = _load_private(key_path)
    digest = plugin_digest(root)
    manifest_hash = manifest_digest(root)
    public = KEY_PREFIX + _b64(
        key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    )
    signature = key.sign(signed_message(name, version, digest, manifest_hash))
    document = {
        "schema": SIGNATURE_SCHEMA,
        "algorithm": "ed25519",
        "key_id": key_id,
        "public_key": public,
        "name": name,
        "version": version,
        "digest": digest,
        "manifest_digest": manifest_hash,
        "signature": _b64(signature),
        "signed_at": datetime.now(UTC).isoformat(),
    }
    (root / SIGNATURE_FILE).write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, **{k: v for k, v in document.items() if k != "signature"}}


def verify_signature(root: Path, trusted: dict[str, str] | None = None) -> dict[str, Any]:
    """Check a pack's signature. ``status`` is unsigned, invalid, untrusted or trusted."""

    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    from magent.plugin_sdk import _manifest, pack_symlinks, plugin_digest

    path = root / SIGNATURE_FILE
    if not path.exists():
        return {"status": "unsigned", "ok": False, "reason": "no magent-plugin.sig"}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        public = str(document["public_key"])
        raw_key = _unb64(public.removeprefix(KEY_PREFIX))
        signature = _unb64(str(document["signature"]))
    except (OSError, ValueError, KeyError, TypeError) as error:
        return {"status": "invalid", "ok": False, "reason": f"unreadable signature file: {error}"}
    manifest = _manifest(root)
    name, version = str(manifest.get("name") or ""), str(manifest.get("version") or "")
    digest, manifest_hash = plugin_digest(root), manifest_digest(root)
    try:
        key_fingerprint = fingerprint(public)
    except ValueError as error:
        return {"status": "invalid", "ok": False, "reason": f"unreadable public key: {error}"}
    base = {
        "key_id": document.get("key_id", ""),
        "public_key": public,
        "fingerprint": key_fingerprint,
        "digest": digest,
    }
    links = pack_symlinks(root)
    if links:
        return {
            **base,
            "status": "invalid",
            "ok": False,
            "reason": "signed packs may not contain symlinks: " + ", ".join(links[:5]),
        }
    if (document.get("name"), document.get("version")) != (name, version):
        return {**base, "status": "invalid", "ok": False, "reason": "name or version changed"}
    if document.get("digest") != digest:
        return {**base, "status": "invalid", "ok": False, "reason": "plugin files changed"}
    if document.get("manifest_digest") != manifest_hash:
        return {**base, "status": "invalid", "ok": False, "reason": "manifest changed"}
    try:
        Ed25519PublicKey.from_public_bytes(raw_key).verify(
            signature, signed_message(name, version, digest, manifest_hash)
        )
    except (InvalidSignature, ValueError):
        return {**base, "status": "invalid", "ok": False, "reason": "signature does not verify"}
    keys = trusted if trusted is not None else load_trusted_keys()
    trusted_as = next((key_id for key_id, key in keys.items() if key == public), "")
    if not trusted_as:
        return {
            **base,
            "status": "untrusted",
            "ok": False,
            "reason": "signed by a key you have not trusted",
        }
    return {**base, "status": "trusted", "ok": True, "trusted_as": trusted_as}


def load_trusted_keys() -> dict[str, str]:
    path = trust_file()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    keys = data.get("keys", {}) if isinstance(data, dict) else {}
    return {
        str(key): str(value.get("public_key"))
        for key, value in keys.items()
        if isinstance(value, dict)
    }


def trust_key(key_id: str, public_key: str, *, note: str = "") -> dict[str, Any]:
    if (
        not public_key.startswith(KEY_PREFIX)
        or len(_unb64(public_key.removeprefix(KEY_PREFIX))) != 32
    ):
        raise ValueError("public keys look like ed25519:<base64 of 32 bytes>")
    path = trust_file()
    data: dict[str, Any] = {"schema": "magent.trusted-plugin-keys.v1", "keys": {}}
    if path.exists():
        with contextlib.suppress(ValueError):
            data = json.loads(path.read_text(encoding="utf-8"))
    existing = data.get("keys", {}).get(key_id)
    if isinstance(existing, dict) and existing.get("public_key") not in {None, public_key}:
        # A pack can name any key_id; replacing a trusted key under the same
        # name would silently hand that name's trust to a different key.
        raise ValueError(
            f"a different key is already trusted as {key_id!r} "
            f"({existing.get('fingerprint', '')}); remove it first with "
            f"`magent plugin trust remove {key_id}` if you really mean to replace it"
        )
    data.setdefault("keys", {})[key_id] = {
        "public_key": public_key,
        "fingerprint": fingerprint(public_key),
        "added_at": datetime.now(UTC).isoformat(),
        "note": note,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    with contextlib.suppress(OSError):
        path.chmod(0o600)
    return {"ok": True, "key_id": key_id, "fingerprint": fingerprint(public_key)}


def untrust_key(key_id: str) -> dict[str, Any]:
    path = trust_file()
    if not path.exists():
        return {"ok": False, "error": f"No trusted key called {key_id!r}"}
    data = json.loads(path.read_text(encoding="utf-8"))
    if key_id not in data.get("keys", {}):
        return {"ok": False, "error": f"No trusted key called {key_id!r}"}
    del data["keys"][key_id]
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "removed": key_id}


def list_trusted_keys() -> list[dict[str, Any]]:
    path = trust_file()
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [{"key_id": key, **value} for key, value in sorted(data.get("keys", {}).items())]
