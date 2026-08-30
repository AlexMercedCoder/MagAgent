"""Browser automation helpers with Playwright fallback behavior."""

from __future__ import annotations

import os
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


def _require_alexmerced_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc.lower() != "alexmerced.app":
        raise ValueError("The built-in WebMCP bridge is restricted to https://alexmerced.app.")
    return url


def _webmcp_profile_dir() -> Path:
    configured = os.environ.get("MAGENT_WEBMCP_PROFILE", "").strip()
    return (
        Path(configured).expanduser()
        if configured
        else Path.home() / ".local" / "share" / "magent" / "webmcp" / "alexmerced-app"
    )


def _webmcp_headless() -> bool:
    return os.environ.get("MAGENT_WEBMCP_HEADLESS", "0").strip().lower() in {
        "1",
        "true",
        "yes",
    }


async def _webmcp_page(url: str, *, wait_ms: int) -> tuple[Any, Any, Any]:
    from playwright.async_api import async_playwright

    _require_alexmerced_url(url)
    profile = _webmcp_profile_dir()
    profile.mkdir(parents=True, exist_ok=True)
    playwright = await async_playwright().start()
    try:
        context = await playwright.chromium.launch_persistent_context(
            str(profile),
            headless=_webmcp_headless(),
            viewport={"width": 1440, "height": 1000},
        )
        await context.add_init_script(_WEBMCP_INIT_SCRIPT)
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(url, wait_until="domcontentloaded")
        if wait_ms:
            await page.wait_for_timeout(max(0, min(int(wait_ms), 10_000)))
        return playwright, context, page
    except Exception:
        await playwright.stop()
        raise


async def webmcp_inspect(url: str, *, wait_ms: int = 750) -> dict[str, Any]:
    """Open an alexmerced.app page and return its live WebMCP registry."""
    try:
        from playwright.async_api import async_playwright as _playwright_factory  # noqa: F401
    except Exception:
        return _missing_webmcp_support()
    playwright: Any = None
    context: Any = None
    try:
        playwright, context, page = await _webmcp_page(url, wait_ms=wait_ms)
        tools = await page.evaluate(
            """() => Array.from(globalThis.__magentWebMCPTools?.values?.() || []).map((tool) => ({
              name: tool.name,
              description: tool.description || "",
              inputSchema: tool.inputSchema || {type: "object", properties: {}},
              annotations: tool.annotations || null,
            }))"""
        )
        return {
            "ok": True,
            "url": page.url,
            "title": await page.title(),
            "tool_count": len(tools),
            "tools": tools,
            "browser_profile": str(_webmcp_profile_dir()),
            "visible": not _webmcp_headless(),
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
) -> dict[str, Any]:
    """Invoke one tool registered by an alexmerced.app page."""
    try:
        from playwright.async_api import async_playwright as _playwright_factory  # noqa: F401
    except Exception:
        return _missing_webmcp_support()
    playwright: Any = None
    context: Any = None
    try:
        playwright, context, page = await _webmcp_page(url, wait_ms=wait_ms)
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
        import json

        encoded = json.dumps(result, default=str).encode("utf-8")
        if len(encoded) > _WEBMCP_MAX_RESULT_BYTES:
            return {
                "ok": False,
                "error": f"WebMCP result exceeded {_WEBMCP_MAX_RESULT_BYTES} bytes.",
                "url": page.url,
            }
        return {"ok": True, "url": page.url, "tool": name, "result": result}
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
