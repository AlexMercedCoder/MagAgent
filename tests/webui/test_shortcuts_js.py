"""Behaviour tests for the Web UI keyboard model.

Exercised through Node against a minimal DOM stub, so the matching rules are
covered without pulling a browser test runner into a Python project. Skips when
Node is absent, which keeps a Python-only contributor's suite green while still
gating CI.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

WEBUI = Path(__file__).resolve().parents[2] / "src" / "magent" / "webui"
SHORTCUTS = WEBUI / "shortcuts.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

HARNESS = """
// Minimal DOM: enough for the module to load and for bindings to resolve.
const listeners = {};
const clicked = [];
const focused = [];
function el(tag, extra) {
  return Object.assign({
    tagName: tag.toUpperCase(),
    click() { clicked.push(this._id || tag); },
    focus() { focused.push(this._id || tag); },
    querySelector: () => null,
    querySelectorAll: () => [],
  }, extra || {});
}
const nodes = {
  '.rail-button[data-view="chat"]': el("button", { _id: "view:chat" }),
  '.rail-button[data-view="graphs"]': el("button", { _id: "view:graphs" }),
  '.composer textarea': el("textarea", { _id: "composer" }),
  'input[placeholder*="Search"]': el("input", { _id: "search" }),
  '.new-actions [data-new="chat"]': el("button", { _id: "new-chat" }),
};
globalThis.window = globalThis;
// Node 21+ defines `navigator` as a read-only global, so a plain
// assignment is silently ignored.
Object.defineProperty(globalThis, "navigator", {
  value: { platform: PLATFORM }, configurable: true, writable: true,
});
globalThis.setTimeout = (fn) => fn();
globalThis.document = {
  querySelector: (sel) => nodes[sel] || null,
  querySelectorAll: () => [],
  getElementById: () => null,
  createElement: (tag) => el(tag, { appendChild() {}, childElementCount: 0 }),
};
globalThis.addEventListener = (name, fn) => { (listeners[name] = listeners[name] || []).push(fn); };
globalThis.removeEventListener = (name, fn) => {
  listeners[name] = (listeners[name] || []).filter((item) => item !== fn);
};

SOURCE

const dispose = globalThis.MagShortcuts.register(globalThis.MagShortcuts.bindings);

function press(spec) {
  let prevented = false;
  const event = Object.assign(
    { metaKey: false, ctrlKey: false, shiftKey: false, altKey: false, target: null },
    spec,
    { preventDefault() { prevented = true; } },
  );
  (listeners.keydown || []).forEach((fn) => fn(event));
  return prevented;
}

const RESULT = RUN;
process.stdout.write(JSON.stringify(RESULT));
"""


def run(js: str, platform: str = '"Win32"') -> object:
    script = (
        HARNESS.replace("SOURCE", SHORTCUTS.read_text(encoding="utf-8"))
        .replace("PLATFORM", platform)
        .replace("RUN", js)
    )
    result = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, timeout=30, check=False
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_modified_binding_runs_and_suppresses_the_default() -> None:
    assert run('press({key:"1",ctrlKey:true})') is True
    assert run('(press({key:"1",ctrlKey:true}), clicked)') == ["view:chat"]


def test_meta_and_ctrl_are_the_same_modifier() -> None:
    assert run('(press({key:"3",metaKey:true}), clicked)') == ["view:graphs"]


def test_bare_key_does_not_trigger_a_modified_binding() -> None:
    assert run('(press({key:"1"}), clicked)') == []


def test_shift_is_part_of_the_match() -> None:
    # Ctrl+Shift+N is New chat; Ctrl+N alone is bound to nothing.
    assert run('(press({key:"n",ctrlKey:true,shiftKey:true}), clicked)') == ["view:chat", "new-chat"]
    assert run('(press({key:"n",ctrlKey:true}), clicked)') == []


def test_alt_combinations_are_left_to_the_os() -> None:
    assert run('(press({key:"1",ctrlKey:true,altKey:true}), clicked)') == []


def test_unmodified_key_is_ignored_while_typing() -> None:
    """Typing "/" in the composer must insert a slash, not open the sheet."""
    assert run('press({key:"/",target:{tagName:"TEXTAREA"}})') is False
    assert run('press({key:"/",target:{tagName:"INPUT"}})') is False
    assert run('press({key:"/",target:{isContentEditable:true,tagName:"DIV"}})') is False


def test_modified_key_still_fires_while_typing() -> None:
    assert run('press({key:"k",ctrlKey:true,target:{tagName:"TEXTAREA"}})') is True


def test_focus_bindings_reach_their_targets() -> None:
    assert run('(press({key:"k",ctrlKey:true}), focused)') == ["composer"]
    assert run('(press({key:"f",ctrlKey:true}), focused)') == ["search"]


def test_disposal_stops_the_listener() -> None:
    assert run('(dispose(), press({key:"1",ctrlKey:true}), clicked)') == []


def test_chord_uses_platform_notation() -> None:
    win = run('globalThis.MagShortcuts.bindings.map(b => globalThis.MagShortcuts.chord(b))')
    assert "Ctrl+K" in win
    assert "Ctrl+Shift+N" in win
    assert "Esc" in win
    mac = run(
        'globalThis.MagShortcuts.bindings.map(b => globalThis.MagShortcuts.chord(b))',
        platform='"MacIntel"',
    )
    assert "⌘K" in mac
    assert "⌘⇧N" in mac
