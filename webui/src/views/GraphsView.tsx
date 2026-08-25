import { useCallback, useEffect, useRef, useState } from "react";
import { post, request } from "../api";
import type { GraphNode, GraphPlan, GraphRun, GraphSummary, Profile } from "../types";

/**
 * Graph Kanban.
 *
 * Load an Agentic Graph, validate its plan, review any human gates, then run
 * it and watch every card move through To do, Current work and Done.
 */

const LANES: { id: string; title: string; note: string; states: string[] }[] = [
  { id: "todo", title: "To do", note: "Waiting for the run or dependencies", states: ["pending", "blocked", "ready", ""] },
  { id: "current", title: "Current work", note: "Actively handled by the agent", states: ["running", "active"] },
  { id: "done", title: "Done", note: "Succeeded and failed jobs with summaries", states: ["succeeded", "failed", "skipped", "cancelled"] },
];

function laneFor(node: GraphNode): string {
  const state = (node.state || "").toLowerCase();
  const lane = LANES.find((item) => item.states.includes(state));
  return lane ? lane.id : "todo";
}

function Card({ node }: { node: GraphNode }) {
  const state = (node.state || "pending").toUpperCase();
  return (
    <article className="kanban-card">
      <div className="kanban-card-top">
        <span className="chip">{(node.type || "task").toUpperCase()}</span>
        <span className={`chip state-${(node.state || "pending").toLowerCase()}`}>{state}</span>
      </div>
      <b>{node.title || node.id}</b>
      <small>{node.id}</small>
      <div className="kanban-card-body">
        {node.depends_on?.length ? (
          <span>Depends on <b>{node.depends_on.join(", ")}</b></span>
        ) : (
          <span><b>Entry card</b> · no dependencies</span>
        )}
      </div>
      {node.summary && <p className="kanban-summary">{node.summary}</p>}
      <div className="kanban-card-foot">
        <span>@{node.profile || "run-default"}</span>
        <span>{node.files_changed ?? 0} files changed</span>
      </div>
    </article>
  );
}

export function GraphsView({
  profiles,
  setError,
  notify,
}: {
  profiles: Profile[];
  setError: (message: string) => void;
  notify: (message: string) => void;
}) {
  const [graphs, setGraphs] = useState<GraphSummary[]>([]);
  const [path, setPath] = useState("");
  const [manual, setManual] = useState("");
  const [goal, setGoal] = useState("");
  const [plan, setPlan] = useState<GraphPlan | null>(null);
  const [run, setRun] = useState<GraphRun | null>(null);
  const [gates, setGates] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState(false);
  const poll = useRef<number | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const data = await request<{ graphs?: GraphSummary[] }>("/api/graphs");
        setGraphs(data.graphs || []);
      } catch (problem) {
        setError((problem as Error).message);
      }
    })();
    return () => {
      if (poll.current) window.clearInterval(poll.current);
    };
  }, [setError]);

  const preview = useCallback(
    async (target: string) => {
      if (!target) {
        setPlan(null);
        return;
      }
      try {
        const data = await request<GraphPlan>(`/api/graphs/preview?path=${encodeURIComponent(target)}`);
        setPlan(data);
        setGates(Object.fromEntries((data.gates || []).map((gate) => [gate, false])));
        setRun(null);
      } catch (problem) {
        setError((problem as Error).message);
        setPlan(null);
      }
    },
    [setError],
  );

  useEffect(() => {
    void preview(path);
  }, [path, preview]);

  async function generate() {
    if (!goal.trim()) return;
    setBusy(true);
    try {
      const draft = await post<GraphPlan>("/api/graphs/draft", { goal });
      setPlan(draft);
      notify("Draft generated. Review it before running.");
    } catch (problem) {
      setError((problem as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function start() {
    const target = manual.trim() || path;
    if (!target) return;
    const ungated = Object.entries(gates).filter(([, approved]) => !approved).map(([gate]) => gate);
    if (ungated.length) {
      setError(`Review the human gate${ungated.length > 1 ? "s" : ""} first: ${ungated.join(", ")}.`);
      return;
    }
    setBusy(true);
    try {
      await post("/api/graphs/run", { path: target });
      notify("Run started.");
      if (poll.current) window.clearInterval(poll.current);
      poll.current = window.setInterval(async () => {
        try {
          const status = await request<GraphRun>("/api/graphs/status");
          setRun(status);
          const finished = ["succeeded", "failed", "cancelled", "complete"].includes(
            String(status.status || "").toLowerCase(),
          );
          if (finished && poll.current) {
            window.clearInterval(poll.current);
            poll.current = null;
            setBusy(false);
          }
        } catch {
          /* a transient poll failure should not kill the run view */
        }
      }, 1500);
    } catch (problem) {
      setError((problem as Error).message);
      setBusy(false);
    }
  }

  const nodes = run?.nodes?.length ? run.nodes : plan?.nodes || [];
  const gateNames = plan?.gates || [];

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <div className="eyebrow">AGENTIC GRAPH</div>
          <h1>Graph Kanban</h1>
          <p>Validate a dependency graph, then let MagAgent work every card to completion.</p>
        </div>
        <div className="header-actions">
          <button className="ghost-button" type="button" onClick={() => void preview(path)} disabled={!path}>
            Validate plan
          </button>
          <button className="primary-button" type="button" onClick={() => void start()} disabled={busy || (!path && !manual.trim())}>
            ▶ Run graph
          </button>
        </div>
      </div>

      <section className="graph-goal">
        <div>
          <div className="eyebrow">GOAL TO GRAPH</div>
          <h2>Build the work, your way</h2>
          <p>Start from an existing file, or ask the planning model for a draft you can review and edit.</p>
        </div>
        <label className="sr-only" htmlFor="graphGoal">What should this graph accomplish?</label>
        <textarea
          id="graphGoal"
          rows={2}
          placeholder="Ship a reliable onboarding flow, including implementation, documentation, and verification…"
          value={goal}
          onChange={(event) => setGoal(event.target.value)}
        />
        <button className="primary-button" type="button" onClick={() => void generate()} disabled={busy || !goal.trim()}>
          ✦ Generate with AI
        </button>
      </section>

      <section className="graph-picker">
        <label htmlFor="graphSelect">Graph file</label>
        <select id="graphSelect" value={path} onChange={(event) => setPath(event.target.value)}>
          <option value="">Choose a graph…</option>
          {graphs.map((item) => (
            <option key={item.path} value={item.path}>{item.name || item.path}</option>
          ))}
        </select>
        <label htmlFor="graphPath">Or enter a project-relative path</label>
        <input
          id="graphPath"
          placeholder="workflow.agraph.yaml"
          value={manual}
          onChange={(event) => setManual(event.target.value)}
        />
      </section>

      {plan?.error && <div className="error-banner inline" role="alert">{plan.error}</div>}

      {plan && !plan.error && (
        <section className="graph-overview">
          <div><small>GRAPH</small><b>{plan.graph || plan.title || "—"}</b></div>
          <div><small>JOBS</small><b>{plan.node_count ?? nodes.length}</b></div>
          <div><small>MAX PARALLEL</small><b>{plan.max_parallel ?? 1}</b></div>
          <div><small>PROJECTED COST</small><b>${(plan.projected_cost_usd ?? 0).toFixed(2)}</b></div>
          <div className="run-status"><small>RUN STATUS</small><b>{run?.status || "Ready"}</b></div>
        </section>
      )}

      {gateNames.length > 0 && (
        <section className="graph-gates">
          <b>Human gates</b> <span>Review each gate before running.</span>
          {gateNames.map((gate) => (
            <label key={gate}>
              <input
                type="checkbox"
                checked={Boolean(gates[gate])}
                onChange={(event) => setGates({ ...gates, [gate]: event.target.checked })}
              />
              Review {gate}
            </label>
          ))}
        </section>
      )}

      <div className="kanban">
        {LANES.map((lane) => {
          const cards = nodes.filter((node) => laneFor(node) === lane.id);
          return (
            <section className={`kanban-lane lane-${lane.id}`} key={lane.id}>
              <header>
                <div>
                  <b>{lane.title}</b>
                  <small>{lane.note}</small>
                </div>
                <span className="count">{cards.length}</span>
              </header>
              {cards.length ? (
                cards.map((node) => <Card key={node.id} node={node} />)
              ) : (
                <div className="lane-empty">
                  {lane.id === "todo"
                    ? "Choose a graph to see its jobs."
                    : lane.id === "current"
                      ? "The agent is not working a card."
                      : "Completed jobs will appear here."}
                </div>
              )}
            </section>
          );
        })}
      </div>

      {profiles.length > 0 && (
        <p className="context-note">
          Cards run as <b>@run-default</b> unless a node names a profile. {profiles.length} profile
          {profiles.length === 1 ? "" : "s"} available.
        </p>
      )}
    </div>
  );
}
