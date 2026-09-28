import { readdirSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * UI-6: every font stack must end in a generic family (or be `inherit` / a
 * `var(--font-*)` token defined with one), so a machine without the named
 * font still gets a predictable face. The UI used to name Inter and Georgia,
 * ship neither, and render differently on every machine.
 */
const GENERIC = new Set([
  "serif",
  "sans-serif",
  "monospace",
  "cursive",
  "fantasy",
  "system-ui",
  "ui-serif",
  "ui-sans-serif",
  "ui-monospace",
  "ui-rounded",
  "math",
  "emoji",
  "fangsong",
]);
const KEYWORDS = new Set(["inherit", "initial", "unset", "revert", "revert-layer"]);

function cssFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) =>
    entry.isDirectory() ? cssFiles(join(dir, entry.name)) : entry.name.endsWith(".css") ? [join(dir, entry.name)] : [],
  );
}

/** The family list of a `font-family` value or a `font` shorthand. */
export function familyList(property: string, value: string): string | null {
  const text = value.replace(/!important/g, "").trim();
  if (property === "font-family") return text;
  if (KEYWORDS.has(text) || text.startsWith("var(")) return null;
  // font: [style] [weight] size[/line-height] family-list
  const match = text.match(/(?:^|\s)[\d.]+(?:px|em|rem|%|pt|vh|vw)(?:\/\S+)?\s+(.+)$/);
  return match ? match[1] : null;
}

export function lacksGenericFallback(list: string): boolean {
  const families = list.split(",").map((item) => item.trim().replace(/^["']|["']$/g, ""));
  const last = families[families.length - 1];
  return !(GENERIC.has(last) || KEYWORDS.has(last) || /^var\(--font-[a-z]+\)$/.test(last));
}

describe("font stacks", () => {
  const root = resolve(__dirname);
  const files = cssFiles(root);

  it("finds the stylesheets", () => {
    expect(files.some((file) => file.endsWith("styles.css"))).toBe(true);
  });

  it("every font-family and font shorthand ends in a generic family", () => {
    const problems: string[] = [];
    for (const file of files) {
      const css = readFileSync(file, "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
      // @font-face declares a family name; it is not a stack.
      const withoutFaces = css.replace(/@font-face\s*{[^}]*}/g, "");
      for (const match of withoutFaces.matchAll(/(?:^|[;{\s])(font-family|font)\s*:\s*([^;}]+)/g)) {
        const list = familyList(match[1], match[2]);
        if (list && lacksGenericFallback(list)) problems.push(`${file}: ${match[1]}: ${match[2].trim()}`);
      }
      for (const match of css.matchAll(/--font-[a-z]+\s*:\s*([^;}]+)/g)) {
        if (lacksGenericFallback(match[1])) problems.push(`${file}: ${match[0].trim()}`);
      }
    }
    expect(problems).toEqual([]);
  });

  it("catches a stack with no fallback", () => {
    expect(lacksGenericFallback("Georgia")).toBe(true);
    expect(lacksGenericFallback('"Inter", sans-serif')).toBe(false);
    expect(familyList("font", "700 13px/1.4 Georgia")).toBe("Georgia");
  });
});
