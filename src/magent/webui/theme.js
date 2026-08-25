/**
 * Theme selection for the local Web UI.
 *
 * The stylesheet was authored light-only and ignored the OS setting. It now has
 * three states, matching how browsers actually behave:
 *
 *   "system"  no stamp on <html>; `prefers-color-scheme` decides
 *   "light"   data-theme="light", wins over a dark OS setting
 *   "dark"    data-theme="dark",  wins over a light OS setting
 *
 * `apply` runs before first paint (the script is loaded in <head> without
 * defer for exactly this reason) so a dark-mode user never sees a light flash.
 */
(function (global) {
  "use strict";

  var KEY = "magent-theme";
  var ORDER = ["system", "light", "dark"];
  var LABEL = { system: "Match system", light: "Light", dark: "Dark" };
  // The rail is narrow; the tooltip and aria-label keep the full wording.
  var SHORT = { system: "System", light: "Light", dark: "Dark" };
  var GLYPH = { system: "◐", light: "☀", dark: "☾" };

  function read() {
    try {
      var stored = global.localStorage && global.localStorage.getItem(KEY);
      return stored === "light" || stored === "dark" ? stored : "system";
    } catch (error) {
      return "system"; // storage can be blocked; the OS setting still works
    }
  }

  function apply(choice) {
    var root = global.document && global.document.documentElement;
    if (!root) return;
    if (choice === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", choice);
  }

  function store(choice) {
    try {
      if (choice === "system") global.localStorage.removeItem(KEY);
      else global.localStorage.setItem(KEY, choice);
    } catch (error) {
      /* non-fatal: the choice simply will not persist */
    }
  }

  function next(choice) {
    return ORDER[(ORDER.indexOf(choice) + 1) % ORDER.length];
  }

  /** Wire a button to cycle the theme and keep its label in sync. */
  function bind(button) {
    if (!button) return;
    var choice = read();

    function paint() {
      button.innerHTML = "";
      var glyph = global.document.createElement("span");
      glyph.setAttribute("aria-hidden", "true");
      glyph.textContent = GLYPH[choice];
      var label = global.document.createElement("i");
      label.textContent = SHORT[choice];
      button.appendChild(glyph);
      button.appendChild(label);
      button.setAttribute("aria-label", "Theme: " + LABEL[choice] + ". Activate to change.");
      button.setAttribute("title", "Theme: " + LABEL[choice]);
    }

    button.addEventListener("click", function () {
      choice = next(choice);
      apply(choice);
      store(choice);
      paint();
    });
    paint();
  }

  apply(read()); // before first paint
  global.MagTheme = { read: read, apply: apply, store: store, next: next, bind: bind };
})(typeof window !== "undefined" ? window : globalThis);
