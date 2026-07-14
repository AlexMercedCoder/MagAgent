"""Static built-in tool definition catalog."""

from __future__ import annotations

from typing import Any

from magent.tools.registry import tool_def


def built_in_tool_definitions() -> list[dict[str, Any]]:
    """Return OpenAI-compatible definitions for all built-in tools."""
    definitions = [
        tool_def(
            "read_file",
            "Read the contents of a file.",
            {"path": ("string", "Relative file path")},
        ),
        tool_def(
            "read_file_range",
            "Read a 1-based inclusive range of lines from a file.",
            {
                "path": ("string", "Relative file path"),
                "start_line": ("integer", "First line to read"),
                "end_line": ("integer", "Optional final line to read"),
            },
        ),
        tool_def(
            "outline_file",
            "Return a compact structural outline of a source file.",
            {
                "path": ("string", "Relative file path"),
                "max_symbols": ("integer", "Maximum symbols to return"),
            },
        ),
        tool_def(
            "write_file",
            "Write content to a file (creates or overwrites). Use this for generated pages, docs, scripts, and other file creation.",
            {"path": ("string", "File path"), "content": ("string", "Full file content")},
        ),
        tool_def(
            "create_docx",
            "Create a Word .docx document from structured sections. Prefer this over generating Python scripts for Word documents.",
            {
                "path": ("string", "Output .docx file path"),
                "title": ("string", "Document title"),
                "sections": ("array", "Sections with title, content, and optional bullets"),
                "subtitle": ("string", "Optional subtitle"),
            },
        ),
        tool_def(
            "create_pptx",
            "Create a PowerPoint .pptx presentation from structured slides. Prefer this over generating Python scripts for presentations.",
            {
                "path": ("string", "Output .pptx file path"),
                "title": ("string", "Presentation title"),
                "slides": ("array", "Slides with title, content, and/or bullets"),
                "subtitle": ("string", "Optional subtitle"),
            },
        ),
        tool_def(
            "create_svg",
            "Create an SVG vector image from structured shapes, paths, lines, and text. Prefer this over generating SVGs with shell or Python scripts.",
            {
                "path": ("string", "Output .svg file path"),
                "elements": (
                    "array",
                    "Visual elements with type, position, fill/stroke, text, etc.",
                ),
                "title": ("string", "Optional accessible SVG title"),
                "width": ("integer", "Optional width in pixels"),
                "height": ("integer", "Optional height in pixels"),
            },
        ),
        tool_def(
            "create_diagram",
            "Create a Mermaid diagram file from structured nodes and edges.",
            {
                "path": ("string", "Output .mmd or .md file path"),
                "title": ("string", "Diagram title"),
                "nodes": ("array", "Nodes with id and label"),
                "edges": (
                    "array",
                    "Optional edges with from/source, to/target, and optional label",
                ),
                "direction": ("string", "Optional Mermaid flowchart direction such as TD or LR"),
            },
        ),
        tool_def(
            "create_image",
            "Create a simple PNG/JPEG image from structured shapes and text using local rendering.",
            {
                "path": ("string", "Output image path such as .png or .jpg"),
                "elements": (
                    "array",
                    "Visual elements with type, position, fill/stroke, text, etc.",
                ),
                "title": ("string", "Optional title text"),
                "width": ("integer", "Optional width in pixels"),
                "height": ("integer", "Optional height in pixels"),
                "background": ("string", "Optional background color"),
            },
        ),
        tool_def(
            "generate_image",
            "Generate an AI-created PNG image through the configured image_maker model role.",
            {
                "path": ("string", "Output image path such as .png"),
                "prompt": ("string", "Detailed visual prompt"),
                "aspect_ratio": ("string", "Optional: landscape, portrait, or square"),
                "reference_image": (
                    "string",
                    "Optional local path or URL for image editing/reference",
                ),
            },
        ),
        tool_def(
            "edit_file",
            "Replace an exact string in a file.",
            {
                "path": ("string", None),
                "old_str": ("string", "Exact string to replace"),
                "new_str": ("string", "Replacement string"),
            },
        ),
        tool_def("delete_file", "Delete a file or directory.", {"path": ("string", None)}),
        tool_def(
            "list_dir",
            "List contents of a directory.",
            {"path": ("string", "Path (default: .)")},
        ),
        tool_def(
            "diff_files",
            "Show unified diff between two files.",
            {"path_a": ("string", "First file"), "path_b": ("string", "Second file")},
        ),
        tool_def(
            "compress",
            "Compress a file or directory to zip or tar.gz.",
            {
                "source_path": ("string", None),
                "output_path": ("string", None),
                "format": ("string", "zip or tar.gz (default: zip)"),
            },
        ),
        tool_def(
            "extract",
            "Extract a zip or tar archive.",
            {
                "archive_path": ("string", None),
                "output_dir": ("string", "Where to extract (default: .)"),
            },
        ),
        tool_def(
            "run_shell",
            "Run a shell command in the project directory. Do not use for file creation or edits; use write_file/edit_file instead.",
            {"command": ("string", None), "timeout": ("integer", "Seconds (default 60)")},
        ),
        tool_def(
            "run_python",
            "Execute Python code in an isolated subprocess and return stdout/stderr.",
            {
                "code": ("string", "Python code to run"),
                "timeout": ("integer", "Seconds (default 30)"),
            },
        ),
        tool_def(
            "install_package",
            "Install a Python package via pip (asks user permission first).",
            {
                "package": ("string", "Package name e.g. moviepy"),
                "version": ("string", "Optional pinned version"),
            },
        ),
        tool_def(
            "search_codebase",
            "Search for a pattern in the codebase using ripgrep.",
            {"pattern": ("string", None), "path": ("string", "Directory (default: .)")},
        ),
        tool_def(
            "web_search",
            "Search the web using DuckDuckGo (real results, no API key).",
            {
                "query": ("string", None),
                "max_results": ("integer", "Number of results (default 8)"),
            },
        ),
        tool_def(
            "web_fetch",
            "Fetch a URL and return clean article text using trafilatura.",
            {
                "url": ("string", None),
                "extract_article": ("boolean", "Use trafilatura for clean text (default true)"),
            },
        ),
        tool_def(
            "deep_research",
            "Run multi-query web research, fetch source pages, and return cited evidence packets.",
            {
                "topic": ("string", "Research topic or question"),
                "questions": ("array", "Optional follow-up questions"),
                "max_sources": ("integer", "Maximum sources to collect (default 6)"),
                "fetch_sources": ("boolean", "Fetch and excerpt sources (default true)"),
            },
        ),
        tool_def(
            "http_request",
            "Make any HTTP request (GET/POST/PUT/PATCH/DELETE) with custom headers and body.",
            {
                "method": ("string", "GET POST PUT PATCH DELETE"),
                "url": ("string", None),
                "headers": ("object", "Optional headers dict"),
                "body": ("string", "Optional body (string or JSON string)"),
                "timeout": ("integer", "Seconds (default 30)"),
            },
        ),
        tool_def(
            "browser_snapshot",
            "Capture page title and visible text using Playwright.",
            {
                "url": ("string", "Page URL"),
                "wait_ms": ("integer", "Milliseconds to wait after load"),
            },
        ),
        tool_def(
            "browser_screenshot",
            "Capture a page screenshot using Playwright.",
            {
                "url": ("string", "Page URL"),
                "path": ("string", "Output image path"),
                "wait_ms": ("integer", "Milliseconds to wait after load"),
            },
        ),
        tool_def(
            "json_query",
            "Run a JMESPath query over a JSON file or JSON string.",
            {
                "path_or_json": ("string", "File path or raw JSON string"),
                "query": ("string", "JMESPath expression e.g. items[?active].name"),
            },
        ),
        tool_def("system_info", "Get CPU, RAM, disk usage, OS info, and Python version.", {}),
        tool_def(
            "notify",
            "Send a desktop notification to alert the user.",
            {
                "title": ("string", None),
                "message": ("string", None),
                "urgency": ("string", "low/normal/critical"),
            },
        ),
        tool_def("clipboard_read", "Read the current system clipboard contents.", {}),
        tool_def(
            "clipboard_write", "Write text to the system clipboard.", {"text": ("string", None)}
        ),
        tool_def(
            "open_file", "Open a file in its default application.", {"path": ("string", None)}
        ),
        tool_def(
            "read_image",
            "Read image metadata and base64 encode it for vision models.",
            {"path": ("string", None)},
        ),
        tool_def(
            "db_query",
            "SELECT from a named SQLite database.",
            {
                "sql": ("string", "SELECT statement"),
                "params": ("array", "Optional parameter list"),
                "db_name": ("string", "Database name (default, project name, or custom)"),
            },
        ),
        tool_def(
            "db_execute",
            "INSERT/UPDATE/DELETE/CREATE TABLE in a named SQLite database.",
            {
                "sql": ("string", "SQL statement"),
                "params": ("array", "Optional parameter list"),
                "db_name": ("string", "Database name"),
            },
        ),
        tool_def(
            "db_list_tables",
            "List tables in a named SQLite database.",
            {"db_name": ("string", "Database name (default: 'default')")},
        ),
        tool_def(
            "db_schema",
            "Show columns and types for a table.",
            {"table": ("string", None), "db_name": ("string", "Database name")},
        ),
        tool_def(
            "db_list_databases", "List all SQLite databases created for the current user.", {}
        ),
        tool_def(
            "git_op",
            "Run a git subcommand.",
            {
                "subcommand": ("string", "e.g. status, diff, add -A, commit -m 'msg'"),
                "args": ("array", "Optional extra args"),
            },
        ),
        tool_def(
            "magent_docs_search",
            "Search MagAgent's built-in documentation for command, configuration, and troubleshooting help.",
            {
                "query": ("string", None),
                "limit": ("integer", "Number of results (default 5)"),
            },
        ),
    ]
    return definitions
