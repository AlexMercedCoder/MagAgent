// Stamp the stored theme before the bundle parses, so a dark-mode user never
// sees a light flash. Kept as its own file because the Web UI's
// Content-Security-Policy is `script-src 'self'` and forbids inline script.
try {
  var choice = localStorage.getItem("magent-theme");
  if (choice === "light" || choice === "dark") {
    document.documentElement.setAttribute("data-theme", choice);
  }
} catch (error) {
  /* storage can be blocked; the OS setting still applies */
}
