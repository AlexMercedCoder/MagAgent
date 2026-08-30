import { useCallback, useEffect, useRef, useState } from "react";
import { post, request } from "../api";
import type { GraphNode, Profile } from "../types";

/**
 * Graph Kanban.
 *
 * Every card starts Pending, moves to In progress while MagAgent works it, and
 * lands in Complete when it finishes, whichever way it finished.
 *
 * A graph reaches the board three ways: load a file from the project, start
 * blank and append cards, or describe a goal and let the planning model draft
 * one. Nothing is written until the draft is saved under a name.
 */

const LANES: { id: string; title: string; note: string; states: string[] }[] = [
  { id: "pending", title: "Pending", note: "Not started yet", states: ["pending", "blocked", "ready", ""] },
  { id: "progress", title: "In progress", note: "Being worked right now", states: ["running", "active"] },
  { id: "complete", title: "Complete", note: "Finished, with the outcome", states: ["succeeded", "failed", "skipped", "cancelled", "complete"] },
];

function laneFor(node: GraphNode): string {
  const state = (node.state || "").toLowerCase();
  return LANES.find((lane) => lane.states.includes(state))?.id ?? "pending";
}

type GraphDoc = Record<string, unknown> & { nodes?: Record<string, Record<string, unknown>> };

type NodeMap = Record<string, Record<string, unknown>>;

/**
 * Wire a hand-edited board back into a valid AGS document.
 *
 * MagAgent validates that every declared output is read by something
 * downstream (AG904), so appending a card is not enough: each card must
 * consume its parents' outputs as inputs, and whatever nothing depends on
 * becomes a graph-level output. The original hand-written UI did this on every
 * edit; the rule is easy to lose and produces a document that only fails at
 * save time.
 */
function rebuildStructure(document: GraphDoc): GraphDoc {
  const nodes: NodeMap = { ...(document.nodes ?? {}) };
  const safeKey = (value: string) => value.replace(/[^A-Za-z0-9_-]/g, "_");

  for (const node of Object.values(nodes)) {
    // Drop dependencies on cards that no longer exist.
    node.depends_on = ((node.depends_on as string[]) ?? []).filter((id) => id in nodes);
  }

  for (const node of Object.values(nodes)) {
    if (String(node.type ?? "task") !== "task") continue;
    // Keep hand-authored inputs, replace the generated dependency ones.
    const inputs = Object.fromEntries(
      Object.entries((node.inputs as Record<string, unknown>) ?? {}).filter(
        ([key]) => !key.startsWith("dependency_"),
      ),
    );
    for (const dependency of (node.depends_on as string[]) ?? []) {
      const parent = nodes[dependency];
      const outputs = (parent?.outputs as Record<string, { type?: string }>) ?? {};
      const outputName = Object.keys(outputs)[0];
      if (!outputName) continue;
      inputs[safeKey(`dependency_${dependency}`)] = {
        type: outputs[outputName]?.type ?? "markdown",
        description: `Completion evidence from ${String(parent.title ?? dependency)}.`,
        from: `nodes.${dependency}.outputs.${outputName}`,
      };
    }
    if (Object.keys(inputs).length) node.inputs = inputs;
    else delete node.inputs;
  }

  const entrypoints = Object.entries(nodes)
    .filter(([, node]) => !((node.depends_on as string[]) ?? []).length)
    .map(([id]) => id);

  const depended = new Set(
    Object.values(nodes).flatMap((node) => ((node.depends_on as string[]) ?? [])),
  );
  const outputs: Record<string, unknown> = {};
  for (const [id, node] of Object.entries(nodes)) {
    if (depended.has(id)) continue;
    const declared = (node.outputs as Record<string, { type?: string }>) ?? {};
    const outputName = Object.keys(declared)[0];
    if (!outputName) continue;
    outputs[safeKey(`result_${id}`)] = {
      type: declared[outputName]?.type ?? "markdown",
      description: `Final result from ${String(node.title ?? id)}.`,
      from: `nodes.${id}.outputs.${outputName}`,
    };
  }

  return { ...document, nodes, entrypoints, outputs };
}

/** Turn a document's node map into cards, all Pending until a run moves them. */
function cardsFrom(document: GraphDoc): GraphNode[] {
  const raw = document.nodes ?? {};
  return Object.entries(raw).map(([id, node]) => ({
    id,
    title: String(node.title ?? id),
    type: String(node.type ?? "task"),
    depends_on: (node.depends_on as string[]) ?? [],
    profile: String(node["x-agent-profile"] ?? ""),
    state: "pending",
  }));
}

function cardsFromPlan(rows: Record<string, unknown>[]): GraphNode[] {
  return rows.map((node) => ({
    id: String(node.id ?? node.node_id ?? ""),
    title: String(node.title ?? node.id ?? node.node_id ?? "Untitled card"),
    type: String(node.type ?? "task"),
    depends_on: (node.depends_on ?? node.dependencies ?? []) as string[],
    profile: String(node.profile ?? node.agent_profile ?? ""),
    state: String(node.state ?? "pending"),
    summary: String(node.summary ?? node.error ?? ""),
    files_changed: Array.isArray(node.files_changed) ? node.files_changed.length : Number(node.files_changed ?? 0),
  }));
}

function Card({ node }: { node: GraphNode }) {
  const state = (node.state || "pending").toLowerCase();
  return (
    <article className="kanban-card">
      <div className="kanban-card-top">
        <span className="chip">{(node.type || "task").toUpperCase()}</span>
        <span className={`chip state-${state}`}>{state.toUpperCase()}</span>
      </div>
      <b>{node.title}</b>
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
  const [graphs, setGraphs] = useState<{ path: string; name?: string }[]>([]);
  const [path, setPath] = useState("");
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [plan, setPlan] = useState<Record<string, unknown> | null>(null);
  const [draft, setDraft] = useState<GraphDoc | null>(null);
  const [draftPath, setDraftPath] = useState("");
  const [template, setTemplate] = useState<Record<string, unknown> | null>(null);
  const [goal, setGoal] = useState("");
  const [busy, setBusy] = useState("");
  const [status, setStatus] = useState("Ready");
  const poll = useRef<number | null>(null);

  const refreshCatalog = useCallback(async () => {
    const data = await request<{ graphs?: { path: string; name?: string }[] }>("/api/graphs");
    setGraphs(data.graphs || []);
    return data.graphs || [];
  }, []);

  useEffect(() => {
    void refreshCatalog().catch((problem) => setError((problem as Error).message));
    return () => {
      if (poll.current) window.clearInterval(poll.current);
    };
  }, [refreshCatalog, setError]);

  const loadSaved = useCallback(
    async (target: string) => {
      if (!target) {
        setPlan(null);
        setNodes([]);
        return;
      }
      try {
        const preview = await request<{ plan?: Record<string, unknown> } & Record<string, unknown>>(
          `/api/graphs/preview?path=${encodeURIComponent(target)}`,
        );
        const resolved = (preview.plan ?? preview) as Record<string, unknown>;
        setPlan(resolved);
        setNodes(cardsFromPlan((resolved.nodes as Record<string, unknown>[]) || []));
        setStatus("Ready");
      } catch (problem) {
        setPlan(null);
        setNodes([]);
        setError((problem as Error).message);
      }
    },
    [setError],
  );

  useEffect(() => {
    // An unsaved draft owns the board; loading a plan would wipe its cards.
    if (draft) return;
    void loadSaved(path);
  }, [path, loadSaved, draft]);

  function adoptDraft(document: GraphDoc, note: string) {
    setDraft(document);
    setPlan(null);
    setNodes(cardsFrom(document));
    setStatus(note);
  }

  async function makeDraft(mode: "blank" | "ai") {
    setBusy(mode);
    if (mode === "ai") setStatus("Drafting…");
    try {
      const created = await post<{ document: GraphDoc; node_template?: Record<string, unknown> }>(
        "/api/graphs/draft",
        { goal, mode },
      );
      if (created.node_template) setTemplate(created.node_template);
      adoptDraft(created.document, "Unsaved draft");
      setDraftPath(draftPath || "workflow.agraph.yaml");
      setPath("");
    } catch (problem) {
      setError((problem as Error).message);
      setStatus("Ready");
    } finally {
      setBusy("");
    }
  }

  /** Append a card, chained onto the last one so the board stays a DAG. */
  async function addCard() {
    let document = draft;
    if (!document && path) {
      const saved = await request<{ document: GraphDoc }>(
        `/api/graphs/document?path=${encodeURIComponent(path)}`,
      ).catch((problem) => {
        setError((problem as Error).message);
        return null;
      });
      document = saved?.document ?? null;
    }
    if (!document) return;

    let node = template;
    if (!node) {
      const seeded = await post<{ node_template?: Record<string, unknown> }>("/api/graphs/draft", {
        goal: "",
        mode: "blank",
      });
      node = seeded.node_template ?? null;
      setTemplate(node);
    }
    if (!node) return;

    const existing = { ...(document.nodes ?? {}) };
    const index = Object.keys(existing).length + 1;
    const id = `card_${index}`;
    const previous = Object.keys(existing).at(-1);
    existing[id] = {
      ...node,
      title: `New card ${index}`,
      ...(previous ? { depends_on: [previous] } : {}),
    };
    adoptDraft(rebuildStructure({ ...document, nodes: existing }), "Unsaved draft");
    if (!draftPath) setDraftPath(path || "workflow.agraph.yaml");
  }

  async function saveDraft() {
    if (!draft || !draftPath.trim()) return;
    setBusy("save");
    try {
      const savedResult = await post<{ path?: string }>("/api/graphs/save", { document: draft, path: draftPath.trim() });
      const found = await refreshCatalog();
      setDraft(null);
      const saved = found.find((item) => item.path === savedResult.path || item.path.endsWith(draftPath.trim()));
      const savedPath = saved?.path ?? savedResult.path ?? "";
      setPath(savedPath);
      if (savedPath) await loadSaved(savedPath);
      setStatus("Saved");
      notify("Graph saved.");
    } catch (problem) {
      setError((problem as Error).message);
    } finally {
      setBusy("");
    }
  }

  /** Export the current graph, saved or draft, as a file to keep or share. */
  async function exportGraph() {
    try {
      let document = draft;
      if (!document && path) {
        const saved = await request<{ document: GraphDoc }>(
          `/api/graphs/document?path=${encodeURIComponent(path)}`,
        );
        document = saved.document;
      }
      if (!document) return;
      const name = (draftPath || path || "workflow.agraph.yaml").split("/").pop()!;
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(document, null, 2)], { type: "application/json" }),
      );
      const anchor = window.document.createElement("a");
      anchor.href = url;
      anchor.download = name.replace(/\.ya?ml$/, ".json");
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (problem) {
      setError((problem as Error).message);
    }
  }

  async function run() {
    if (!path) return;
    setBusy("run");
    try {
      const started = await post<{ job_id?: string }>("/api/graphs/run", { path });
      if (!started.job_id) throw new Error("The graph runner did not return a job id.");
      setStatus("Running");
      notify("Run started.");
      if (poll.current) window.clearInterval(poll.current);
      poll.current = window.setInterval(async () => {
        try {
          const state = await request<{ state?: string; status?: string; nodes?: Record<string, unknown>[] }>(
            `/api/graphs/status?job_id=${encodeURIComponent(started.job_id!)}`,
          );
          if (state.nodes?.length) setNodes(cardsFromPlan(state.nodes));
          const runState = state.state || state.status || "";
          if (runState) setStatus(runState);
          const finished = ["succeeded", "failed", "cancelled", "complete"].includes(
            String(runState).toLowerCase(),
          );
          if (finished && poll.current) {
            window.clearInterval(poll.current);
            poll.current = null;
            setBusy("");
          }
        } catch {
          /* a transient poll failure should not tear down the board */
        }
      }, 1500);
    } catch (problem) {
      setError((problem as Error).message);
      setBusy("");
    }
  }

  const canAuthor = Boolean(draft || path);

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <div className="eyebrow">AGENTIC GRAPH</div>
          <h1>Graph Kanban</h1>
          <p>Validate a dependency graph, then let MagAgent work every card to completion.</p>
        </div>
        <div className="header-actions">
          <button className="ghost-button" type="button" onClick={() => void exportGraph()} disabled={!canAuthor}>
            ↓ Export
          </button>
          <button className="primary-button" type="button" onClick={() => void run()} disabled={!path || Boolean(busy)}>
            ▶ Run graph
          </button>
        </div>
      </div>

      <section className="graph-goal">
        <div>
          <div className="eyebrow">BUILD A GRAPH</div>
          <h2>Build the work, your way</h2>
          <p>Load a file, start from an empty board, or describe a goal and review the model's draft.</p>
        </div>
        <label className="sr-only" htmlFor="graphGoal">What should this graph accomplish?</label>
        <textarea
          id="graphGoal"
          rows={2}
          placeholder="Ship a reliable onboarding flow, including implementation, documentation, and verification…"
          value={goal}
          onChange={(event) => setGoal(event.target.value)}
        />
        <div className="graph-goal-buttons">
          <button className="primary-button" type="button" onClick={() => void makeDraft("ai")} disabled={Boolean(busy) || !goal.trim()}>
            {busy === "ai" ? "Drafting…" : "✦ Generate with AI"}
          </button>
          <button className="ghost-button" type="button" onClick={() => void makeDraft("blank")} disabled={Boolean(busy)}>
            ＋ Blank graph
          </button>
          <button className="ghost-button" type="button" onClick={() => void addCard()} disabled={Boolean(busy) || !canAuthor}>
            ＋ Add card
          </button>
        </div>
      </section>

      {draft && (
        <section className="graph-draft" role="status">
          <div>
            <b>Unsaved draft</b>
            <span>{nodes.length} card{nodes.length === 1 ? "" : "s"}. Nothing is written until you save.</span>
          </div>
          <div className="graph-draft-save">
            <label className="sr-only" htmlFor="draftPath">Save as</label>
            <input
              id="draftPath"
              value={draftPath}
              placeholder="workflow.agraph.yaml"
              onChange={(event) => setDraftPath(event.target.value)}
            />
            <button className="primary-button" type="button" onClick={() => void saveDraft()} disabled={busy === "save" || !draftPath.trim()}>
              {busy === "save" ? "Saving…" : "Save graph"}
            </button>
            <button className="ghost-button" type="button" onClick={() => { setDraft(null); void loadSaved(path); }}>
              Discard
            </button>
          </div>
        </section>
      )}

      <section className="graph-picker">
        <label htmlFor="graphSelect">Graph file</label>
        <select id="graphSelect" value={path} onChange={(event) => setPath(event.target.value)}>
          <option value="">Choose a graph…</option>
          {graphs.map((item) => (
            <option key={item.path} value={item.path}>{item.name || item.path}</option>
          ))}
        </select>
        <button className="ghost-button" type="button" disabled={!path || Boolean(busy)} onClick={() => void loadSaved(path)}>
          Load graph
        </button>
      </section>

      {plan && !draft && (
        <section className="graph-overview">
          <div><small>GRAPH</small><b>{String(plan.graph ?? plan.title ?? "—")}</b></div>
          <div><small>JOBS</small><b>{String(plan.node_count ?? nodes.length)}</b></div>
          <div><small>MAX PARALLEL</small><b>{String(plan.max_parallel ?? 1)}</b></div>
          <div className="run-status"><small>RUN STATUS</small><b>{status}</b></div>
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
                  {lane.id === "pending"
                    ? "Load a graph, start a blank one, or generate one from a goal."
                    : "Nothing here yet."}
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
