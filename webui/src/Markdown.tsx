import { memo, useCallback, useState } from "react";

/**
 * Assistant output is markdown. Rendering it is not optional: escaped into a
 * text node, every reply shows its own `**` markers and backticks.
 *
 * This is a deliberately small renderer rather than a dependency, because the
 * bundle ships inside the wheel and the supported subset is fixed.
 *
 * Security posture: model output is untrusted, because it can quote a hostile
 * file, a scraped page, or a tool result. Nothing here is ever inserted as
 * HTML — every node below is created by React, so an embedded `<img onerror>`
 * can only ever become text.
 */

type Inline = { text: string; code?: boolean; strong?: boolean; em?: boolean; del?: boolean; href?: string };

/** Only these schemes survive; anything else renders as plain text. */
function safeHref(raw: string): string | null {
  const href = raw.trim();
  if (/^(https?:|mailto:)/i.test(href)) return href;
  if (/^[/#]/.test(href) && !/^\/\//.test(href)) return href;
  return null;
}

/** Split a run of markdown into styled spans. Code spans win over everything. */
export function parseInline(source: string): Inline[] {
  const out: Inline[] = [];
  const pattern =
    /`([^`\n]+)`|\[([^\]\n]+)\]\(([^)\s]+)\)|\*\*\*([^*\n]+)\*\*\*|\*\*([^*\n]+)\*\*|~~([^~\n]+)~~|(?<![*\w])\*([^*\n]+)\*(?![*\w])|(?<![_\w])_([^_\n]+)_(?![_\w])/g;
  let last = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(source))) {
    if (match.index > last) out.push({ text: source.slice(last, match.index) });
    const [, code, label, href, both, strong, del, em1, em2] = match;
    if (code !== undefined) out.push({ text: code, code: true });
    else if (label !== undefined) {
      const url = safeHref(href ?? "");
      out.push(url ? { text: label, href: url } : { text: label });
    } else if (both !== undefined) out.push({ text: both, strong: true, em: true });
    else if (strong !== undefined) out.push({ text: strong, strong: true });
    else if (del !== undefined) out.push({ text: del, del: true });
    else out.push({ text: (em1 ?? em2) as string, em: true });
    last = pattern.lastIndex;
  }
  if (last < source.length) out.push({ text: source.slice(last) });
  return out;
}

function Spans({ source }: { source: string }) {
  return (
    <>
      {parseInline(source).map((span, index) => {
        const key = `${index}-${span.text.slice(0, 8)}`;
        if (span.code) return <code className="md-code" key={key}>{span.text}</code>;
        if (span.href) {
          return (
            <a key={key} href={span.href} target="_blank" rel="noopener noreferrer nofollow ugc">
              {span.text}
            </a>
          );
        }
        let node = <>{span.text}</>;
        if (span.em) node = <em>{node}</em>;
        if (span.strong) node = <strong>{node}</strong>;
        if (span.del) node = <del>{node}</del>;
        return <span key={key}>{node}</span>;
      })}
    </>
  );
}

function Fence({ code, language }: { code: string; language?: string }) {
  const [copied, setCopied] = useState(false);
  const copy = useCallback(() => {
    void navigator.clipboard
      ?.writeText(code)
      .then(() => {
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1600);
      })
      .catch(() => setCopied(false));
  }, [code]);

  return (
    <div className="md-fence" data-language={language || undefined}>
      <button
        type="button"
        className="md-copy"
        onClick={copy}
        aria-label={copied ? "Copied to clipboard" : "Copy code to clipboard"}
      >
        {copied ? "Copied" : "Copy"}
      </button>
      <pre>
        <code>{code}</code>
      </pre>
    </div>
  );
}

type Block =
  | { kind: "p" | "quote"; text: string }
  | { kind: "h"; level: number; text: string }
  | { kind: "hr" }
  | { kind: "fence"; text: string; language?: string }
  | { kind: "list"; ordered: boolean; items: string[] };

/** Split the source into blocks. Exported so the parser can be tested alone. */
export function parseBlocks(source: string): Block[] {
  const lines = String(source ?? "").replace(/\r\n?/g, "\n").split("\n");
  const blocks: Block[] = [];
  let paragraph: string[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;

  const flushParagraph = () => {
    if (paragraph.length) blocks.push({ kind: "p", text: paragraph.join("\n") });
    paragraph = [];
  };
  const flushList = () => {
    if (list) blocks.push({ kind: "list", ...list });
    list = null;
  };
  const flushAll = () => {
    flushParagraph();
    flushList();
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    const fence = /^\s*```+\s*([\w+-]*)\s*$/.exec(line);
    if (fence) {
      flushAll();
      const body: string[] = [];
      i++;
      for (; i < lines.length; i++) {
        if (/^\s*```+\s*$/.test(lines[i])) break;
        body.push(lines[i]);
      }
      blocks.push({ kind: "fence", text: body.join("\n"), language: fence[1] || undefined });
      continue;
    }

    if (!line.trim()) {
      flushAll();
      continue;
    }

    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      flushAll();
      blocks.push({ kind: "h", level: heading[1].length, text: heading[2].trim() });
      continue;
    }

    if (/^\s*(?:---+|\*\*\*+|___+)\s*$/.test(line)) {
      flushAll();
      blocks.push({ kind: "hr" });
      continue;
    }

    const quote = /^\s*>\s?(.*)$/.exec(line);
    if (quote) {
      flushAll();
      const quoted = [quote[1]];
      while (i + 1 < lines.length && /^\s*>\s?/.test(lines[i + 1])) {
        quoted.push(lines[++i].replace(/^\s*>\s?/, ""));
      }
      blocks.push({ kind: "quote", text: quoted.join("\n") });
      continue;
    }

    const bullet = /^\s*[-*+]\s+(.*)$/.exec(line);
    const ordered = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    if (bullet || ordered) {
      flushParagraph();
      const wantsOrdered = Boolean(ordered);
      if (!list || list.ordered !== wantsOrdered) {
        flushList();
        list = { ordered: wantsOrdered, items: [] };
      }
      list.items.push((bullet || ordered)![1]);
      continue;
    }

    // An indented continuation line belongs to the open list item.
    if (list && /^\s+\S/.test(line)) {
      list.items[list.items.length - 1] += `\n${line.trim()}`;
      continue;
    }

    flushList();
    paragraph.push(line);
  }

  flushAll();
  return blocks;
}

/** Render a run that may contain newlines, preserving them as breaks. */
function Lines({ text }: { text: string }) {
  const parts = text.split("\n");
  return (
    <>
      {parts.map((part, index) => (
        <span key={index}>
          {index > 0 && <br />}
          <Spans source={part} />
        </span>
      ))}
    </>
  );
}

export const Markdown = memo(function Markdown({ children }: { children: string }) {
  const blocks = parseBlocks(children);
  return (
    <div className="md">
      {blocks.map((block, index) => {
        switch (block.kind) {
          case "h": {
            const Tag = `h${Math.min(block.level, 6)}` as "h1";
            return <Tag key={index}><Spans source={block.text} /></Tag>;
          }
          case "hr":
            return <hr key={index} />;
          case "fence":
            return <Fence key={index} code={block.text} language={block.language} />;
          case "quote":
            return <blockquote key={index}><Lines text={block.text} /></blockquote>;
          case "list": {
            const Tag = block.ordered ? "ol" : "ul";
            return (
              <Tag key={index}>
                {block.items.map((item, itemIndex) => (
                  <li key={itemIndex}><Lines text={item} /></li>
                ))}
              </Tag>
            );
          }
          default:
            return <p key={index}><Lines text={block.text} /></p>;
        }
      })}
    </div>
  );
});

export default Markdown;
