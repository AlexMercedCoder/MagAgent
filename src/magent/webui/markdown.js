/**
 * Minimal, dependency-free markdown renderer for assistant messages.
 *
 * Assistant output is markdown. It used to be escaped straight into a text
 * node, so every answer displayed its own `**` markers and backticks.
 *
 * Security posture: model output is untrusted. It can quote a hostile file, a
 * scraped page, or a tool result. Every text run is HTML-escaped *before* any
 * markup is introduced, and the only tags this file ever emits are the fixed
 * set below. Raw HTML in the source is never parsed as HTML, so an embedded
 * `<img onerror>` stays visible text.
 *
 * Supported: ATX headings, fenced and inline code, unordered and ordered
 * lists, blockquotes, horizontal rules, bold, italic, strikethrough, links,
 * and paragraphs. Anything else degrades to escaped text, which is the
 * behaviour this file replaces, so it can never render worse than before.
 */
(function (global) {
  "use strict";

  var ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" };

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (c) {
      return ESCAPES[c];
    });
  }

  // Only http(s) and mailto survive. Anything else — javascript:, data:,
  // vbscript: — is dropped and the link renders as plain text.
  function safeHref(raw) {
    var href = String(raw || "").trim();
    if (/^(https?:|mailto:)/i.test(href)) return href;
    if (/^[/#]/.test(href) && !/^\/\//.test(href)) return href;
    return null;
  }

  // Inline pass. Input is a raw markdown run; output is escaped HTML.
  // Code spans are extracted first so their contents are never treated as
  // markup, then restored after the other inline rules have run.
  function inline(text) {
    var spans = [];
    var work = String(text).replace(/`([^`\n]+)`/g, function (_, code) {
      spans.push('<code class="md-code">' + esc(code) + "</code>");
      return "\u0000" + (spans.length - 1) + "\u0000";
    });

    work = esc(work);

    work = work.replace(/\[([^\]\n]+)\]\(([^)\s]+)\)/g, function (whole, label, href) {
      // `href` came through esc(), so &amp; must be undone before validating.
      var url = safeHref(href.replace(/&amp;/g, "&"));
      if (!url) return label;
      return '<a href="' + esc(url) + '" target="_blank" rel="noopener noreferrer nofollow ugc">' + label + "</a>";
    });

    work = work
      .replace(/\*\*\*([^*\n]+)\*\*\*/g, "<strong><em>$1</em></strong>")
      .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[^*\w])\*([^*\n]+)\*(?![*\w])/g, "$1<em>$2</em>")
      .replace(/(^|[^_\w])_([^_\n]+)_(?![_\w])/g, "$1<em>$2</em>")
      .replace(/~~([^~\n]+)~~/g, "<del>$1</del>");

    return work.replace(/\u0000(\d+)\u0000/g, function (_, index) {
      return spans[Number(index)];
    });
  }

  function fence(code, language) {
    var label = language ? ' data-language="' + esc(language) + '"' : "";
    return (
      '<div class="md-fence"' +
      label +
      '><button type="button" class="md-copy" data-md-copy aria-label="Copy code to clipboard">Copy</button>' +
      "<pre><code>" +
      esc(code.replace(/\n$/, "")) +
      "</code></pre></div>"
    );
  }

  function render(source) {
    var lines = String(source == null ? "" : source).replace(/\r\n?/g, "\n").split("\n");
    var out = [];
    var paragraph = [];
    var list = null; // {tag, items: [[line, ...]]}

    function flushParagraph() {
      if (!paragraph.length) return;
      out.push("<p>" + inline(paragraph.join("\n")).replace(/\n/g, "<br>") + "</p>");
      paragraph = [];
    }

    function flushList() {
      if (!list) return;
      var items = list.items
        .map(function (item) {
          return "<li>" + inline(item.join("\n")).replace(/\n/g, "<br>") + "</li>";
        })
        .join("");
      out.push("<" + list.tag + ">" + items + "</" + list.tag + ">");
      list = null;
    }

    function flushAll() {
      flushParagraph();
      flushList();
    }

    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];

      var fenceMatch = /^\s*```+\s*([\w+-]*)\s*$/.exec(line);
      if (fenceMatch) {
        flushAll();
        var body = [];
        i++;
        for (; i < lines.length; i++) {
          if (/^\s*```+\s*$/.test(lines[i])) break;
          body.push(lines[i]);
        }
        out.push(fence(body.join("\n"), fenceMatch[1]));
        continue;
      }

      if (!line.trim()) {
        flushAll();
        continue;
      }

      var heading = /^(#{1,6})\s+(.*)$/.exec(line);
      if (heading) {
        flushAll();
        var level = heading[1].length;
        out.push("<h" + level + ">" + inline(heading[2].trim()) + "</h" + level + ">");
        continue;
      }

      if (/^\s*(?:---+|\*\*\*+|___+)\s*$/.test(line)) {
        flushAll();
        out.push("<hr>");
        continue;
      }

      var quote = /^\s*>\s?(.*)$/.exec(line);
      if (quote) {
        flushAll();
        var quoted = [quote[1]];
        while (i + 1 < lines.length && /^\s*>\s?/.test(lines[i + 1])) {
          quoted.push(lines[++i].replace(/^\s*>\s?/, ""));
        }
        out.push("<blockquote>" + inline(quoted.join("\n")).replace(/\n/g, "<br>") + "</blockquote>");
        continue;
      }

      var bullet = /^\s*[-*+]\s+(.*)$/.exec(line);
      var ordered = /^\s*\d+[.)]\s+(.*)$/.exec(line);
      if (bullet || ordered) {
        flushParagraph();
        var tag = bullet ? "ul" : "ol";
        if (!list || list.tag !== tag) {
          flushList();
          list = { tag: tag, items: [] };
        }
        list.items.push([(bullet || ordered)[1]]);
        continue;
      }

      // A plain line directly under a list item continues that item.
      if (list && /^\s+\S/.test(line)) {
        list.items[list.items.length - 1].push(line.trim());
        continue;
      }

      flushList();
      paragraph.push(line);
    }

    flushAll();
    return out.join("");
  }

  /**
   * Delegated handler for the copy buttons the renderer emits. Registered once
   * by the app rather than per message, so re-rendering the transcript costs
   * nothing.
   */
  function bindCopy(root) {
    (root || document).addEventListener("click", function (event) {
      var button = event.target.closest ? event.target.closest("[data-md-copy]") : null;
      if (!button) return;
      var block = button.parentElement && button.parentElement.querySelector("pre code");
      if (!block || !global.navigator || !global.navigator.clipboard) return;
      global.navigator.clipboard.writeText(block.textContent).then(
        function () {
          button.textContent = "Copied";
          global.setTimeout(function () {
            button.textContent = "Copy";
          }, 1600);
        },
        function () {
          button.textContent = "Copy failed";
          global.setTimeout(function () {
            button.textContent = "Copy";
          }, 1600);
        }
      );
    });
  }

  global.MagMarkdown = { render: render, escape: esc, bindCopy: bindCopy };
})(typeof window !== "undefined" ? window : globalThis);
