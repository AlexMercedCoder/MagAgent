import { useEffect, useState } from "react";
import { request } from "../api";

type Cockpit = Record<string, unknown> & { ok?: boolean };

function Card({ title, value }: { title: string; value: unknown }) {
  const text =
    value === null || value === undefined
      ? "—"
      : typeof value === "object"
        ? JSON.stringify(value, null, 2)
        : String(value);
  const long = text.includes("\n") || text.length > 60;
  return (
    <article className="ops-card">
      <h3>{title}</h3>
      {long ? <pre>{text}</pre> : <b>{text}</b>}
    </article>
  );
}

/** Local diagnostics: workspace health, readiness, usage, recent activity. */
export function OperationsView({ setError }: { setError: (message: string) => void }) {
  const [state, setState] = useState<Cockpit | null>(null);
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    try {
      const [cockpit, ui] = await Promise.all([
        request<Cockpit>("/api/cockpit"),
        request<Cockpit>("/api/state"),
      ]);
      setState({ ...ui, ...cockpit });
    } catch (problem) {
      setError((problem as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const entries = Object.entries(state || {}).filter(([key]) => key !== "ok" && key !== "error");

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <div className="eyebrow">LOCAL DIAGNOSTICS</div>
          <h1>Operations</h1>
          <p>Workspace health, plans, patches, models, and recent activity.</p>
        </div>
        <button className="ghost-button" type="button" onClick={() => void load()} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </div>
      {entries.length ? (
        <div className="ops-grid">
          {entries.map(([key, value]) => (
            <Card key={key} title={key.replace(/_/g, " ")} value={value} />
          ))}
        </div>
      ) : (
        <div className="empty-panel">
          <h2>{loading ? "Loading…" : "Nothing to report"}</h2>
        </div>
      )}
    </div>
  );
}
