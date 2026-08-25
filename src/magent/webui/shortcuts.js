/**
 * Keyboard model for the local Web UI.
 *
 * The app bound two keys before this: Enter to send, and one dialog handler.
 * For a terminal-native tool that is backwards, so the bindings below are
 * registered once, globally.
 *
 * Two rules keep them from fighting the user:
 *   - a plain single-key binding never fires while a text field has focus, so
 *     typing "/" in the composer types a slash;
 *   - a modified binding still fires there, so Cmd/Ctrl-K works mid-sentence.
 */
(function (global) {
  "use strict";

  var doc = global.document;

  function isTextEntry(target) {
    if (!target || !target.tagName) return false;
    var tag = target.tagName.toLowerCase();
    return tag === "input" || tag === "textarea" || tag === "select" || target.isContentEditable;
  }

  function matches(event, binding) {
    if (String(event.key).toLowerCase() !== String(binding.key).toLowerCase()) return false;
    var mod = event.metaKey || event.ctrlKey;
    if (Boolean(binding.mod) !== mod) return false;
    if (Boolean(binding.shift) !== event.shiftKey) return false;
    if (event.altKey) return false; // leave Alt to the OS
    return true;
  }

  function register(bindings) {
    function onKeyDown(event) {
      for (var i = 0; i < bindings.length; i++) {
        var binding = bindings[i];
        if (!matches(event, binding)) continue;
        if (!binding.mod && String(binding.key).length === 1 && isTextEntry(event.target)) continue;
        event.preventDefault();
        binding.run(event);
        return;
      }
    }
    global.addEventListener("keydown", onKeyDown);
    return function () {
      global.removeEventListener("keydown", onKeyDown);
    };
  }

  /** Render a binding the way the host platform writes it. */
  function chord(binding) {
    var mac = global.navigator && /Mac|iPhone|iPad/.test(global.navigator.platform || "");
    var parts = [];
    if (binding.mod) parts.push(mac ? "⌘" : "Ctrl");
    if (binding.shift) parts.push(mac ? "⇧" : "Shift");
    parts.push(binding.key === "Escape" ? "Esc" : String(binding.key).toUpperCase());
    return parts.join(mac ? "" : "+");
  }

  function view(name) {
    var button = doc.querySelector('.rail-button[data-view="' + name + '"]');
    if (button) button.click();
  }

  function focusComposer() {
    view("chat");
    global.setTimeout(function () {
      var box = doc.querySelector(".composer textarea");
      if (box) box.focus();
    }, 0);
  }

  function closeTopmost() {
    var open = doc.querySelector("dialog[open]");
    if (open && typeof open.close === "function") {
      open.close();
      return;
    }
    var sheet = doc.getElementById("shortcutsSheet");
    if (sheet && sheet.open) sheet.close();
  }

  var BINDINGS = [
    { key: "k", mod: true, describe: "Focus the message box", run: focusComposer },
    { key: "n", mod: true, shift: true, describe: "New chat", run: function () {
        view("chat");
        var button = doc.querySelector('.new-actions [data-new="chat"]');
        if (button) button.click();
      } },
    { key: "f", mod: true, describe: "Search conversations", run: function () {
        view("chat");
        var box = doc.querySelector('input[placeholder*="Search"]');
        if (box) box.focus();
      } },
    { key: "1", mod: true, describe: "Go to Chats", run: function () { view("chat"); } },
    { key: "2", mod: true, describe: "Go to Bots", run: function () { view("bots"); } },
    { key: "3", mod: true, describe: "Go to Graphs", run: function () { view("graphs"); } },
    { key: "4", mod: true, describe: "Go to Profiles", run: function () { view("profiles"); } },
    { key: "5", mod: true, describe: "Go to Settings", run: function () { view("settings"); } },
    { key: "6", mod: true, describe: "Go to Ops", run: function () { view("operations"); } },
    { key: "/", describe: "Show keyboard shortcuts", run: function () { openSheet(); } },
    { key: "Escape", describe: "Close a dialog", run: closeTopmost },
  ];

  function openSheet() {
    var sheet = doc.getElementById("shortcutsSheet");
    if (!sheet) return;
    var body = sheet.querySelector(".shortcuts-body");
    if (body && !body.childElementCount) {
      var list = doc.createElement("ul");
      BINDINGS.concat([
        { key: "Enter", describe: "Send the message" },
        { key: "Enter", shift: true, describe: "Newline in the message box" },
      ]).forEach(function (binding) {
        var row = doc.createElement("li");
        var label = doc.createElement("span");
        label.textContent = binding.describe;
        var keys = doc.createElement("kbd");
        keys.textContent = chord(binding);
        row.appendChild(label);
        row.appendChild(keys);
        list.appendChild(row);
      });
      body.appendChild(list);
    }
    if (typeof sheet.showModal === "function" && !sheet.open) sheet.showModal();
  }

  global.MagShortcuts = { register: register, chord: chord, bindings: BINDINGS, openSheet: openSheet };
})(typeof window !== "undefined" ? window : globalThis);
