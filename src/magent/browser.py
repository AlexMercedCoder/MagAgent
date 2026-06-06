"""Browser automation helpers with Playwright fallback behavior."""

from __future__ import annotations

from pathlib import Path
from typing import Any


async def browser_snapshot(url: str, *, wait_ms: int = 500) -> dict[str, Any]:
    """Capture page title, URL, and text with Playwright when installed."""
    try:
        from playwright.async_api import async_playwright
    except Exception:
        return {"ok": False, "error": "Playwright is not installed", "install": "pip install playwright && playwright install"}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, wait_until="domcontentloaded")
        if wait_ms:
            await page.wait_for_timeout(wait_ms)
        title = await page.title()
        text = await page.locator("body").inner_text(timeout=3000)
        final_url = page.url
        await browser.close()
    return {"ok": True, "url": final_url, "title": title, "text": text[:6000], "truncated": len(text) > 6000}


async def browser_screenshot(url: str, path: str, *, wait_ms: int = 500) -> dict[str, Any]:
    """Capture a screenshot with Playwright when installed."""
    try:
        from playwright.async_api import async_playwright
    except Exception:
        return {"ok": False, "error": "Playwright is not installed", "install": "pip install playwright && playwright install"}
    target = Path(path).expanduser().resolve(strict=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 1000})
        await page.goto(url, wait_until="domcontentloaded")
        if wait_ms:
            await page.wait_for_timeout(wait_ms)
        await page.screenshot(path=str(target), full_page=True)
        final_url = page.url
        title = await page.title()
        await browser.close()
    return {"ok": True, "url": final_url, "title": title, "path": str(target)}
