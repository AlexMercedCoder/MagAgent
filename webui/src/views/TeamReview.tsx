import { useCallback, useEffect, useState } from "react";
import { post, request } from "../api";

/**
 * Team memory review inbox.
 *
 * Nodes only reach the shared team graph as proposals a teammate accepts.
 * This lists what is waiting, shows the node diff and the automatic checks,
 * and records an accept or reject (with an optional reason).
 */

type Change = { status: string; path: string };
type Proposal = { id: string; author: string; title: string; created_at: string; changes: Change[] };
type Inbox = {
  ok?: boolean;
  configured?: boolean;
  user?: string;
  note?: string;
  error?: string;
  proposals?: Proposal[];
  status?: { remote?: string; nodes?: number };
};
type Detail = {
  ok?: boolean;
  error?: string;
  id?: string;
  author?: string;
  title?: string;
  diff?: string;
  checks?: { ok: boolean; problems: string[] };
};

const STATUS: Record<string, string> = { A: "new", M: "changed", D: "removed" };

export function TeamReview({ setError, notify }: { setError: (message: string) => void; notify: (message: string) => void }) {
  const [inbox, setInbox] = useState<Inbox | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setInbox(await request<Inbox>("/api/memory/team/inbox"));
    } catch (problem) {
      setError((problem as Error).message);
    }
  }, [setError]);

  useEffect(() => {
    void load();
  }, [load]);

  async function open(id: string) {
    try {
      setReason("");
      setDetail(await request<Detail>(`/api/memory/team/proposal?id=${encodeURIComponent(id)}`));
    } catch (problem) {
      setError((problem as Error).message);
    }
  }

  async function decide(decision: "accept" | "reject") {
    if (!detail?.id) return;
    setBusy(true);
    try {
      const result = await post<{ ok: boolean; error?: string }>("/api/memory/team/decide", { id: detail.id, decision, reason });
      if (!result.ok) throw new Error(result.error || "The decision was not recorded.");
      notify(decision === "accept" ? "Proposal merged into the team graph" : "Proposal rejected");
      setDetail(null);
      await load();
    } catch (problem) {
      setError((problem as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!inbox) return null;
  const proposals = inbox.proposals ?? [];
  const own = detail?.author && detail.author === inbox.user;
  return (
    <section className="detail-card team-review" aria-labelledby="team-review-title">
      <div className="team-review-head">
        <div>
          <h2 id="team-review-title">Team review</h2>
          <p>
            {inbox.configured
              ? `Proposals for the shared team graph${inbox.status?.nodes !== undefined ? ` (${inbox.status.nodes} reviewed nodes)` : ""}. A teammate must accept a proposal before it is shared.`
              : inbox.note}
          </p>
        </div>
        {inbox.configured && <button className="secondary-button" type="button" onClick={() => void load()}>Refresh</button>}
      </div>
      {inbox.error && <div className="graph-error" role="alert">{inbox.error}</div>}
      {inbox.configured && proposals.length === 0 && !inbox.error && (
        <p className="memory-empty">Nothing is waiting for review. Share a node with <code>magent memory team propose &lt;node-id&gt;</code>.</p>
      )}
      {proposals.length > 0 && (
        <ul className="team-proposals">
          {proposals.map((item) => (
            <li key={item.id}>
              <button type="button" className={detail?.id === item.id ? "active" : ""} aria-pressed={detail?.id === item.id} onClick={() => void open(item.id)}>
                <strong>{item.title}</strong>
                <small>
                  {item.author} · {item.changes.map((change) => `${change.path.replace(/^nodes\//, "").replace(/\.md$/, "")} (${STATUS[change.status] || change.status})`).join(", ")}
                </small>
              </button>
            </li>
          ))}
        </ul>
      )}
      {detail && (
        <div className="team-proposal-detail">
          {detail.error ? (
            <div className="graph-error" role="alert">{detail.error}</div>
          ) : (
            <>
              <h3>{detail.title}</h3>
              <p className={detail.checks?.ok ? "team-check ok" : "team-check fail"}>
                {detail.checks?.ok ? "Checks passed: valid nodes, no secrets, within size limits." : `Checks failed: ${(detail.checks?.problems || []).join("; ")}`}
              </p>
              <pre className="diff-view team-diff" aria-label="Proposed changes">
                {(detail.diff || "(no node changes)").split("\n").filter((line) => !/^(index |diff --git |new file mode )/.test(line)).map((line, index) => (
                  <span key={index} className={line.startsWith("+++") || line.startsWith("---") ? "file" : line.startsWith("+") ? "add" : line.startsWith("-") ? "del" : line.startsWith("@@") ? "hunk" : ""}>{line + "\n"}</span>
                ))}
              </pre>
              <label className="team-reason">
                <span>Note for the review log (optional)</span>
                <input value={reason} onChange={(event) => setReason(event.target.value)} />
              </label>
              {own && <p className="memory-empty">You wrote this proposal, so a teammate has to accept it.</p>}
              <div className="toolbar-row">
                <button className="primary-button" type="button" disabled={busy || Boolean(own) || !detail.checks?.ok} onClick={() => void decide("accept")}>Accept and merge</button>
                <button className="danger-button" type="button" disabled={busy} onClick={() => void decide("reject")}>Reject</button>
                <button className="secondary-button" type="button" onClick={() => setDetail(null)}>Close</button>
              </div>
            </>
          )}
        </div>
      )}
    </section>
  );
}
