"""System information, desktop integration, and image inspection tools."""

from __future__ import annotations

import asyncio
import base64
import io
import shlex
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from magent.permissions import PermissionResult, RiskTier
from magent.tools.types import ToolResult

_NOTIFY_URGENCIES = {"low", "normal", "critical"}


class SystemToolsMixin:
    """System/desktop capability implementation mixed into the tool executor."""

    cwd: str

    def _path_tier(self, op: str, path: str) -> tuple[Path, RiskTier]:
        raise NotImplementedError

    def _log_tool(self, name: str, desc: str, tier: RiskTier) -> None:
        raise NotImplementedError

    def _check_permission(self, action_description: str, tier: RiskTier) -> PermissionResult:
        raise NotImplementedError

    def _permission_denied(self, perm: PermissionResult) -> ToolResult:
        raise NotImplementedError

    if TYPE_CHECKING:

        async def run_shell(self, command: str, timeout: int = 60) -> ToolResult: ...

    async def system_info(self) -> ToolResult:
        """Get CPU, RAM, disk usage, OS information, and Python version."""
        self._log_tool("system_info", "fetching system metrics", RiskTier.SILENT)
        try:
            import psutil

            cpu = psutil.cpu_percent(interval=0.5)
            ram = psutil.virtual_memory()
            disk = psutil.disk_usage(self.cwd)
            return {
                "ok": True,
                "cpu_percent": cpu,
                "ram_total_gb": round(ram.total / 1e9, 2),
                "ram_used_gb": round(ram.used / 1e9, 2),
                "ram_percent": ram.percent,
                "disk_total_gb": round(disk.total / 1e9, 2),
                "disk_used_gb": round(disk.used / 1e9, 2),
                "disk_free_gb": round(disk.free / 1e9, 2),
                "platform": sys.platform,
                "python": sys.version.split()[0],
                "cwd": self.cwd,
            }
        except ImportError:
            return {"ok": False, "error": "psutil not installed. Use install_package('psutil')."}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def notify(self, title: str, message: str, urgency: str = "normal") -> ToolResult:
        """Send a desktop notification after a long-running task."""
        self._log_tool("notify", title, RiskTier.SILENT)

        # `urgency` reaches a command line, so it is validated rather than
        # interpolated.
        if urgency not in _NOTIFY_URGENCIES:
            return {
                "ok": False,
                "error": f"urgency must be one of {', '.join(sorted(_NOTIFY_URGENCIES))}",
            }

        try:
            from plyer import notification

            notification.notify(title=title, message=message, timeout=8)
            return {"ok": True, "title": title, "message": message}
        except ImportError:
            pass

        notify_send = shutil.which("notify-send")
        if notify_send:
            # Exec form, no shell: json.dumps() is JSON quoting, not shell
            # quoting, and bash still expands $(...) inside double quotes — so
            # a title of `$(touch /tmp/pwned)` used to execute.
            proc = await asyncio.create_subprocess_exec(
                notify_send,
                f"--urgency={urgency}",
                "--",
                title,
                message,
                cwd=self.cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode == 0:
                return {"ok": True, "title": title, "message": message}
            return {"ok": False, "error": stderr.decode("utf-8", errors="replace").strip()}

        return {"ok": False, "error": "No notification backend available (plyer or notify-send)"}

    async def clipboard_read(self) -> ToolResult:
        """Read the current system clipboard contents."""
        self._log_tool("clipboard_read", "reading clipboard", RiskTier.SILENT)
        try:
            import pyperclip

            text = pyperclip.paste()
            return {"ok": True, "content": text, "length": len(text)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def clipboard_write(self, text: str) -> ToolResult:
        """Write text to the system clipboard."""
        tier = RiskTier.AUTO
        self._log_tool("clipboard_write", f"{len(text)} chars", tier)
        perm = self._check_permission(f"Write {len(text)} chars to clipboard", tier)
        if not perm.approved:
            return self._permission_denied(perm)
        try:
            import pyperclip

            pyperclip.copy(text)
            return {"ok": True, "length": len(text)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def open_file(self, path: str) -> ToolResult:
        """Open a file in the platform's default application."""
        abs_path, file_tier = self._path_tier("read", path)
        tier = max(RiskTier.AUTO, file_tier)
        self._log_tool("open_file", str(abs_path), tier)
        perm = self._check_permission(f"Open file: {abs_path}", tier)
        if not perm.approved:
            return self._permission_denied(perm)
        opener = shutil.which("xdg-open") or shutil.which("open")
        if not opener:
            return {"ok": False, "error": "No file opener found (xdg-open / open)"}
        return await self.run_shell(f"{opener} {shlex.quote(str(abs_path))}")

    async def read_image(self, path: str) -> ToolResult:
        """Read image metadata and bounded base64 content for vision models."""
        abs_path, tier = self._path_tier("read", path)
        self._log_tool("read_image", str(abs_path), tier)
        perm = self._check_permission(f"Read image {abs_path}", tier)
        if not perm.approved:
            return self._permission_denied(perm)
        try:
            from PIL import Image

            with Image.open(abs_path) as image:
                metadata = {
                    "format": image.format,
                    "mode": image.mode,
                    "size": image.size,
                    "width": image.size[0],
                    "height": image.size[1],
                }
                if image.size[0] > 1024 or image.size[1] > 1024:
                    image.thumbnail((1024, 1024))
                buffer = io.BytesIO()
                image.save(buffer, format=image.format or "PNG")
                encoded = base64.b64encode(buffer.getvalue()).decode()
            return {
                "ok": True,
                "metadata": metadata,
                "base64": encoded,
                "path": str(abs_path),
            }
        except ImportError:
            return {"ok": False, "error": "Pillow not installed. Use install_package('Pillow')."}
        except Exception as e:
            return {"ok": False, "error": str(e)}
