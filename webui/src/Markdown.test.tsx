import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Markdown, parseBlocks, parseInline } from "./Markdown";

describe("Markdown", () => {
  it("renders emphasis and inline code as elements, not literal characters", () => {
    const { container } = render(<Markdown>{"Change **the rate** in `pricing.py`."}</Markdown>);
    expect(container.querySelector("strong")?.textContent).toBe("the rate");
    expect(container.querySelector("code.md-code")?.textContent).toBe("pricing.py");
    expect(container.textContent).not.toContain("**");
    expect(container.textContent).not.toContain("`");
  });

  it("renders headings, lists and rules", () => {
    const { container } = render(
      <Markdown>{"## Findings\n\n- first\n- second\n\n1. one\n2. two\n\n---\n"}</Markdown>,
    );
    expect(container.querySelector("h2")?.textContent).toBe("Findings");
    expect(container.querySelectorAll("li")).toHaveLength(4);
    expect(container.querySelector("ul")).toBeTruthy();
    expect(container.querySelector("ol")).toBeTruthy();
    expect(container.querySelector("hr")).toBeTruthy();
  });

  it("renders a fenced block with a copy control", () => {
    const { container } = render(<Markdown>{"```python\nprint('hi')\n```"}</Markdown>);
    expect(container.querySelector(".md-fence pre code")?.textContent).toBe("print('hi')");
    expect(container.querySelector(".md-fence")?.getAttribute("data-language")).toBe("python");
    expect(screen.getByRole("button", { name: /copy code/i })).toBeInTheDocument();
  });

  it("renders blockquotes and strikethrough", () => {
    const { container } = render(<Markdown>{"> quoted\n\n~~gone~~"}</Markdown>);
    expect(container.querySelector("blockquote")?.textContent).toContain("quoted");
    expect(container.querySelector("del")?.textContent).toBe("gone");
  });

  it("keeps digits in ordinary prose", () => {
    const { container } = render(<Markdown>{"step 1 of `run.py` then 0 again"}</Markdown>);
    expect(container.textContent).toContain("step 1 of");
    expect(container.textContent).toContain("then 0 again");
  });

  // Model output is untrusted: it can quote a hostile file or a tool result.
  it("never turns embedded HTML into elements", () => {
    const hostile = '<img src=x onerror="window.__pwned=1"> and <script>window.__pwned=2</script>';
    const { container } = render(<Markdown>{hostile}</Markdown>);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect((window as unknown as { __pwned?: number }).__pwned).toBeUndefined();
    expect(container.textContent).toContain("onerror");
  });

  it("drops a javascript: link", () => {
    const { container } = render(<Markdown>{"[click](javascript:alert(1))"}</Markdown>);
    expect(container.querySelector("a")).toBeNull();
    expect(container.textContent).toContain("click");
  });

  it("drops a data: link", () => {
    const { container } = render(<Markdown>{"[x](data:text/html;base64,PHNjcmlwdD4=)"}</Markdown>);
    expect(container.querySelector("a")).toBeNull();
  });

  it("does not let an external link take the opener", () => {
    const { container } = render(<Markdown>{"[docs](https://example.com/a)"}</Markdown>);
    const anchor = container.querySelector("a");
    expect(anchor?.getAttribute("href")).toBe("https://example.com/a");
    expect(anchor?.getAttribute("rel")).toContain("noopener");
    expect(anchor?.getAttribute("target")).toBe("_blank");
  });
});

describe("parsers", () => {
  it("splits blocks by kind", () => {
    const blocks = parseBlocks("# H\n\ntext\n\n```\ncode\n```\n\n- a\n");
    expect(blocks.map((b) => b.kind)).toEqual(["h", "p", "fence", "list"]);
  });

  it("keeps a code span intact through the inline pass", () => {
    const spans = parseInline("a `**not bold**` b");
    expect(spans.find((s) => s.code)?.text).toBe("**not bold**");
  });
});
