/**
 * Theme selection.
 *
 * Three states, matching how browsers actually behave:
 *   "system"  no stamp on <html>; `prefers-color-scheme` decides
 *   "light"   data-theme="light", wins over a dark OS setting
 *   "dark"    data-theme="dark",  wins over a light OS setting
 *
 * index.html stamps the stored choice before this module loads, so the first
 * paint is already correct.
 */
export type ThemeChoice = "system" | "light" | "dark";

const STORAGE_KEY = "magent-theme";
const ORDER: ThemeChoice[] = ["system", "light", "dark"];

export const themeLabel: Record<ThemeChoice, string> = {
  system: "Match system",
  light: "Light",
  dark: "Dark",
};

/** The rail is 76px wide, so it shows the short form. */
export const themeShort: Record<ThemeChoice, string> = {
  system: "System",
  light: "Light",
  dark: "Dark",
};

export const themeGlyph: Record<ThemeChoice, string> = {
  system: "◐",
  light: "☀",
  dark: "☾",
};

export function readTheme(): ThemeChoice {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored === "light" || stored === "dark" ? stored : "system";
  } catch {
    return "system";
  }
}

export function applyTheme(choice: ThemeChoice): void {
  const root = document.documentElement;
  if (choice === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", choice);
}

export function storeTheme(choice: ThemeChoice): void {
  try {
    if (choice === "system") localStorage.removeItem(STORAGE_KEY);
    else localStorage.setItem(STORAGE_KEY, choice);
  } catch {
    /* non-fatal: the choice simply will not persist */
  }
}

export function nextTheme(choice: ThemeChoice): ThemeChoice {
  return ORDER[(ORDER.indexOf(choice) + 1) % ORDER.length];
}

export function initTheme(): ThemeChoice {
  const choice = readTheme();
  applyTheme(choice);
  return choice;
}
