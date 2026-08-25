import { useCallback, useEffect, useRef, useState } from "react";
import { streamMessage } from "../api";
import { Markdown } from "../Markdown";
import type { ChatEvent, Conversation, Message } from "../types";

function initials(name = "M"): string {
  return name.split(/\s+|[-_]/).map((p) => p[0]).join("").slice(0, 2).toUpperCase() || "M";
}

const STARTERS = [
  "Summarize this project",
  "Help me plan a feature",
  "Review recent changes",
  "Explain the architecture",
];

/** The chat stage: transcript plus composer. Lives inside `.workspace`. */
export function ChatView({
  active,
  refresh,
  setError,
  notify,
}: {
  active: Conversation | null;
  refresh: () => Promise<void>;
  setError: (message: string) => void;
  notify: (message: string) => void;
}) {
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [live, setLive] = useState<Message[]>([]);
  const transcript = useRef<HTMLDivElement>(null);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => {
    const node = transcript.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [active?.messages?.length, live]);

  const send = useCallback(async () => {
    const content = draft.trim();
    if (!content || !active || busy) return;
    setBusy(true);
    setDraft("");

    const settled: Message[] = [
      { id: `local-${Date.now()}`, role: "user", content, speaker: "You", status: "complete" },
    ];
    let streaming: Message = {
      id: `stream-${Date.now()}`,
      role: "assistant",
      content: "",
      speaker: active.profiles?.[0] || "MagAgent",
      status: "streaming",
    };
    setLive([...settled, streaming]);

    const controller = new AbortController();
    abort.current = controller;

    try {
      await streamMessage(
        active.id,
        content,
        (event: ChatEvent) => {
          if (event.type === "chunk") {
            // A group turn hands off between speakers; start a new bubble.
            if (streaming.speaker !== event.speaker && streaming.content) {
              settled.push({ ...streaming, status: "complete" });
              streaming = {
                id: `stream-${Date.now()}-${settled.length}`,
                role: "assistant",
                content: "",
                speaker: event.speaker,
                status: "streaming",
              };
            }
            streaming = {
              ...streaming,
              speaker: event.speaker,
              content: streaming.content + event.content,
            };
            setLive([...settled, streaming]);
          } else if (event.type === "error") {
            streaming = { ...streaming, status: "error", content: event.error };
            setLive([...settled, streaming]);
          }
        },
        controller.signal,
      );
      await refresh();
      setLive([]);
    } catch (problem) {
      if ((problem as Error).name === "AbortError") notify("Turn stopped.");
      else setError((problem as Error).message);
      setLive([]);
    } finally {
      abort.current = null;
      setBusy(false);
    }
  }, [draft, active, busy, refresh, setError, notify]);

  const messages = live.length ? [...(active?.messages ?? []), ...live] : (active?.messages ?? []);

  return (
    <section className="view active chat-view">
      <div
        className="messages"
        ref={transcript}
        role="log"
        aria-label="Conversation transcript"
        aria-live="polite"
        aria-relevant="additions text"
        aria-busy={busy}
      >
        {!messages.length && (
          <div className="welcome">
            <div className="brand-mark large">M</div>
            <h2>Your local AI workspace</h2>
            <p>
              Start a traditional chat, choose a profile-backed bot, or assemble a small group of
              specialists.
            </p>
            <div className="starter-grid">
              {STARTERS.map((prompt) => (
                <button key={prompt} type="button" onClick={() => setDraft(prompt)}>
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((message) => (
          <article
            key={message.id}
            className={`message ${message.role} ${message.status === "error" ? "error" : ""}`}
          >
            <div className="mini-avatar">
              {initials(message.role === "user" ? "You" : message.speaker || "M")}
            </div>
            <div>
              <div className="message-meta">
                {message.role === "user" ? "You" : message.speaker || "MagAgent"}
              </div>
              <div className="message-bubble">
                {message.role === "user" ? message.content : <Markdown>{message.content}</Markdown>}
                {message.status === "streaming" && <span className="typing" />}
              </div>
            </div>
          </article>
        ))}
      </div>

      <div className="composer-wrap">
        <form
          className="composer"
          onSubmit={(event) => {
            event.preventDefault();
            void send();
          }}
        >
          <textarea
            rows={1}
            value={draft}
            disabled={!active}
            placeholder={active ? "Ask MagAgent anything…" : "Start a conversation first"}
            aria-label="Message"
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void send();
              }
            }}
          />
          <div className="composer-footer">
            <div>
              <span className="hint">Enter to send · Shift+Enter for a new line</span>
            </div>
            {busy ? (
              <button
                type="button"
                className="send-button stop"
                onClick={() => abort.current?.abort()}
                aria-label="Stop the turn"
              >
                ■
              </button>
            ) : (
              <button
                type="submit"
                className="send-button"
                disabled={!draft.trim() || !active}
                aria-label="Send message"
              >
                ↑
              </button>
            )}
          </div>
        </form>
        <p className="disclaimer">
          MagAgent can make mistakes. Review consequential changes and tool activity.
        </p>
      </div>
    </section>
  );
}
