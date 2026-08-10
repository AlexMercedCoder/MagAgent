"""One network policy for every outbound request MagAgent makes.

Web tools used to accept any URL at AUTO tier with no validation at all, so
`http://169.254.169.254/…` (cloud credentials), `http://127.0.0.1:7830/api/…`
(MagAgent's own unauthenticated ops UI) and `file:///etc/passwd` via Playwright
were all reachable. Meanwhile the shell classifier carefully asked for
confirmation on `curl -X POST` while `http_request(method="POST")` sailed
through — the same action, two different answers.

This module answers both questions in one place:

    validate_request_url(url)      → raises UrlPolicyError, or returns the URL
    classify_network_action(method, url) → the risk tier that action deserves

Redirects are re-validated per hop, because a check at the entry point means
nothing when `follow_redirects=True` will happily walk to the metadata service.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from magent.permissions import RiskTier

__all__ = [
    "MAX_REDIRECTS",
    "MAX_RESPONSE_BYTES",
    "UrlPolicyError",
    "classify_network_action",
    "read_capped",
    "request_with_policy",
    "validate_request_url",
]

ALLOWED_SCHEMES = {"http", "https"}

# Refused by name as well as by address, so an unavailable resolver is not a bypass.
_LOCAL_HOSTNAMES = {"localhost", "ip6-localhost", "ip6-loopback"}

# Methods that only read.
READ_METHODS = {"GET", "HEAD", "OPTIONS"}

MAX_REDIRECTS = 5
MAX_RESPONSE_BYTES = 5_000_000


class UrlPolicyError(ValueError):
    """A URL was rejected before any request was made."""


def _blocked_reason(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    """Why this resolved address must not be reached, or "" when it is fine."""
    if address.is_loopback:
        return "loopback address"
    if address.is_link_local:
        # 169.254.169.254 is the cloud instance metadata service.
        return "link-local address (cloud metadata range)"
    if address.is_private:
        return "private address"
    if address.is_reserved:
        return "reserved address"
    if address.is_multicast:
        return "multicast address"
    if address.is_unspecified:
        return "unspecified address"
    if getattr(address, "is_site_local", False):
        return "site-local address"
    # IPv4-mapped IPv6 (::ffff:127.0.0.1) hides a loopback behind a v6 literal.
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        return _blocked_reason(mapped)
    return ""


def _resolve(host: str, port: int | None) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Every address `host` resolves to. A name may map to several.

    A resolution *failure* returns nothing rather than raising. Refusing a
    request because our own lookup failed buys no safety — the connection uses
    the same resolver and would fail too — while making every web tool depend
    on DNS being reachable, which breaks offline use and makes behaviour
    load-dependent.
    """
    try:
        return [ipaddress.ip_address(host.strip("[]"))]
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(host, port or 0, proto=socket.IPPROTO_TCP)
    except OSError:
        return []

    addresses = []
    for info in infos:
        candidate = info[4][0]
        try:
            addresses.append(ipaddress.ip_address(candidate))
        except ValueError:
            continue
    return addresses


def validate_request_url(url: str, *, allow_private: bool = False) -> str:
    """Return `url` when it is safe to request, else raise `UrlPolicyError`.

    `allow_private` exists for deliberate local calls (a user pointing a tool at
    their own dev server); it is never set from model-supplied input.
    """
    if not isinstance(url, str) or not url.strip():
        raise UrlPolicyError("URL must be a non-empty string")

    parsed = urlparse(url.strip())

    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise UrlPolicyError(
            f"Scheme {parsed.scheme or '(none)'!r} is not allowed; use http or https"
        )
    if not parsed.hostname:
        raise UrlPolicyError("URL has no host")

    if allow_private:
        return url

    # Names that mean "this machine" are refused by name too, so a resolver
    # that is unavailable cannot turn into a bypass.
    host = parsed.hostname.lower().rstrip(".")
    if host in _LOCAL_HOSTNAMES or host.endswith(".localhost"):
        raise UrlPolicyError(f"Refusing to reach {parsed.hostname}: loopback hostname")

    try:
        port = parsed.port
    except ValueError as error:
        raise UrlPolicyError(f"Invalid port in URL: {error}") from error

    for address in _resolve(parsed.hostname, port):
        reason = _blocked_reason(address)
        if reason:
            raise UrlPolicyError(f"Refusing to reach {parsed.hostname} ({address}): {reason}")

    return url


def classify_network_action(method: str, url: str) -> RiskTier:
    """The tier an outbound request deserves, whatever tool is making it.

    A shell `curl -X POST` and an `http_request(method="POST")` now get the same
    answer.
    """
    normalized = (method or "GET").strip().upper()
    return RiskTier.AUTO if normalized in READ_METHODS else RiskTier.CONFIRM


async def request_with_policy(
    client: object,
    method: str,
    url: str,
    *,
    allow_private: bool = False,
    max_redirects: int = MAX_REDIRECTS,
    **kwargs: object,
) -> object:
    """Perform a request, validating the URL at every redirect hop.

    `httpx`'s own `follow_redirects=True` defeats an entry-point check — the
    entry URL passes, then the redirect walks wherever it likes — so redirects
    are followed by hand and every `Location` is validated first.

    The response is returned *unread* so the caller can cap the body with
    `read_capped`. Callers must close it (`read_capped` does).
    """
    import httpx

    current = validate_request_url(url, allow_private=allow_private)
    kwargs.pop("follow_redirects", None)

    for _ in range(max_redirects + 1):
        request = client.build_request(method.upper(), current, **kwargs)  # type: ignore[attr-defined]
        response = await client.send(request, stream=True, follow_redirects=False)  # type: ignore[attr-defined]

        if not response.is_redirect:
            return response

        location = response.headers.get("location")
        await response.aclose()
        if not location:
            return response

        current = validate_request_url(
            str(httpx.URL(current).join(location)), allow_private=allow_private
        )
        # A 303 redirect becomes a GET without a body, as browsers do.
        if response.status_code == 303:
            method = "GET"
            for body_key in ("content", "json", "data", "files"):
                kwargs.pop(body_key, None)

    raise UrlPolicyError(f"Too many redirects (more than {max_redirects})")


async def read_capped(response: object, limit: int = MAX_RESPONSE_BYTES) -> str:
    """Read a streamed response body with a hard byte cap, then close it.

    Reading `response.text` on an unbounded stream is a memory-exhaustion
    primitive; this stops pulling bytes once `limit` is reached.
    """
    chunks: list[bytes] = []
    total = 0
    try:
        async for chunk in response.aiter_bytes():  # type: ignore[attr-defined]
            chunks.append(chunk)
            total += len(chunk)
            if total >= limit:
                break
    finally:
        await response.aclose()  # type: ignore[attr-defined]

    encoding = getattr(response, "encoding", None) or "utf-8"
    return b"".join(chunks)[:limit].decode(encoding, errors="replace")
