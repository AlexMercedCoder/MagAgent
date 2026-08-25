import { useCallback, useEffect, useRef, useState } from "react";
import { activeRun, cancelRun, reattachRun, streamMessage } from "../api";
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
  const [resumed, setResumed] = useState(false);
  const transcript = useRef<HTMLDivElement>(null);
  const abort = useRef<AbortController | null>(null);
  const runId = useRef("");

  useEffect(() => {
    const node = transcript.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [active?.messages?.length, live]);

  /**
   * Consume a run's event stream into the transcript.
   *
   * Shared by sending and by reattaching, because a resumed run has to render
   * exactly the way the original did: the events are the same log.
   */
  const consume = useCallback(
    async (
      begin: (onEvent: (event: ChatEvent) => void, signal: AbortSignal) => Promise<void>,
      opening: Message[],
      speaker: string,
    ) => {
      const settled = [...opening];
      let streaming: Message = {
        id: `stream-${Date.now()}`,
        role: "assistant",
        content: "",
        speaker,
        status: "streaming",
      };
      setLive([...settled, streaming]);

      const controller = new AbortController();
      abort.current = controller;

      try {
        await begin((event: ChatEvent) => {
          if (event.type === "run") {
            // Held so Stop can cancel the work itself rather than just closing
            // this socket and leaving the turn running on the server.
            runId.current = event.id;
          } else if (event.type === "chunk") {
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
          } else if (event.type === "cancelled") {
            streaming = { ...streaming, status: "complete" };
            setLive([...settled, streaming]);
          } else if (event.type === "error") {
            streaming = { ...streaming, status: "error", content: event.error };
            setLive([...settled, streaming]);
          }
        }, controller.signal);
        await refresh();
        setLive([]);
      } catch (problem) {
        // Abandoning the stream is not abandoning the turn: the run keeps going
        // and its reply is still recorded, so this only clears the live view.
        if ((problem as Error).name !== "AbortError") setError((problem as Error).message);
        setLive([]);
      } finally {
        abort.current = null;
        runId.current = "";
        setBusy(false);
      }
    },
    [refresh, setError],
  );

  const send = useCallback(async () => {
    const content = draft.trim();
    if (!content || !active || busy) return;
    setBusy(true);
    setDraft("");
    await consume(
      (onEvent, signal) => streamMessage(active.id, content, onEvent, signal),
      [{ id: `local-${Date.now()}`, role: "user", content, speaker: "You", status: "complete" }],
      active.profiles?.[0] || "MagAgent",
    );
  }, [draft, active, busy, consume]);

  const stop = useCallback(async () => {
    // Cancel the run itself. Aborting only this socket used to leave the turn
    // running on the server, still spending tokens with nobody watching.
    //
    // The stream is deliberately not aborted here. A cancelled run ends its own
    // log, and letting it close normally is what delivers the final transcript;
    // tearing the socket down first threw that away, so the partial reply
    // vanished from the screen and the cancellation was never recorded.
    if (!runId.current) {
      abort.current?.abort();
      return;
    }
    try {
      await cancelRun(runId.current);
      notify("Stopping the turn…");
    } catch (problem) {
      setError((problem as Error).message);
      abort.current?.abort();
    }
  }, [notify, setError]);

  // Reattach to a turn that was still running when this view last went away.
  useEffect(() => {
    setResumed(false);
    if (!active) return;
    let cancelled = false;
    (async () => {
      try {
        const found = await activeRun(active.id);
        // A finished run already wrote its reply into the conversation;
        // replaying its chunks would show the answer twice.
        if (cancelled || !found || found.state !== "running") return;
        setResumed(true);
        setBusy(true);
        runId.current = found.id;
        await consume(
          (onEvent, signal) => reattachRun(found.id, 0, onEvent, signal),
          [],
          active.profiles?.[0] || "MagAgent",
        );
      } catch {
        /* nothing to resume is the normal case, not an error worth showing */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [active, consume]);

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
        {resumed && busy && (
          <p className="run-resumed" role="status">
            Picked this turn back up. It kept running while the view was away.
          </p>
        )}
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
                onClick={() => void stop()}
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
