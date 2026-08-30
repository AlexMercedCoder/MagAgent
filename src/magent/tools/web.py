"""Web search, research, HTTP, and browser capability tools."""

from __future__ import annotations

import json
import re
import warnings
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from magent.browser import (
    WEBMCP_ORIGIN,
    browser_screenshot,
    browser_snapshot,
    webmcp_inspect,
    webmcp_invoke,
)
from magent.net_policy import (
    UrlPolicyError,
    classify_network_action,
    read_capped,
    request_with_policy,
    validate_request_url,
)
from magent.permissions import PermissionResult, RiskTier
from magent.tools.types import ToolResult

_SEARCH_STOP_WORDS = {
    "about",
    "after",
    "again",
    "also",
    "ancient",
    "based",
    "before",
    "complete",
    "create",
    "current",
    "design",
    "from",
    "history",
    "into",
    "modern",
    "please",
    "research",
    "system",
    "that",
    "the",
    "this",
    "timeline",
    "using",
    "with",
}

_LOW_VALUE_SEARCH_DOMAINS = {
    "facebook.com",
    "instagram.com",
    "pinterest.com",
    "tiktok.com",
    "x.com",
}


def _search_terms(query: str) -> list[str]:
    words = re.findall(r"[a-z0-9][a-z0-9-]{2,}", query.lower())
    terms = [word.strip("-") for word in words if word not in _SEARCH_STOP_WORDS]
    return list(dict.fromkeys(term for term in terms if term))


def _clean_search_result(item: dict[str, Any]) -> dict[str, str]:
    return {
        "title": str(item.get("title") or ""),
        "snippet": str(item.get("body") or item.get("snippet") or ""),
        "url": str(item.get("href") or item.get("url") or ""),
    }


def _is_low_value_search_url(url: str) -> bool:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    return any(
        host == domain or host.endswith(f".{domain}") for domain in _LOW_VALUE_SEARCH_DOMAINS
    )


def _rank_search_results(
    query: str,
    raw: list[dict[str, Any]],
    max_results: int,
) -> list[dict[str, str]]:
    terms = _search_terms(query)
    cleaned = [
        result
        for result in (_clean_search_result(item) for item in raw)
        if result["url"] and not _is_low_value_search_url(result["url"])
    ]
    if not terms:
        return cleaned[:max_results]

    scored: list[tuple[int, int, dict[str, str]]] = []
    for index, result in enumerate(cleaned):
        text = f"{result['title']} {result['snippet']} {result['url']}".lower()
        matched = {term for term in terms if term in text}
        required = 1 if len(terms) == 1 else min(2, len(terms))
        if len(matched) < required:
            continue
        score = len(matched) * 10
        if any(term in result["title"].lower() for term in matched):
            score += 4
        if any(term in result["url"].lower() for term in matched):
            score += 2
        scored.append((score, -index, result))
    scored.sort(reverse=True)
    return [result for _score, _index, result in scored[:max_results]]


def _research_summary(topic: str, evidence: list[dict[str, Any]]) -> str:
    """Build a compact non-LLM research summary from source metadata."""
    if not evidence:
        return f"No sources were found for: {topic}"
    lines = [f"Research summary for: {topic}", "", "Sources reviewed:"]
    for index, item in enumerate(evidence, start=1):
        title = item.get("title") or item.get("url") or f"Source {index}"
        url = item.get("url", "")
        snippet = str(item.get("snippet") or item.get("excerpt") or "").replace("\n", " ").strip()
        if len(snippet) > 220:
            snippet = snippet[:220].rstrip() + "..."
        lines.append(f"{index}. {title} - {url}")
        if snippet:
            lines.append(f"   Evidence: {snippet}")
    lines.extend(
        [
            "",
            "Use the source excerpts above for grounded analysis; verify dates and claims before high-stakes decisions.",
        ]
    )
    return "\n".join(lines)


class WebToolsMixin:
    """Web capability implementation mixed into the public tool executor."""

    def _log_tool(self, name: str, desc: str, tier: RiskTier) -> None:
        raise NotImplementedError

    def _check_permission(self, action_description: str, tier: RiskTier) -> PermissionResult:
        raise NotImplementedError

    def _permission_denied(self, perm: PermissionResult) -> ToolResult:
        raise NotImplementedError

    def _path_tier(self, op: str, path: str) -> tuple[Path, RiskTier]:
        raise NotImplementedError

    async def web_search(self, query: str, max_results: int = 8) -> ToolResult:
        """Search the web using DDGS, with a keyless instant-answer fallback."""
        tier = RiskTier.AUTO
        self._log_tool("web_search", query, tier)
        perm = self._check_permission(f"Web search: {query}", tier)
        if not perm.approved:
            return self._permission_denied(perm)

        search_errors: list[str] = []
        max_results = max(1, min(int(max_results), 20))

        try:
            try:
                from ddgs import DDGS as SearchClient

                source = "ddgs"
            except ImportError:
                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore", message=".*duckduckgo_search.*ddgs.*")
                    from duckduckgo_search import DDGS as SearchClient

                source = "duckduckgo-search"

            with SearchClient() as ddgs:
                raw = list(ddgs.text(query, max_results=max_results))
            results = _rank_search_results(query, raw, max_results)
            return {
                "ok": True,
                "query": query,
                "results": results,
                "source": source,
                "raw_count": len(raw),
                "filtered_count": max(0, len(raw) - len(results)),
                "warning": "" if results else "Search returned no relevant results.",
            }
        except Exception as e:
            search_errors.append(str(e))

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(
                    "https://api.duckduckgo.com/",
                    params={"q": query, "format": "json", "no_html": "1"},
                )
                data = response.json()
                fallback_results = []
                if data.get("AbstractText"):
                    fallback_results.append(
                        {
                            "title": data.get("Heading", query),
                            "snippet": data.get("AbstractText"),
                            "url": data.get("AbstractURL"),
                        }
                    )
                for item in data.get("RelatedTopics", [])[:6]:
                    if isinstance(item, dict) and item.get("Text"):
                        fallback_results.append(
                            {
                                "title": item.get("Text", "")[:80],
                                "snippet": item.get("Text"),
                                "url": item.get("FirstURL"),
                            }
                        )
                ranked = _rank_search_results(query, fallback_results, max_results)
                return {
                    "ok": True,
                    "query": query,
                    "results": ranked,
                    "source": "ddg-instant",
                    "raw_count": len(fallback_results),
                    "filtered_count": max(0, len(fallback_results) - len(ranked)),
                    "warning": "" if ranked else "Search returned no relevant results.",
                    "fallback_errors": search_errors,
                }
        except Exception as e:
            search_errors.append(str(e))
            return {"ok": False, "error": "; ".join(error for error in search_errors if error)}

    async def web_fetch(self, url: str, extract_article: bool = True) -> ToolResult:
        """Fetch a URL and extract bounded readable text."""
        tier = classify_network_action("GET", url)
        self._log_tool("web_fetch", url, tier)
        perm = self._check_permission(f"Fetch URL: {url}", tier)
        if not perm.approved:
            return self._permission_denied(perm)

        try:
            validate_request_url(url)
        except UrlPolicyError as e:
            return {"ok": False, "error": str(e), "blocked_by": "network-policy"}

        try:
            async with httpx.AsyncClient(timeout=25) as client:
                response = await request_with_policy(
                    client, "GET", url, headers={"User-Agent": "MagAgent/0.2"}
                )
                raw_html = await read_capped(response)

            if extract_article:
                try:
                    import trafilatura

                    text = (
                        trafilatura.extract(raw_html, include_comments=False, include_tables=True)
                        or ""
                    )
                    if text and len(text) > 200:
                        return {
                            "ok": True,
                            "url": str(response.url),
                            "status": response.status_code,
                            "content": text[:10000],
                            "truncated": len(text) > 10000,
                            "extractor": "trafilatura",
                        }
                except ImportError:
                    pass

            text = re.sub(
                r"<script[^>]*>.*?</script>",
                "",
                raw_html,
                flags=re.DOTALL | re.IGNORECASE,
            )
            text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r"<[^>]+>", "", text)
            text = re.sub(r"\n{3,}", "\n\n", text).strip()
            return {
                "ok": True,
                "url": str(response.url),
                "status": response.status_code,
                "content": text[:8000],
                "truncated": len(text) > 8000,
                "extractor": "html-strip",
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def deep_research(
        self,
        topic: str,
        questions: list[str] | None = None,
        max_sources: int = 6,
        fetch_sources: bool = True,
    ) -> ToolResult:
        """Run a multi-query web research pass with cited evidence packets."""
        tier = RiskTier.AUTO
        self._log_tool("deep_research", topic, tier)
        perm = self._check_permission(f"Deep web research: {topic}", tier)
        if not perm.approved:
            return self._permission_denied(perm)

        research_questions = [q.strip() for q in (questions or []) if str(q).strip()]
        queries = [topic]
        queries.extend(f"{topic} {question}" for question in research_questions[:4])

        seen_urls: set[str] = set()
        sources: list[dict[str, Any]] = []
        search_packets: list[dict[str, Any]] = []
        for query in queries[:5]:
            search = await self.web_search(query, max_results=max(3, min(max_sources, 8)))
            search_packets.append(
                {"query": query, "ok": search.get("ok"), "source": search.get("source")}
            )
            for result in search.get("results", []) if search.get("ok") else []:
                url = str(result.get("url") or "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                sources.append(
                    {
                        "title": result.get("title", ""),
                        "url": url,
                        "snippet": result.get("snippet", ""),
                        "query": query,
                    }
                )
                if len(sources) >= max_sources:
                    break
            if len(sources) >= max_sources:
                break

        evidence: list[dict[str, Any]] = []
        for source in sources:
            packet = dict(source)
            if fetch_sources:
                fetched = await self.web_fetch(source["url"], extract_article=True)
                packet["fetch_ok"] = fetched.get("ok", False)
                packet["status"] = fetched.get("status")
                if fetched.get("ok"):
                    content = str(fetched.get("content", ""))
                    packet["excerpt"] = content[:1600].strip()
                    packet["extractor"] = fetched.get("extractor")
                else:
                    packet["fetch_error"] = fetched.get("error", "")
            evidence.append(packet)

        return {
            "ok": True,
            "topic": topic,
            "questions": research_questions,
            "queries": queries[:5],
            "searches": search_packets,
            "source_count": len(evidence),
            "sources": evidence,
            "summary": _research_summary(topic, evidence),
        }

    async def http_request(
        self,
        method: str,
        url: str,
        headers: dict[str, Any] | None = None,
        body: str | dict[str, Any] | None = None,
        timeout: int = 30,
    ) -> ToolResult:
        """Make an HTTP request with custom headers and an optional body."""
        # Same policy as the shell classifier applies to `curl -X POST`: a
        # mutating method is a confirmation, not an auto-approve.
        tier = classify_network_action(method, url)
        self._log_tool("http_request", f"{method.upper()} {url}", tier)
        perm = self._check_permission(f"HTTP {method.upper()} {url}", tier)
        if not perm.approved:
            return self._permission_denied(perm)

        try:
            validate_request_url(url)
        except UrlPolicyError as e:
            return {"ok": False, "error": str(e), "blocked_by": "network-policy"}

        try:
            kwargs: dict[str, Any] = {"headers": headers or {}}
            if body:
                if isinstance(body, dict):
                    kwargs["json"] = body
                else:
                    kwargs["content"] = body.encode()
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await request_with_policy(client, method, url, **kwargs)
                text = await read_capped(response)
            try:
                data = json.loads(text)
            except Exception:
                data = None
            return {
                "ok": response.is_success,
                "status": response.status_code,
                "headers": dict(response.headers),
                "body_text": text[:5000],
                "body_json": data,
                "truncated": len(text) > 5000,
            }
        except UrlPolicyError as e:
            return {"ok": False, "error": str(e), "blocked_by": "network-policy"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def browser_snapshot(self, url: str, wait_ms: int = 500) -> ToolResult:
        """Capture title and body text from a page with Playwright."""
        tier = classify_network_action("GET", url)
        self._log_tool("browser_snapshot", url, tier)
        perm = self._check_permission(f"Browser snapshot: {url}", tier)
        if not perm.approved:
            return self._permission_denied(perm)
        try:
            # Playwright happily loads file:// and localhost; the policy applies
            # to the browser exactly as it does to httpx.
            validate_request_url(url)
        except UrlPolicyError as e:
            return {"ok": False, "error": str(e), "blocked_by": "network-policy"}
        return await browser_snapshot(url, wait_ms=wait_ms)

    async def browser_screenshot(self, url: str, path: str, wait_ms: int = 500) -> ToolResult:
        """Capture a page screenshot with Playwright."""
        abs_path, tier = self._path_tier("write", path)
        self._log_tool("browser_screenshot", f"{url} -> {abs_path}", tier)
        perm = self._check_permission(f"Browser screenshot: {url}", tier)
        if not perm.approved:
            return self._permission_denied(perm)
        try:
            validate_request_url(url)
        except UrlPolicyError as e:
            return {"ok": False, "error": str(e), "blocked_by": "network-policy"}
        return await browser_screenshot(url, str(abs_path), wait_ms=wait_ms)

    def _alexmerced_webmcp_url(self, path: str = "") -> str:
        requested = str(path or "").strip()
        if not requested:
            return str(getattr(self, "_webmcp_url", WEBMCP_ORIGIN + "/"))
        url = urljoin(WEBMCP_ORIGIN + "/", requested.lstrip("/"))
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc.lower() != "alexmerced.app":
            raise ValueError("The built-in WebMCP bridge only opens https://alexmerced.app.")
        return url

    async def webmcp_open(self, path: str = "/", wait_ms: int = 750) -> ToolResult:
        """Open one alexmerced.app page and discover its live WebMCP tools."""
        try:
            url = self._alexmerced_webmcp_url(path)
        except ValueError as error:
            return {"ok": False, "error": str(error), "blocked_by": "origin-policy"}
        tier = RiskTier.AUTO
        self._log_tool("webmcp_open", url, tier)
        perm = self._check_permission(f"Open alexmerced.app WebMCP page: {url}", tier)
        if not perm.approved:
            return self._permission_denied(perm)
        self._webmcp_url = url
        return await webmcp_inspect(url, wait_ms=wait_ms)

    async def webmcp_list_tools(self, path: str = "", wait_ms: int = 750) -> ToolResult:
        """List live tools on the current or requested alexmerced.app page."""
        return await self.webmcp_open(path or self._alexmerced_webmcp_url(), wait_ms=wait_ms)

    async def webmcp_call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        path: str = "",
        wait_ms: int = 750,
    ) -> ToolResult:
        """Invoke one live alexmerced.app WebMCP tool with explicit mutation approval."""
        try:
            url = self._alexmerced_webmcp_url(path)
        except ValueError as error:
            return {"ok": False, "error": str(error), "blocked_by": "origin-policy"}
        read_prefixes = (
            "list_",
            "get_",
            "search_",
            "read_",
            "describe_",
            "plan_",
            "explain_",
            "test_",
            "evaluate",
            "current",
            "summary",
            "due_",
            "infer_",
            "compute_",
        )
        operation = name.split("_", 1)[-1]
        tier = (
            RiskTier.AUTO
            if name.startswith(read_prefixes) or operation.startswith(read_prefixes)
            else RiskTier.CONFIRM
        )
        self._log_tool("webmcp_call_tool", f"{name} on {url}", tier)
        perm = self._check_permission(f"Call alexmerced.app WebMCP tool {name} on {url}", tier)
        if not perm.approved:
            return self._permission_denied(perm)
        self._webmcp_url = url
        return await webmcp_invoke(url, name, arguments or {}, wait_ms=wait_ms)


__all__ = [
    "WebToolsMixin",
    "browser_screenshot",
    "browser_snapshot",
    "webmcp_inspect",
    "webmcp_invoke",
]
