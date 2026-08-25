"""Behaviour tests for the Web UI markdown renderer.

The renderer is browser JavaScript with no build step, so it is exercised here
through Node. If Node is unavailable the tests skip rather than fail, which
keeps a Python-only contributor's suite green while still gating CI, where Node
is present.

The security cases are the important ones: assistant output is untrusted and
can carry a hostile quote from a file, a web page, or a tool result.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

RENDERER = Path(__file__).resolve().parents[2] / "src" / "magent" / "webui" / "markdown.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def render(source: str) -> str:
    """Render `source` through the real renderer in a bare Node context."""
    script = f"""
    globalThis.window = undefined;
    {RENDERER.read_text(encoding="utf-8")}
    const source = JSON.parse(process.argv[1]);
    process.stdout.write(globalThis.MagMarkdown.render(source));
    """
    result = subprocess.run(
        ["node", "-e", script, json.dumps(source)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_renderer_module_loads() -> None:
    assert render("hello") == "<p>hello</p>"


def test_emphasis_and_inline_code_become_elements() -> None:
    html = render("Change **the rate** in `pricing.py`.")
    assert "<strong>the rate</strong>" in html
    assert '<code class="md-code">pricing.py</code>' in html
    assert "**" not in html
    assert "`" not in html


def test_headings_lists_and_rules() -> None:
    html = render("## Findings\n\n- first\n- second\n\n1. one\n2. two\n\n---\n")
    assert "<h2>Findings</h2>" in html
    assert html.count("<li>") == 4
    assert "<ul>" in html and "<ol>" in html
    assert "<hr>" in html


def test_fenced_block_carries_a_copy_control() -> None:
    html = render("```python\nprint('hi')\n```")
    assert 'data-language="python"' in html
    assert "data-md-copy" in html
    assert "<pre><code>print(&#039;hi&#039;)</code></pre>" in html


def test_blockquote_and_strikethrough() -> None:
    html = render("> quoted line\n\n~~gone~~")
    assert "<blockquote>quoted line</blockquote>" in html
    assert "<del>gone</del>" in html


def test_digits_surrounded_by_spaces_survive_code_span_extraction() -> None:
    """The code-span placeholder must not collide with ordinary prose."""
    html = render("step 1 of `run.py` then 0 again")
    assert "step 1 of" in html
    assert "then 0 again" in html
    assert '<code class="md-code">run.py</code>' in html


# --- security ---------------------------------------------------------------


def test_embedded_html_never_becomes_markup() -> None:
    html = render('<img src=x onerror="alert(1)"> and <script>alert(2)</script>')
    assert "<img" not in html
    assert "<script" not in html
    assert "&lt;img" in html
    assert "&lt;script" in html


def test_javascript_url_is_dropped() -> None:
    html = render("[click](javascript:alert(1))")
    assert "javascript:" not in html.lower()
    assert "<a " not in html
    assert "click" in html


def test_data_url_is_dropped() -> None:
    html = render("[x](data:text/html;base64,PHNjcmlwdD4=)")
    assert "<a " not in html
    assert "data:" not in html


def test_external_link_cannot_take_the_opener() -> None:
    html = render("[docs](https://example.com/a)")
    assert 'href="https://example.com/a"' in html
    assert 'rel="noopener noreferrer nofollow ugc"' in html
    assert 'target="_blank"' in html


def test_quotes_in_code_are_escaped() -> None:
    html = render('`"><img src=x>`')
    assert "<img" not in html
    assert "&quot;&gt;&lt;img" in html


def test_attribute_injection_through_a_language_tag_is_escaped() -> None:
    html = render('```py"onload="alert(1)\ncode\n```')
    # The fence regex only accepts word characters, so a hostile "language"
    # never reaches the attribute; the line stays ordinary text.
    assert "onload=" not in html or "&quot;" in html
    assert "<img" not in html
