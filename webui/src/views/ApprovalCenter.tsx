import { useCallback, useEffect, useState } from "react";
import { post, request } from "../api";

type Choice = {
  decision: "approve" | "deny" | "cancel";
  scope: "once" | "session" | "persistent";
  label: string;
};

type PendingApproval = {
  id: string;
  created_at: string;
  expires_at?: string;
  origin: Record<string, string>;
  action: {
    kind: string;
    name: string;
    summary: string;
    arguments: Record<string, unknown>;
    resource?: string;
    working_directory?: string;
    effects?: string[];
  };
  action_digest: string;
  risk: { level: string; reasons: string[] };
  choices: Choice[];
};

type Snapshot = {
  snapshot: { pending: PendingApproval[] };
};

export function ApprovalCenter({
  setError,
  notify,
}: {
  setError: (message: string) => void;
  notify: (message: string) => void;
}) {
  const [pending, setPending] = useState<PendingApproval[]>([]);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const data = await request<Snapshot>("/api/approvals/snapshot");
      setPending(data.snapshot?.pending ?? []);
    } catch {
      // The normal run stream still carries the request. Polling is only the
      // route-independent reconnect path, so a transient miss is not alarming.
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 800);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const decide = useCallback(
    async (approval: PendingApproval, choice: Choice) => {
      setBusy(true);
      try {
        const result = await post<{ ok: boolean; error?: string }>("/api/approvals/decide", {
          request_id: approval.id,
          decision: choice.decision,
          scope: choice.scope,
          decision_id: `dec_web_${crypto.randomUUID().replaceAll("-", "")}`,
        });
        if (!result.ok) throw new Error(result.error || "The approval could not be resolved.");
        notify(choice.decision === "approve" ? "Permission approved." : "Permission denied.");
        await refresh();
      } catch (problem) {
        setError((problem as Error).message);
        await refresh();
      } finally {
        setBusy(false);
      }
    },
    [notify, refresh, setError],
  );

  const approval = pending[0];
  if (!approval) return null;
  return (
    <div className="modal-backdrop approval-backdrop" role="presentation">
      <section className="modal approval-modal" role="alertdialog" aria-modal="true" aria-label="Permission required">
        <small>PERMISSION REQUIRED · {pending.length} PENDING</small>
        <h2>{approval.action.summary}</h2>
        <div className={`approval-risk ${approval.risk.level}`}>
          <b>{approval.risk.level} risk</b>
          {approval.risk.reasons.map((reason) => <span key={reason}>{reason}</span>)}
        </div>
        <dl className="approval-detail">
          <div><dt>Action</dt><dd>{approval.action.name}</dd></div>
          {approval.action.working_directory && <div><dt>Project</dt><dd>{approval.action.working_directory}</dd></div>}
          {approval.origin.node_id && <div><dt>Graph card</dt><dd>{approval.origin.node_id}</dd></div>}
          <div><dt>Exact arguments</dt><dd><pre>{JSON.stringify(approval.action.arguments, null, 2)}</pre></dd></div>
          <div><dt>Digest</dt><dd><code>{approval.action_digest}</code></dd></div>
        </dl>
        {!!approval.action.effects?.length && <ul>{approval.action.effects.map((effect) => <li key={effect}>{effect}</li>)}</ul>}
        <div className="approval-actions">
          {approval.choices.map((choice) => (
            <button
              className={choice.decision === "approve" ? "primary-button" : "secondary-button"}
              disabled={busy}
              key={`${choice.decision}:${choice.scope}`}
              type="button"
              onClick={() => void decide(approval, choice)}
            >
              {choice.label}
            </button>
          ))}
        </div>
        <small>MagAgent will revalidate the exact action and current policy before execution.</small>
      </section>
    </div>
  );
}
