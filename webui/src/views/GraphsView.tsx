import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { humanizeError, post, request } from "../api";
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

const GRAPH_RUN_KEY = "magent:last-graph-run";
const GRAPH_DRAFT_KEY = "magent:graph-draft";
const GRAPH_TOOLS = [
  ["file_read", "Read project files"],
  ["file_search", "Search project code"],
  ["file_write", "Create or edit files"],
  ["shell_exec", "Run shell commands"],
  ["web_search", "Search the web"],
  ["web_fetch", "Fetch web pages or APIs"],
  ["browser", "Use browser tools"],
  ["data", "Query structured data"],
  ["database", "Query databases"],
  ["image", "Create or inspect images"],
  ["document", "Create documents or presentations"],
] as const;

function laneFor(node: GraphNode): string {
  const state = (node.state || "").toLowerCase();
  return LANES.find((lane) => lane.states.includes(state))?.id ?? "pending";
}

type GraphDoc = Record<string, unknown> & { nodes?: Record<string, Record<string, unknown>> };
type DraftActivity = { stage?: string; message?: string; attempt?: number; finding_count?: number; details?: string[]; at?: number };
type GraphAuditEvent = {
  type?: string;
  timestamp?: string;
  node_id?: string;
  tool?: string;
  state?: string;
  summary?: string;
  error_code?: string;
  error?: string;
};
type GraphApproval = {
  request_id: string;
  description: string;
  tier: number;
  choices: Array<"once" | "session" | "always" | "deny">;
  node_id?: string;
};

type NodeMap = Record<string, Record<string, unknown>>;
type CardEditor = {
  id: string;
  title: string;
  description: string;
  profile: string;
  dependencies: string[];
  tools: string[];
  skills: string[];
  mcpServers: string[];
  permissions: string;
  workspace: "none" | "read_only" | "read_write";
};

function auditEventText(event: GraphAuditEvent): string {
  const subject = [event.node_id, event.tool].filter(Boolean).join(" · ");
  const detail = event.error || event.summary || event.state || "Lifecycle event recorded.";
  return `${subject ? `${subject}: ` : ""}${humanizeError(detail)}`;
}

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
    description: String(node.description ?? ""),
    depends_on: (node.depends_on as string[]) ?? [],
    profile: String(node["x-magagent-profile"] ?? ""),
    tools: (((node.requirements as Record<string, unknown> | undefined)?.tools as string[]) ?? []),
    state: "pending",
  }));
}

function cardsFromPlan(rows: Record<string, unknown>[]): GraphNode[] {
  return rows.map((node) => ({
    id: String(node.id ?? node.node_id ?? ""),
    title: String(node.title ?? node.id ?? node.node_id ?? "Untitled card"),
    type: String(node.type ?? "task"),
    description: String(node.description ?? ""),
    depends_on: (node.depends_on ?? node.dependencies ?? []) as string[],
    profile: String(node.profile ?? node.agent_profile ?? ""),
    state: String(node.state ?? "pending"),
    summary: humanizeError(String(node.summary ?? "")),
    error: humanizeError(String(node.error ?? "")),
    error_code: String(node.error_code ?? ""),
    attempts: Array.isArray(node.attempts) ? node.attempts as GraphNode["attempts"] : [],
    files_changed: Array.isArray(node.files_changed) ? node.files_changed.length : Number(node.files_changed ?? 0),
  }));
}

function Card({ node, editable, onEdit }: { node: GraphNode; editable: boolean; onEdit: () => void }) {
  const state = (node.state || "pending").toLowerCase();
  return (
    <article className={`kanban-card ${state === "running" ? "running" : ""} ${editable ? "editable" : ""}`}>
      <div className="kanban-card-top">
        <span className="chip">{(node.type || "task").toUpperCase()}</span>
        <span className={`chip state-${state}`}>{state.toUpperCase()}</span>
      </div>
      <b>{node.title}</b>
      <small>{node.id}</small>
      {node.description && <p className="kanban-description">{node.description}</p>}
      <div className="kanban-card-body">
        {node.depends_on?.length ? (
          <span>Depends on <b>{node.depends_on.join(", ")}</b></span>
        ) : (
          <span><b>Entry card</b> · no dependencies</span>
        )}
      </div>
      {node.error && (
        <div className="kanban-error" role="alert">
          <b>{node.error_code ? `${node.error_code}: ` : "Why it failed: "}</b>
          {node.error}
        </div>
      )}
      {node.summary && <p className="kanban-summary">{node.summary}</p>}
      {node.attempts && node.attempts.length > 0 && state === "failed" && (
        <details className="kanban-attempts">
          <summary>{node.attempts.length} attempt{node.attempts.length === 1 ? "" : "s"}</summary>
          {node.attempts.map((attempt, index) => (
            <div key={`${attempt.attempt ?? index}-${attempt.status ?? "unknown"}`}>
              <b>Attempt {attempt.attempt ?? index + 1}: {attempt.status ?? "unknown"}</b>
              {attempt.error && <p>{humanizeError(attempt.error)}</p>}
              {(attempt.criteria ?? []).map((criterion) => (
                <small key={criterion.id ?? "criterion"}>
                  {criterion.passed ? "Passed" : "Failed"}: {criterion.id ?? "criterion"}
                  {criterion.evidence != null ? ` · evidence ${String(criterion.evidence)}` : ""}
                </small>
              ))}
            </div>
          ))}
        </details>
      )}
      {node.tools?.length ? <p className="kanban-tools">Tools: {node.tools.join(", ")}</p> : null}
      <div className="kanban-card-foot">
        <span>@{node.profile || "run-default"}</span>
        <span>{node.files_changed ?? 0} files changed</span>
      </div>
      {editable && <button type="button" className="card-edit-button" onClick={onEdit}>Edit card</button>}
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
  const [jobId, setJobId] = useState("");
  const [runSummary, setRunSummary] = useState("");
  const [runActivity, setRunActivity] = useState("");
  const [lastUpdate, setLastUpdate] = useState<number | null>(null);
  const [eventCount, setEventCount] = useState(0);
  const [runId, setRunId] = useState("");
  const [auditEvents, setAuditEvents] = useState<GraphAuditEvent[]>([]);
  const [cardEditor, setCardEditor] = useState<CardEditor | null>(null);
  const [graphChoices, setGraphChoices] = useState<{ skills: string[]; mcp: string[] }>({ skills: [], mcp: [] });
  const [operationStarted, setOperationStarted] = useState<number | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [draftActivity, setDraftActivity] = useState<DraftActivity[]>([]);
  const [draftStage, setDraftStage] = useState("Preparing graph generation…");
  const [draftJobId, setDraftJobId] = useState("");
  const [approvals, setApprovals] = useState<GraphApproval[]>([]);
  const [approvalBusy, setApprovalBusy] = useState(false);
  const poll = useRef<number | null>(null);

  const watchJob = useCallback(
    (id: string, graphPath: string) => {
      if (poll.current) window.clearInterval(poll.current);
      setJobId(id);
      const update = async () => {
        try {
          const state = await request<{
            state?: string;
            status?: string;
            summary?: string | Record<string, unknown>;
            activity?: string;
            nodes?: Record<string, unknown>[];
            events?: GraphAuditEvent[];
            run_id?: string;
            awaiting_approvals?: GraphApproval[];
          }>(`/api/graphs/status?job_id=${encodeURIComponent(id)}`);
          if (state.nodes?.length) setNodes(cardsFromPlan(state.nodes));
          const runState = String(state.state || state.status || "");
          if (runState) setStatus(runState);
          setRunSummary(
            typeof state.summary === "string"
              ? state.summary
              : String((state.summary as { text?: string } | undefined)?.text || ""),
          );
          setRunActivity(state.activity || "");
          setEventCount(state.events?.length || 0);
          setRunId(state.run_id || "");
          setAuditEvents(state.events || []);
          setApprovals((state.awaiting_approvals || []).filter((item) => Boolean(item.request_id)));
          setLastUpdate(Date.now());
          sessionStorage.setItem(
            GRAPH_RUN_KEY,
            JSON.stringify({ job_id: id, run_id: state.run_id || "", path: graphPath }),
          );
          if (["succeeded", "failed", "cancelled", "complete", "completed"].includes(runState.toLowerCase())) {
            if (poll.current) window.clearInterval(poll.current);
            poll.current = null;
            setBusy("");
            setApprovals([]);
          }
        } catch (problem) {
          setRunSummary(`Status refresh failed: ${(problem as Error).message}. Retrying automatically…`);
        }
      };
      void update();
      poll.current = window.setInterval(() => void update(), 1500);
    },
    [],
  );

  const refreshCatalog = useCallback(async () => {
    const data = await request<{ graphs?: { path: string; name?: string }[] }>("/api/graphs");
    setGraphs(data.graphs || []);
    return data.graphs || [];
  }, []);

  useEffect(() => {
    void refreshCatalog().catch((problem) => setError((problem as Error).message));
    void request<{ skills?: { name?: string }[]; mcp_servers?: { name?: string }[] }>("/api/extensions")
      .then((data) => setGraphChoices({
        skills: (data.skills || []).map((item) => item.name || "").filter(Boolean),
        mcp: (data.mcp_servers || []).map((item) => item.name || "").filter(Boolean),
      }))
      .catch(() => setGraphChoices({ skills: [], mcp: [] }));
    try {
      const savedDraft = JSON.parse(sessionStorage.getItem(GRAPH_DRAFT_KEY) || "null") as
        | { document?: GraphDoc; path?: string; goal?: string }
        | null;
      if (savedDraft?.document) {
        setDraft(savedDraft.document);
        setNodes(cardsFrom(savedDraft.document));
        setDraftPath(savedDraft.path || "workflow.agraph.yaml");
        setGoal(savedDraft.goal || "");
        setStatus("Unsaved draft restored");
      }
      const saved = JSON.parse(sessionStorage.getItem(GRAPH_RUN_KEY) || "null") as
        | { job_id?: string; run_id?: string; path?: string }
        | null;
      const statusId = saved?.job_id || saved?.run_id || "";
      if (statusId && saved?.path) {
        setPath(saved.path);
        setStatus("Reconnecting…");
        watchJob(statusId, saved.path);
      }
    } catch {
      sessionStorage.removeItem(GRAPH_RUN_KEY);
    }
    return () => {
      if (poll.current) window.clearInterval(poll.current);
    };
  }, [refreshCatalog, setError, watchJob]);

  useEffect(() => {
    if (!draft) return;
    sessionStorage.setItem(GRAPH_DRAFT_KEY, JSON.stringify({ document: draft, path: draftPath, goal }));
  }, [draft, draftPath, goal]);

  useEffect(() => {
    if (!operationStarted) { setElapsed(0); return; }
    const tick = () => setElapsed(Math.max(0, Math.floor((Date.now() - operationStarted) / 1000)));
    tick();
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, [operationStarted]);

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
    if (draft || jobId) return;
    void loadSaved(path);
  }, [path, loadSaved, draft, jobId]);

  function adoptDraft(document: GraphDoc, note: string) {
    setDraft(document);
    setPlan(null);
    setNodes(cardsFrom(document));
    setStatus(note);
  }

  async function makeDraft(mode: "blank" | "ai") {
    setBusy(mode);
    setOperationStarted(Date.now());
    if (mode === "ai") {
      setStatus("Drafting…");
      setDraftActivity([]);
      setDraftStage("Starting a background graph draft…");
    }
    try {
      let created: { document: GraphDoc; node_template?: Record<string, unknown> };
      if (mode === "ai") {
        const started = await post<{ job_id?: string; message?: string }>("/api/graphs/draft/start", { goal });
        if (!started.job_id) throw new Error(started.message || "Graph generation did not return a job id.");
        setDraftJobId(started.job_id);
        let result: {
          document?: GraphDoc;
          node_template?: Record<string, unknown>;
          fallback?: boolean;
          fallback_reason?: string;
        } | undefined;
        for (let check = 0; check < 900; check += 1) {
          const state = await request<{
            status?: string; stage?: string; message?: string; activity?: DraftActivity[];
            result?: { ok?: boolean; error?: string; document?: GraphDoc; node_template?: Record<string, unknown>; fallback?: boolean; fallback_reason?: string };
          }>(`/api/graphs/draft/status?job_id=${encodeURIComponent(started.job_id)}`);
          setDraftStage(state.message || state.stage || "Generating graph…");
          setDraftActivity(state.activity || []);
          if (state.status === "succeeded") {
            result = state.result;
            if (result?.fallback) {
              notify(`The planning model did not return a valid draft. MagAgent loaded a validated capability-aware fallback instead. ${result.fallback_reason || ""}`.trim());
            }
            break;
          }
          if (state.status === "failed") throw new Error(state.result?.error || state.message || "Graph generation failed.");
          if (state.status === "cancelled") { setStatus("Generation cancelled"); return; }
          await new Promise((resolve) => window.setTimeout(resolve, 1000));
        }
        if (!result?.document) throw new Error("Graph generation timed out before producing a validated draft.");
        created = { document: result.document, node_template: result.node_template };
      } else {
        created = await post<{ document: GraphDoc; node_template?: Record<string, unknown> }>(
          "/api/graphs/draft",
          { goal, mode },
        );
      }
      if (created.node_template) setTemplate(created.node_template);
      adoptDraft(created.document, "Unsaved draft");
      setDraftPath(draftPath || "workflow.agraph.yaml");
      setPath("");
    } catch (problem) {
      setError((problem as Error).message);
      setStatus("Ready");
    } finally {
      setBusy("");
      setOperationStarted(null);
      setDraftJobId("");
    }
  }

  async function cancelDraft() {
    if (!draftJobId) return;
    try {
      await post("/api/graphs/draft/cancel", { job_id: draftJobId });
      setDraftStage("Cancellation requested; stopping the active model request…");
    } catch (problem) {
      setError((problem as Error).message);
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
    if (!Object.keys(draft.nodes || {}).length) {
      setError("Add at least one card before saving this graph. A blank board is only a starting point, not a runnable graph.");
      return;
    }
    setBusy("save");
    try {
      const savedResult = await post<{ path?: string }>("/api/graphs/save", { document: draft, path: draftPath.trim() });
      const found = await refreshCatalog();
      setDraft(null);
      sessionStorage.removeItem(GRAPH_DRAFT_KEY);
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

  function exportAuditLog() {
    const payload = {
      schema_version: "magent.graph-audit.v1",
      exported_at: new Date().toISOString(),
      job_id: jobId,
      run_id: runId,
      graph_path: path,
      status,
      activity: runActivity,
      summary: runSummary,
      nodes,
      events: auditEvents,
    };
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" }),
    );
    const anchor = window.document.createElement("a");
    anchor.href = url;
    anchor.download = `${runId || jobId || "graph-run"}-audit.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  async function run() {
    if (!path) return;
    setBusy("run");
    try {
      const started = await post<{ job_id?: string }>("/api/graphs/run", { path });
      if (!started.job_id) throw new Error("The graph runner did not return a job id.");
      setStatus("Running");
      setRunSummary("Runner accepted the graph and is preparing the first ready card.");
      setLastUpdate(Date.now());
      setEventCount(0);
      setRunId("");
      setAuditEvents([]);
      notify("Run started.");
      sessionStorage.setItem(GRAPH_RUN_KEY, JSON.stringify({ job_id: started.job_id, path }));
      watchJob(started.job_id, path);
    } catch (problem) {
      setError((problem as Error).message);
      setBusy("");
    }
  }

  async function decideGraphApproval(
    approval: GraphApproval,
    decision: "once" | "session" | "always" | "deny",
  ) {
    if (!jobId || approvalBusy) return;
    setApprovalBusy(true);
    try {
      await post("/api/graphs/approve", {
        job_id: jobId,
        request_id: approval.request_id,
        decision,
      });
      setApprovals((current) => current.filter((item) => item.request_id !== approval.request_id));
      setRunActivity(
        decision === "deny"
          ? "Permission denied; the card is handling that decision."
          : "Permission approved; the card is resuming.",
      );
      notify(decision === "deny" ? "Permission denied." : "Permission approved.");
    } catch (problem) {
      setError((problem as Error).message);
    } finally {
      setApprovalBusy(false);
    }
  }

  async function openCard(nodeId: string) {
    if (busy === "run") return;
    try {
      let document = draft;
      if (!document && path) {
        const loaded = await request<{ document: GraphDoc }>(
          `/api/graphs/document?path=${encodeURIComponent(path)}`,
        );
        document = loaded.document;
        setDraft(document);
        setDraftPath(path);
        setPlan(null);
        setJobId("");
        if (poll.current) window.clearInterval(poll.current);
      }
      const node = document?.nodes?.[nodeId];
      if (!document || !node) return;
      const requirements = (node.requirements as Record<string, unknown>) || {};
      setCardEditor({
        id: nodeId,
        title: String(node.title || nodeId),
        description: String(node.description || ""),
        profile: String(node["x-magagent-profile"] || ""),
        dependencies: (node.depends_on as string[]) || [],
        tools: ((requirements.tools as Array<string | { name?: string }>) || []).map((item) =>
          typeof item === "string" ? item : String(item.name || ""),
        ).filter(Boolean),
        skills: ((requirements.skills as string[]) || []),
        mcpServers: ((requirements.mcp_servers as string[]) || []),
        permissions: ((requirements.permissions as string[]) || []).join("\n"),
        workspace: (String(requirements.workspace || "read_only") as CardEditor["workspace"]),
      });
    } catch (problem) {
      setError((problem as Error).message);
    }
  }

  function saveCard(event: React.FormEvent) {
    event.preventDefault();
    if (!draft || !cardEditor || !draft.nodes?.[cardEditor.id]) return;
    const current = draft.nodes[cardEditor.id];
    const permissions = cardEditor.permissions
      .split(/[,\n]/)
      .map((item) => item.trim())
      .filter(Boolean);
    const requirements: Record<string, unknown> = {
      ...((current.requirements as Record<string, unknown>) || {}),
      workspace: cardEditor.workspace,
    };
    if (cardEditor.tools.length) requirements.tools = cardEditor.tools;
    else delete requirements.tools;
    if (cardEditor.skills.length) requirements.skills = cardEditor.skills;
    else delete requirements.skills;
    if (cardEditor.mcpServers.length) requirements.mcp_servers = cardEditor.mcpServers;
    else delete requirements.mcp_servers;
    if (permissions.length) requirements.permissions = permissions;
    else delete requirements.permissions;
    const updated: Record<string, unknown> = {
      ...current,
      title: cardEditor.title.trim(),
      description: cardEditor.description.trim(),
      depends_on: cardEditor.dependencies,
      requirements,
    };
    if (cardEditor.profile) updated["x-magagent-profile"] = cardEditor.profile;
    else delete updated["x-magagent-profile"];
    const document = rebuildStructure({
      ...draft,
      nodes: { ...draft.nodes, [cardEditor.id]: updated },
    });
    adoptDraft(document, "Unsaved card changes");
    setCardEditor(null);
  }

  function deleteCard() {
    if (!draft || !cardEditor) return;
    const remaining = { ...(draft.nodes || {}) };
    delete remaining[cardEditor.id];
    adoptDraft(rebuildStructure({ ...draft, nodes: remaining }), "Unsaved card deletion");
    setCardEditor(null);
  }

  const canAuthor = Boolean(draft || path);
  const running = ["queued", "running", "active", "reconnecting…"].includes(status.toLowerCase());

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

      {busy === "ai" && (
        <section className="operation-health" role="status" aria-live="polite">
          <span className="operation-spinner" aria-hidden="true" />
          <div className="operation-health-copy"><b>Generating and validating the graph</b><p>{draftStage}</p><small>{elapsed >= 90 ? "This request is taking longer than usual; you can cancel it safely. " : ""}This shows lifecycle and validation activity, not the model's private reasoning.</small>{draftActivity.length > 0 && <ol className="operation-activity">{draftActivity.slice(-5).map((item, index) => <li key={`${item.at || index}-${item.stage}`}>{item.message || item.stage}{item.attempt ? ` · attempt ${item.attempt}` : ""}{item.details?.length ? <ul>{item.details.map((detail) => <li key={detail}>{detail}</li>)}</ul> : null}</li>)}</ol>}</div>
          <button className="ghost-button operation-cancel" type="button" onClick={() => void cancelDraft()} disabled={!draftJobId}>Cancel</button>
          <span>{elapsed}s</span>
        </section>
      )}

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
            <button className="ghost-button" type="button" onClick={() => { setDraft(null); sessionStorage.removeItem(GRAPH_DRAFT_KEY); void loadSaved(path); }}>
              Discard
            </button>
          </div>
        </section>
      )}

      <section className="graph-picker">
        <label htmlFor="graphSelect">Graph file</label>
        <select id="graphSelect" value={path} onChange={(event) => {
          setJobId("");
          setRunSummary("");
          sessionStorage.removeItem(GRAPH_RUN_KEY);
          setPath(event.target.value);
        }}>
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

      {jobId && !draft && (
        <section className={`graph-run-health ${running ? "running" : "settled"}`} aria-live="polite">
          <span className="run-health-dot" aria-hidden="true" />
          <div>
            <b>{running ? "Graph runner is active" : `Graph run ${status}`}</b>
            <p className="graph-run-activity">
              <span>Most recent activity</span>
              {runActivity || (running ? "Waiting for the next runner event…" : runSummary || "The latest run state is shown on the board.")}
            </p>
            {!running && runSummary && runSummary !== runActivity && <p>{runSummary}</p>}
          </div>
          <dl>
            <div><dt>Status</dt><dd>{status}</dd></div>
            <div><dt>Events</dt><dd>{eventCount}</dd></div>
            <div><dt>Job</dt><dd title={jobId}>{jobId}</dd></div>
            <div><dt>Last check</dt><dd>{lastUpdate ? new Date(lastUpdate).toLocaleTimeString() : "—"}</dd></div>
          </dl>
        </section>
      )}

      {jobId && !draft && (
        <details className="graph-audit-log">
          <summary>Run audit log · {auditEvents.length} event{auditEvents.length === 1 ? "" : "s"}</summary>
          <div className="graph-audit-head">
            <p>Safe lifecycle evidence for debugging. Tool arguments and secrets are not included.</p>
            <button className="ghost-button" type="button" onClick={exportAuditLog}>Download JSON</button>
          </div>
          {auditEvents.length ? (
            <ol>
              {auditEvents.slice(-100).map((event, index) => (
                <li key={`${event.timestamp || "event"}-${index}`}>
                  <div><b>{event.type || "graph.event"}</b>{event.error_code && <span>{event.error_code}</span>}</div>
                  <p>{auditEventText(event)}</p>
                  {event.timestamp && <time>{new Date(event.timestamp).toLocaleString()}</time>}
                </li>
              ))}
            </ol>
          ) : <p>No lifecycle events have arrived yet.</p>}
        </details>
      )}

      {approvals.length > 0 && createPortal(
        <div className="modal-backdrop graph-approval-backdrop" role="presentation">
          <section
            className="modal graph-approval-modal"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="graphApprovalTitle"
            aria-describedby="graphApprovalDescription"
          >
            <div className="dialog-head">
              <div>
                <div className="eyebrow">PERMISSION REQUIRED</div>
                <h2 id="graphApprovalTitle">Graph card needs your approval</h2>
              </div>
              {approvals.length > 1 && <span className="tag">{approvals.length} waiting</span>}
            </div>
            <p id="graphApprovalDescription">
              {approvals[0].node_id ? `Card ${approvals[0].node_id} is waiting before it can continue.` : "The active graph card is waiting before it can continue."}
            </p>
            <code className="graph-approval-command">{approvals[0].description}</code>
            <p className="context-note">
              Review the exact action. Closing or navigating in the UI does not approve it automatically.
            </p>
            <div className="graph-approval-actions">
              <button
                className="danger-button"
                type="button"
                disabled={approvalBusy}
                onClick={() => void decideGraphApproval(approvals[0], "deny")}
              >
                Deny
              </button>
              <button
                className="primary-button"
                type="button"
                disabled={approvalBusy}
                onClick={() => void decideGraphApproval(approvals[0], "once")}
              >
                Approve once
              </button>
              {approvals[0].choices.includes("session") && (
                <button
                  className="ghost-button"
                  type="button"
                  disabled={approvalBusy}
                  onClick={() => void decideGraphApproval(approvals[0], "session")}
                >
                  For this session
                </button>
              )}
              {approvals[0].choices.includes("always") && (
                <button
                  className="ghost-button"
                  type="button"
                  disabled={approvalBusy}
                  title="Save this exact shell command as a trusted approval for future sessions."
                  onClick={() => void decideGraphApproval(approvals[0], "always")}
                >
                  Always allow exact command
                </button>
              )}
            </div>
          </section>
        </div>,
        document.body,
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
                cards.map((node) => (
                  <Card key={node.id} node={node} editable={!running} onEdit={() => void openCard(node.id)} />
                ))
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


      {cardEditor && (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={`Edit ${cardEditor.title}`}
          onClick={(event) => { if (event.target === event.currentTarget) setCardEditor(null); }}>
          <form className="modal graph-card-editor" onSubmit={saveCard}>
            <div className="dialog-head"><div><div className="eyebrow">GRAPH CARD</div><h2>Edit {cardEditor.id}</h2></div><button className="icon-button" type="button" onClick={() => setCardEditor(null)}>×</button></div>
            <label>Title<input required value={cardEditor.title} onChange={(event) => setCardEditor({ ...cardEditor, title: event.target.value })} /></label>
            <label>Description<textarea required rows={4} value={cardEditor.description} onChange={(event) => setCardEditor({ ...cardEditor, description: event.target.value })} /></label>
            <label>Agent profile<select value={cardEditor.profile} onChange={(event) => setCardEditor({ ...cardEditor, profile: event.target.value })}><option value="">Run default</option>{profiles.map((profile) => <option key={profile.name} value={profile.name}>@{profile.name}</option>)}</select></label>
            <fieldset className="dependency-picker"><legend>Dependencies</legend><p>This card waits until every selected card completes.</p><div>{nodes.filter((item) => item.id !== cardEditor.id).map((item) => <label key={item.id}><input type="checkbox" checked={cardEditor.dependencies.includes(item.id)} onChange={(event) => setCardEditor({ ...cardEditor, dependencies: event.target.checked ? [...cardEditor.dependencies, item.id] : cardEditor.dependencies.filter((id) => id !== item.id) })} />{item.title}</label>)}</div></fieldset>
            <fieldset className="capability-picker"><legend>Declared tool capabilities</legend><p>The runner blocks every tool not declared here. Choose everything this card may need.</p><div>{GRAPH_TOOLS.map(([name, label]) => <label key={name}><input type="checkbox" checked={cardEditor.tools.includes(name)} onChange={(event) => {
              const tools = event.target.checked ? [...cardEditor.tools, name] : cardEditor.tools.filter((item) => item !== name);
              const suggested = name === "file_write" ? ["fs:read:**", "fs:write:**"] : name === "shell_exec" ? ["shell:exec:*"] : name.startsWith("web_") || name === "browser" ? ["net:fetch:https://**"] : name.startsWith("file_") ? ["fs:read:**"] : [];
              const currentPermissions = cardEditor.permissions.split(/[,\n]/).map((item) => item.trim()).filter(Boolean);
              setCardEditor({ ...cardEditor, tools, permissions: event.target.checked ? Array.from(new Set([...currentPermissions, ...suggested])).join("\n") : cardEditor.permissions });
            }} /> <span><b>{name}</b><small>{label}</small></span></label>)}</div>
              <label>Additional tool names<input value={cardEditor.tools.filter((tool) => !GRAPH_TOOLS.some(([known]) => known === tool)).join(", ")} placeholder="custom_tool, another_tool" onChange={(event) => { const known = cardEditor.tools.filter((tool) => GRAPH_TOOLS.some(([name]) => name === tool)); const custom = event.target.value.split(",").map((item) => item.trim()).filter(Boolean); setCardEditor({ ...cardEditor, tools: [...known, ...custom] }); }} /></label>
            </fieldset>
            {(graphChoices.skills.length > 0 || graphChoices.mcp.length > 0) && <div className="form-grid">
              <fieldset className="compact-picker"><legend>Skills</legend>{graphChoices.skills.map((name) => <label key={name}><input type="checkbox" checked={cardEditor.skills.includes(name)} onChange={(event) => setCardEditor({ ...cardEditor, skills: event.target.checked ? [...cardEditor.skills, name] : cardEditor.skills.filter((item) => item !== name) })} />{name}</label>)}</fieldset>
              <fieldset className="compact-picker"><legend>MCP servers</legend>{graphChoices.mcp.map((name) => <label key={name}><input type="checkbox" checked={cardEditor.mcpServers.includes(name)} onChange={(event) => setCardEditor({ ...cardEditor, mcpServers: event.target.checked ? [...cardEditor.mcpServers, name] : cardEditor.mcpServers.filter((item) => item !== name) })} />{name}</label>)}</fieldset>
            </div>}
            <div className="form-grid"><label>Workspace access<select value={cardEditor.workspace} onChange={(event) => setCardEditor({ ...cardEditor, workspace: event.target.value as CardEditor["workspace"] })}><option value="none">None</option><option value="read_only">Read only</option><option value="read_write">Read and write</option></select></label><label>Permissions <small>one per line</small><textarea rows={4} value={cardEditor.permissions} placeholder={"fs:read:**\nfs:write:src/**\nshell:exec:pytest*"} onChange={(event) => setCardEditor({ ...cardEditor, permissions: event.target.value })} /></label></div>
            <p className="context-note">Saving updates the draft only. Use Save graph above to validate and write it.</p>
            <div className="graph-card-dialog-actions"><button className="danger-button" type="button" onClick={deleteCard}>Delete card</button><span /><button className="ghost-button" type="button" onClick={() => setCardEditor(null)}>Cancel</button><button className="primary-button" type="submit">Apply changes</button></div>
          </form>
        </div>
      )}
    </div>
  );
}
