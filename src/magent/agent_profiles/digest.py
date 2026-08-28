"""Canonical OAP digests."""

from __future__ import annotations

from typing import Any

from oap.validate import canonical_json, profile_digest, spec_digest


def digest_document(document: dict[str, Any]) -> str:
    return profile_digest(document)


def digest_spec(document: dict[str, Any]) -> str:
    return spec_digest(document)


__all__ = ["canonical_json", "digest_document", "digest_spec"]
