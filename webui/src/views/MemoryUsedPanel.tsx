import { useEffect, useMemo, useState } from "react";

/** One turn's MagGraph recall record (magent.memory-evidence.v1). */
export type MemoryEvidence = {
  schema?: string;
  turn?: number;
  recorded_at?: string;
  status?: "used" | "no_match" | "unavailable" | "blocked_by_profile" | string;
  query_preview?: string;
  speaker?: string;
  nodes?: { id: string; type?: string; score?: number | null; matched?: string[]; reason?: string; source?: string }[];
  tokens?: { recalled?: number; injected?: number; budget?: number; profile_reserve?: number };
  truncated?: boolean;
  truncation?: string[];
};

export type EvidenceSource = {
  key: string;
  label: string;
  detail: string;
  turns: MemoryEvidence[];
};

const STATUS_TEXT: Record<string, string> = {
  used: "Recalled memory",
  no_match: "No memory matched",
  unavailable: "Memory graph unavailable",
  blocked_by_profile: "Profile does not allow memory reads",
};

const TRUNCATION_TEXT: Record<string, string> = {
  recall_budget: "memory budget",
  profile_reserve: "profile-state reserve",
};

function asEvidence(value: unknown): MemoryEvidence[] {
  return Array.isArray(value) ? (value.filter((item) => item && typeof item === "object") as MemoryEvidence[]) : [];
}

/** Chat runs, then durable tasks (each newest first) that recorded memory evidence. */
export function evidenceSources(chatRuns: Record<string, unknown>[], tasks: Record<string, unknown>[]): EvidenceSource[] {
  const sources: EvidenceSource[] = [];
  for (const run of chatRuns) {
    const turns = asEvidence(run.memory_evidence);
    if (!turns.length) continue;
    const started = typeof run.started_at === "number" ? new Date(run.started_at * 1000) : null;
    sources.push({
      key: `run:${String(run.id)}`,
      label: `Chat run ${String(run.id).replace(/^run_/, "").slice(0, 8)}`,
      detail: [String(run.state || ""), started ? started.toLocaleString() : ""].filter(Boolean).join(" · "),
      turns,
    });
  }
  for (const task of tasks) {
    const metadata = (task.metadata || {}) as Record<string, unknown>;
    const turns = asEvidence(metadata.memory_evidence);
    if (!turns.length) continue;
    sources.push({
      key: `task:${String(task.id || task.task_id)}`,
      label: String(task.title || task.id || "Task"),
      detail: [String(task.state || task.status || ""), String(metadata.model || "")].filter(Boolean).join(" · "),
      turns,
    });
  }
  return sources;
}

function summary(turns: MemoryEvidence[]) {
  const nodes = new Set<string>();
  let injected = 0;
  for (const turn of turns) {
    for (const node of turn.nodes || []) nodes.add(node.id);
    injected += turn.tokens?.injected || 0;
  }
  return {
    used: turns.filter((turn) => turn.status === "used").length,
    nodes: nodes.size,
    injected,
    truncated: turns.some((turn) => turn.truncated),
  };
}

function score(value: number | null | undefined): string {
  return typeof value === "number" ? value.toFixed(2).replace(/\.?0+$/, "") || "0" : "–";
}

export function MemoryUsedPanel({ sources }: { sources: EvidenceSource[] }) {
  const [selected, setSelected] = useState("");
  const current = useMemo(() => sources.find((item) => item.key === selected) || sources[0], [sources, selected]);

  useEffect(() => {
    if (selected && !sources.some((item) => item.key === selected)) setSelected("");
  }, [sources, selected]);

  return (
    <article className="detail-card memory-used" aria-labelledby="memory-used-title">
      <div className="memory-used-head">
        <div>
          <h2 id="memory-used-title">Memory used</h2>
          <p>Which MagGraph memories each run recalled, how well they matched, and what they cost in context.</p>
        </div>
        {sources.length > 1 && (
          <label className="memory-used-picker">
            <span>Run</span>
            <select value={current?.key || ""} onChange={(event) => setSelected(event.target.value)}>
              {sources.map((item) => (
                <option key={item.key} value={item.key}>{item.label}</option>
              ))}
            </select>
          </label>
        )}
      </div>

      {!current && (
        <p className="memory-empty">
          No run has recorded memory use yet. When a chat turn or <code>magent ask</code> draws on your memory graph,
          the nodes it used appear here. In a terminal session, <code>/why last</code> shows the same thing.
        </p>
      )}

      {current && (() => {
        const totals = summary(current.turns);
        return (
          <>
            <div className="memory-used-run">
              <strong>{current.label}</strong>
              {current.detail && <small>{current.detail}</small>}
            </div>
            <dl className="memory-used-stats">
              <div><dt>Turns with memory</dt><dd>{totals.used} of {current.turns.length}</dd></div>
              <div><dt>Distinct nodes</dt><dd>{totals.nodes}</dd></div>
              <div><dt>Tokens injected</dt><dd>~{totals.injected.toLocaleString()}</dd></div>
              <div><dt>Truncated</dt><dd className={totals.truncated ? "warn" : ""}>{totals.truncated ? "Yes" : "No"}</dd></div>
            </dl>
            <ol className="memory-turns">
              {current.turns.map((turn, index) => {
                const budget = turn.tokens?.budget || 0;
                const injected = turn.tokens?.injected || 0;
                const percent = budget > 0 ? Math.min(100, Math.round((injected / budget) * 100)) : 0;
                return (
                  <li key={`${turn.turn}-${turn.recorded_at}-${index}`} className={`memory-turn ${turn.status || ""}`}>
                    <header>
                      <b>Turn {turn.turn ?? index + 1}{turn.speaker ? ` · ${turn.speaker}` : ""}</b>
                      <span className="memory-turn-status">{STATUS_TEXT[turn.status || ""] || turn.status}</span>
                    </header>
                    {turn.query_preview && <p className="memory-turn-query">“{turn.query_preview}”</p>}
                    {turn.status === "used" && (
                      <>
                        <div className="memory-meter" role="img" aria-label={`About ${injected} of ${budget} memory tokens used`}>
                          <span style={{ width: `${percent}%` }} />
                        </div>
                        <small className="memory-meter-label">
                          ~{injected.toLocaleString()} of {budget.toLocaleString()} tokens
                          {turn.truncated && ` · truncated by ${(turn.truncation || []).map((item) => TRUNCATION_TEXT[item] || item).join(" and ")}`}
                        </small>
                        <table className="memory-node-table">
                          <thead>
                            <tr><th scope="col">Node</th><th scope="col">Score</th><th scope="col">Matched</th></tr>
                          </thead>
                          <tbody>
                            {(turn.nodes || []).map((node) => (
                              <tr key={node.id}>
                                <td>
                                  <code>{node.id}</code>
                                  {(node.type || node.source === "team") && <small>{[node.type, node.source === "team" ? "team memory" : ""].filter(Boolean).join(" · ")}</small>}
                                </td>
                                <td data-label="Score">{score(node.score)}</td>
                                <td data-label="Matched">{(node.matched || []).join(", ") || node.reason || "graph search"}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </>
                    )}
                  </li>
                );
              })}
            </ol>
          </>
        );
      })()}
    </article>
  );
}
