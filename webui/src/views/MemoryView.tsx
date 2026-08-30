import { useCallback, useEffect, useState } from "react";
import { post, request } from "../api";

/**
 * Memory browser.
 *
 * MagAgent's memory is a linked graph of notes the agent wrote about the user
 * and their projects, and it shapes every reply. The browser could only see the
 * promotion inbox, so the memory already in force was invisible: no way to ask
 * what the agent believes, or where a belief came from.
 *
 * Everything here reads. Editing, merging, and deletion stay in the CLI, where
 * the destructive commands already have their confirmations.
 */

type Row = { id: string; type: string; excerpt: string; links: string[]; path: string };

type Overview = {
  ok?: boolean;
  available?: boolean;
  note?: string;
  error?: string;
  stats?: Record<string, unknown>;
  quality?: { nodes?: number; duplicate_groups?: number; suppressed?: string[] };
  nodes?: Row[];
  total?: number;
  truncated?: boolean;
};

type Node = {
  ok?: boolean;
  error?: string;
  id?: string;
  type?: string;
  path?: string;
  body?: string;
  truncated?: boolean;
  links?: string[];
  backlinks?: string[];
};

const MODES = ["keyword", "hybrid", "semantic"] as const;

function bytes(value: unknown): string {
  const size = Number(value || 0);
  if (!size) return "0 B";
  const units = ["B", "KB", "MB"];
  const index = Math.min(units.length - 1, Math.floor(Math.log(size) / Math.log(1024)));
  return `${(size / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}`;
}

export function MemoryView({ setError, notify }: { setError: (message: string) => void; notify: (message: string) => void }) {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<(typeof MODES)[number]>("keyword");
  const [results, setResults] = useState<Row[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [selected, setSelected] = useState<Node | null>(null);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({ id: "", type: "fact", body: "", links: "" });

  const load = useCallback(async () => {
    try {
      setOverview(await request<Overview>("/api/memory/overview"));
    } catch (problem) {
      setError((problem as Error).message);
    }
  }, [setError]);

  useEffect(() => {
    void load();
  }, [load]);

  async function runSearch() {
    if (!query.trim()) {
      setResults(null);
      return;
    }
    setSearching(true);
    try {
      const found = await request<{ results: Row[] }>(
        `/api/memory/search?q=${encodeURIComponent(query)}&mode=${mode}`,
      );
      setResults(found.results || []);
    } catch (problem) {
      setError((problem as Error).message);
    } finally {
      setSearching(false);
    }
  }

  async function open(id: string) {
    try {
      const found = await request<Node>(`/api/memory/node?id=${encodeURIComponent(id)}`);
      if (!found.ok) {
        setError(found.error || "That memory node could not be read.");
        return;
      }
      setSelected(found);
    } catch (problem) {
      setError((problem as Error).message);
    }
  }

  function beginCreate() {
    setForm({ id: "", type: "fact", body: "", links: "" });
    setEditing(true);
  }

  function beginEdit() {
    if (!selected) return;
    setForm({ id: selected.id || "", type: selected.type || "fact", body: selected.body || "", links: (selected.links || []).join(", ") });
    setEditing(true);
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    const exists = Boolean(selected && selected.id === form.id);
    try {
      const result = await post<Node>("/api/memory/nodes", {
        action: exists ? "update" : "create",
        id: form.id,
        type: form.type,
        body: form.body,
        links: form.links.split(",").map((item) => item.trim()).filter(Boolean),
      });
      setEditing(false);
      setSelected(result);
      await load();
      notify(`Memory ${exists ? "updated" : "created"}.`);
    } catch (problem) { setError((problem as Error).message); }
  }

  async function remove() {
    if (!selected?.id || !window.confirm(`Delete memory “${selected.id}”? This cannot be undone.`)) return;
    try {
      await post("/api/memory/nodes", { action: "delete", id: selected.id });
      setSelected(null);
      await load();
      notify("Memory deleted.");
    } catch (problem) { setError((problem as Error).message); }
  }

  const rows = results ?? overview?.nodes ?? [];
  const stats = overview?.stats || {};

  return (
    <div className="page-view view active memory-page">
      <div className="page-head">
        <div>
          <span className="eyebrow">KNOWLEDGE</span>
          <h1>Memory</h1>
          <p>Create, review, and maintain the durable facts that shape agent replies.</p>
        </div>
        <div className="header-actions"><button className="secondary-button" type="button" onClick={() => void load()}>Refresh</button><button className="primary-button" type="button" onClick={beginCreate}>＋ New memory</button></div>
      </div>

      {overview?.error && <div className="graph-error" role="alert">{overview.error}</div>}

      {overview && overview.available === false ? (
        <p className="memory-empty">{overview.note}</p>
      ) : (
        <>
          <div className="memory-stats">
            <div>
              <span>NODES</span>
              <strong>{String(stats.nodes ?? "—")}</strong>
            </div>
            <div>
              <span>LINKS</span>
              <strong>{String(stats.edges_total ?? "—")}</strong>
            </div>
            <div>
              <span>ON DISK</span>
              <strong>{bytes(stats.disk_bytes)}</strong>
            </div>
            <div>
              <span>DUPLICATE GROUPS</span>
              <strong>{String(overview?.quality?.duplicate_groups ?? "—")}</strong>
            </div>
            <div>
              <span>SUPPRESSED</span>
              <strong>{String(overview?.quality?.suppressed?.length ?? 0)}</strong>
            </div>
          </div>

          <form
            className="memory-search"
            onSubmit={(event) => {
              event.preventDefault();
              void runSearch();
            }}
          >
            <label className="sr-only" htmlFor="memoryQuery">Search memory</label>
            <input
              id="memoryQuery"
              value={query}
              placeholder="Search what the agent remembers…"
              onChange={(event) => setQuery(event.target.value)}
            />
            <label className="sr-only" htmlFor="memoryMode">Search mode</label>
            <select
              id="memoryMode"
              value={mode}
              onChange={(event) => setMode(event.target.value as (typeof MODES)[number])}
            >
              {MODES.map((item) => (
                <option key={item} value={item}>{item}</option>
              ))}
            </select>
            <button className="primary-button" type="submit" disabled={searching}>
              {searching ? "Searching…" : "Search"}
            </button>
            {results && (
              <button
                className="secondary-button"
                type="button"
                onClick={() => {
                  setResults(null);
                  setQuery("");
                }}
              >
                Clear
              </button>
            )}
          </form>

          <p className="memory-count">
            {results
              ? `${results.length} match${results.length === 1 ? "" : "es"} for “${query}”`
              : overview?.note || `${rows.length} of ${overview?.total ?? rows.length} nodes`}
          </p>

          <div className="memory-layout">
            <div className="memory-list">
              {rows.length === 0 && <p className="memory-empty">Nothing to show.</p>}
              {rows.map((row) => (
                <button
                  key={row.id}
                  type="button"
                  className={`memory-row ${selected?.id === row.id ? "active" : ""}`}
                  onClick={() => void open(row.id)}
                >
                  <strong>{row.id}</strong>
                  <span className="tag">{row.type || "note"}</span>
                  <small>{row.excerpt}</small>
                </button>
              ))}
            </div>

            <div className="memory-detail">
              {selected ? (
                <>
                  <span className="eyebrow">{selected.type || "note"}</span>
                  <h3>{selected.id}</h3>
                  <p className="memory-path">{selected.path}</p>
                  <pre>{selected.body}</pre>
                  <div className="detail-actions"><button className="ghost-button" type="button" onClick={beginEdit}>Edit</button><button className="danger-button" type="button" onClick={() => void remove()}>Delete</button></div>
                  {selected.truncated && (
                    <p className="memory-empty">
                      This note is longer than the browser shows. Read the file for the rest.
                    </p>
                  )}
                  <div className="memory-links">
                    <div>
                      <span className="eyebrow">LINKS OUT</span>
                      {selected.links?.length ? (
                        selected.links.map((id) => (
                          <button key={id} type="button" className="link-chip" onClick={() => void open(id)}>
                            {id}
                          </button>
                        ))
                      ) : (
                        <p className="memory-empty">None.</p>
                      )}
                    </div>
                    <div>
                      <span className="eyebrow">LINKS IN</span>
                      {selected.backlinks?.length ? (
                        selected.backlinks.map((id) => (
                          <button key={id} type="button" className="link-chip" onClick={() => void open(id)}>
                            {id}
                          </button>
                        ))
                      ) : (
                        <p className="memory-empty">
                          Nothing refers to this note.
                        </p>
                      )}
                    </div>
                  </div>
                </>
              ) : (
                <p className="memory-empty">Choose a note to read it and see what links to it.</p>
              )}
            </div>
          </div>
        </>
      )}
      {editing && <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Memory editor" onClick={(event) => { if (event.target === event.currentTarget) setEditing(false); }}><form className="modal" onSubmit={save}><div className="dialog-head"><div><div className="eyebrow">DURABLE MEMORY</div><h2>{selected?.id === form.id && form.id ? "Edit memory" : "Create memory"}</h2></div><button className="icon-button" type="button" onClick={() => setEditing(false)}>×</button></div><div className="form-grid"><div><label htmlFor="memoryId">ID</label><input id="memoryId" required disabled={selected?.id === form.id && Boolean(form.id)} value={form.id} onChange={(event) => setForm({ ...form, id: event.target.value })} /></div><div><label htmlFor="memoryType">Type</label><select id="memoryType" value={form.type} onChange={(event) => setForm({ ...form, type: event.target.value })}><option value="fact">Fact</option><option value="preference">Preference</option><option value="project">Project</option><option value="decision">Decision</option><option value="bookmark">Bookmark</option></select></div></div><label htmlFor="memoryBody">Body</label><textarea id="memoryBody" rows={9} required value={form.body} onChange={(event) => setForm({ ...form, body: event.target.value })} /><label htmlFor="memoryLinks">Links <small>comma-separated memory IDs</small></label><input id="memoryLinks" value={form.links} onChange={(event) => setForm({ ...form, links: event.target.value })} /><button className="primary-button" type="submit">Save memory</button></form></div>}
    </div>
  );
}
