"""Canonical OAP digests."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def digest_document(document: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(document)).hexdigest()


def digest_spec(document: dict[str, Any]) -> str:
    pinned = {"metadata": document.get("metadata", {}), "spec": document.get("spec", {})}
    return digest_document(pinned)
