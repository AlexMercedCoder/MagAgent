"""Browser automation helpers with Playwright fallback behavior."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

WEBMCP_ORIGIN = "https://alexmerced.app"
_WEBMCP_MAX_RESULT_BYTES = 2_000_000
_WEBMCP_INIT_SCRIPT = r"""
(() => {
  const tools = new Map();
  const normalize = (first, second) => {
    if (typeof first === "string") return { name: first, ...(second || {}) };
    return first || {};
  };
  const registry = {
    registerTool(first, second) {
      const tool = normalize(first, second);
      if (!tool.name || typeof tool.name !== "string") throw new Error("WebMCP tool requires a name");
      tools.set(tool.name, tool);
      return tool.name;
    },
    unregisterTool(name) { tools.delete(name); },
  };
  Object.defineProperty(globalThis, "__magentWebMCPTools", { value: tools, configurable: true });
  for (const host of [document, navigator]) {
    try {
      Object.defineProperty(host, "modelContext", { value: registry, configurable: true });
    } catch (_) {
      // A native implementation may own this property. The compatibility
      // bridge is only used by browsers that let the harness provide it.
    }
  }
})();
"""


def _missing_webmcp_support() -> dict[str, Any]:
    return {
        "ok": False,
        "error": "WebMCP browser support is not installed (Playwright missing).",
        "install": 'python -m pip install "mag-agent[browser]" && playwright install chromium',
    }


def _canonical_webmcp_origin(value: str, *, configuration: bool = False) -> str:
    parsed = urlsplit(str(value).strip())
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or (configuration and parsed.path not in {"", "/"})
        or (configuration and (parsed.query or parsed.fragment))
    ):
        raise ValueError("WebMCP requires an exact HTTPS origin without credentials.")
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("WebMCP origin contains an invalid port.") from error
    host = (
        f"[{parsed.hostname.casefold()}]" if ":" in parsed.hostname else parsed.hostname.casefold()
    )
    return f"https://{host}" + (f":{port}" if port not in {None, 443} else "")


def normalize_webmcp_origins(origins: Any = None) -> tuple[str, ...]:
    """Return canonical, HTTPS-only origins with the bundled origin as the safe default."""
    configured = origins
    if configured is None:
        configured = os.environ.get("MAGENT_WEBMCP_ORIGINS", "")
    if isinstance(configured, str):
        configured = [item.strip() for item in configured.split(",") if item.strip()]
    if not isinstance(configured, (list, tuple, set)) or not configured:
        configured = [WEBMCP_ORIGIN]
    result: list[str] = []
    for value in configured:
        try:
            origin = _canonical_webmcp_origin(str(value), configuration=True)
        except ValueError:
            continue
        if origin not in result:
            result.append(origin)
    if not result:
        if origins is not None:
            raise ValueError("WebMCP requires at least one exact HTTPS origin.")
        result = [WEBMCP_ORIGIN]
    return tuple(result)


def require_webmcp_url(url: str, allowed_origins: Any = None) -> str:
    allowed = normalize_webmcp_origins(allowed_origins)
    try:
        origin = _canonical_webmcp_origin(url)
    except ValueError:
        origin = ""
    if origin not in allowed:
        raise ValueError(
            "WebMCP navigation is restricted to configured HTTPS origins: " + ", ".join(allowed)
        )
    return url


def _require_alexmerced_url(url: str) -> str:
    """Backward-compatible bundled-origin guard."""
    try:
        return require_webmcp_url(url, [WEBMCP_ORIGIN])
    except ValueError as error:
        raise ValueError(
            "The built-in WebMCP bridge is restricted to https://alexmerced.app."
        ) from error


def _origin_key(origin: str) -> str:
    host = urlsplit(origin).netloc.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", host).strip("-") or "origin"
    return f"{slug}-{hashlib.sha256(origin.encode()).hexdigest()[:8]}"


def _webmcp_profile_dir(origin: str = WEBMCP_ORIGIN) -> Path:
    configured = os.environ.get("MAGENT_WEBMCP_PROFILE", "").strip()
    base = (
        Path(configured).expanduser()
        if configured
        else Path.home() / ".local" / "share" / "magent" / "webmcp"
    )
    return base / _origin_key(origin)


def _webmcp_headless() -> bool:
    return os.environ.get("MAGENT_WEBMCP_HEADLESS", "0").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def webmcp_registry_revision(url: str, tools: list[dict[str, Any]]) -> str:
    canonical = json.dumps({"url": url, "tools": tools}, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


async def _webmcp_page(
    url: str, *, wait_ms: int, allowed_origins: Any = None, headless: bool | None = None
) -> tuple[Any, Any, Any]:
    from playwright.async_api import async_playwright

    require_webmcp_url(url, allowed_origins)
    origin = _canonical_webmcp_origin(url)
    profile = _webmcp_profile_dir(origin)
    profile.mkdir(parents=True, exist_ok=True)
    playwright = await async_playwright().start()
    try:
        context = await playwright.chromium.launch_persistent_context(
            str(profile),
            headless=_webmcp_headless() if headless is None else headless,
            viewport={"width": 1440, "height": 1000},
        )
        await context.add_init_script(_WEBMCP_INIT_SCRIPT)
        page = context.pages[0] if context.pages else await context.new_page()
        response = await page.goto(url, wait_until="domcontentloaded")
        require_webmcp_url(page.url, allowed_origins)
        if response and response.status >= 400:
            raise RuntimeError(f"WebMCP page returned HTTP {response.status}.")
        if wait_ms:
            await page.wait_for_timeout(max(0, min(int(wait_ms), 10_000)))
        return playwright, context, page
    except Exception:
        await playwright.stop()
        raise


async def webmcp_inspect(
    url: str,
    *,
    wait_ms: int = 750,
    allowed_origins: Any = None,
    headless: bool | None = None,
) -> dict[str, Any]:
    """Open an allowlisted page and return its authoritative live WebMCP registry."""
    try:
        from playwright.async_api import async_playwright as _playwright_factory  # noqa: F401
    except Exception:
        return _missing_webmcp_support()
    playwright: Any = None
    context: Any = None
    try:
        playwright, context, page = await _webmcp_page(
            url, wait_ms=wait_ms, allowed_origins=allowed_origins, headless=headless
        )
        tools = await page.evaluate(
            """() => Array.from(globalThis.__magentWebMCPTools?.values?.() || []).map((tool) => ({
              name: tool.name,
              description: tool.description || "",
              inputSchema: tool.inputSchema || {type: "object", properties: {}},
              annotations: tool.annotations || null,
            }))"""
        )
        revision = webmcp_registry_revision(page.url, tools)
        origin = _canonical_webmcp_origin(page.url)
        return {
            "ok": True,
            "schema_version": "webmcp.runtime.v1",
            "origin": origin,
            "url": page.url,
            "title": await page.title(),
            "tool_count": len(tools),
            "tools": tools,
            "registry_revision": revision,
            "browser_profile": str(_webmcp_profile_dir(origin)),
            "visible": not (_webmcp_headless() if headless is None else headless),
        }
    except Exception as error:
        return {"ok": False, "error": str(error), "url": url}
    finally:
        if context is not None:
            await context.close()
        if playwright is not None:
            await playwright.stop()


async def webmcp_invoke(
    url: str,
    name: str,
    arguments: dict[str, Any] | None = None,
    *,
    wait_ms: int = 750,
    allowed_origins: Any = None,
    expected_revision: str = "",
    headless: bool | None = None,
) -> dict[str, Any]:
    """Invoke one exact tool from an allowlisted live registry."""
    try:
        from playwright.async_api import async_playwright as _playwright_factory  # noqa: F401
    except Exception:
        return _missing_webmcp_support()
    playwright: Any = None
    context: Any = None
    try:
        playwright, context, page = await _webmcp_page(
            url, wait_ms=wait_ms, allowed_origins=allowed_origins, headless=headless
        )
        tools = await page.evaluate(
            """() => Array.from(globalThis.__magentWebMCPTools?.values?.() || []).map((tool) => ({
              name: tool.name, description: tool.description || "",
              inputSchema: tool.inputSchema || {type: "object", properties: {}},
              annotations: tool.annotations || null,
            }))"""
        )
        revision = webmcp_registry_revision(page.url, tools)
        if expected_revision and expected_revision != revision:
            return {
                "ok": False,
                "error": "The WebMCP page registry changed. Refresh tools before invoking.",
                "error_code": "WEBMCP_STALE_REGISTRY",
                "expected_revision": expected_revision,
                "registry_revision": revision,
                "available": [item.get("name", "") for item in tools],
                "url": page.url,
            }
        discovered = next((item for item in tools if item.get("name") == name), None)
        if discovered is None:
            return {
                "ok": False,
                "error": f"No WebMCP tool named {name} is registered on this page.",
                "error_code": "WEBMCP_TOOL_NOT_FOUND",
                "available": [item.get("name", "") for item in tools],
                "url": page.url,
            }
        try:
            from jsonschema import Draft202012Validator

            Draft202012Validator(discovered.get("inputSchema") or {}).validate(arguments or {})
        except Exception as error:
            return {
                "ok": False,
                "error": f"WebMCP arguments did not match the live tool schema: {error}",
                "error_code": "WEBMCP_ARGUMENT_VALIDATION_FAILED",
                "url": page.url,
                "tool": name,
                "registry_revision": revision,
            }
        result = await page.evaluate(
            """async ({name, arguments}) => {
              const tool = globalThis.__magentWebMCPTools?.get?.(name);
              if (!tool) {
                return {__bridgeError: `No WebMCP tool named ${name} is registered on this page.`,
                  available: Array.from(globalThis.__magentWebMCPTools?.keys?.() || [])};
              }
              const handler = tool.execute || tool.handler;
              if (typeof handler !== "function") return {__bridgeError: `WebMCP tool ${name} has no callable handler.`};
              return await handler(arguments || {});
            }""",
            {"name": name, "arguments": arguments or {}},
        )
        if isinstance(result, dict) and result.get("__bridgeError"):
            return {
                "ok": False,
                "error": result["__bridgeError"],
                "available": result.get("available", []),
                "url": page.url,
            }
        encoded = json.dumps(result, default=str).encode("utf-8")
        if len(encoded) > _WEBMCP_MAX_RESULT_BYTES:
            return {
                "ok": False,
                "error": f"WebMCP result exceeded {_WEBMCP_MAX_RESULT_BYTES} bytes.",
                "url": page.url,
            }
        return {
            "ok": True,
            "schema_version": "webmcp.runtime.v1",
            "url": page.url,
            "tool": name,
            "registry_revision": revision,
            "result": result,
        }
    except Exception as error:
        return {"ok": False, "error": str(error), "url": url, "tool": name}
    finally:
        if context is not None:
            await context.close()
        if playwright is not None:
            await playwright.stop()


async def browser_snapshot(url: str, *, wait_ms: int = 500) -> dict[str, Any]:
    """Capture page title, URL, and text with Playwright when installed."""
    try:
        from playwright.async_api import async_playwright
    except Exception:
        return {
            "ok": False,
            "error": "Browser support is not installed (Playwright missing).",
            "install": 'python -m pip install "mag-agent[browser]" && playwright install',
        }
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # try/finally: close() only ran on success, so a failed goto left
        # Chromium running for the rest of the session.
        try:
            page = await browser.new_page()
            await page.goto(url, wait_until="domcontentloaded")
            if wait_ms:
                await page.wait_for_timeout(wait_ms)
            title = await page.title()
            text = await page.locator("body").inner_text(timeout=3000)
            final_url = page.url
        finally:
            await browser.close()
    return {
        "ok": True,
        "url": final_url,
        "title": title,
        "text": text[:6000],
        "truncated": len(text) > 6000,
    }


async def browser_screenshot(url: str, path: str, *, wait_ms: int = 500) -> dict[str, Any]:
    """Capture a screenshot with Playwright when installed."""
    try:
        from playwright.async_api import async_playwright
    except Exception:
        return {
            "ok": False,
            "error": "Browser support is not installed (Playwright missing).",
            "install": 'python -m pip install "mag-agent[browser]" && playwright install',
        }
    target = Path(path).expanduser().resolve(strict=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page(viewport={"width": 1440, "height": 1000})
            await page.goto(url, wait_until="domcontentloaded")
            if wait_ms:
                await page.wait_for_timeout(wait_ms)
            await page.screenshot(path=str(target), full_page=True)
            final_url = page.url
            title = await page.title()
        finally:
            await browser.close()
    return {"ok": True, "url": final_url, "title": title, "path": str(target)}
