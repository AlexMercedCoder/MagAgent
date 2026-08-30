import { useEffect, useState } from "react";
import { post, request } from "../api";

type Plugin = { name: string; version?: string; enabled: boolean; valid?: boolean; integrity?: string };
type Skill = { name: string; description?: string; version?: string; editable?: boolean; body?: string };
type Mcp = { name: string; enabled: boolean; command?: string; args?: string[]; url?: string };
type ExtensionData = { plugins?: Plugin[]; skills?: Skill[]; mcp_servers?: Mcp[]; capabilities?: { id: string; label: string; description?: string; enabled: boolean }[] };
type Kind = "plugin" | "skill" | "mcp";
type Editor = { kind: Kind; original?: string; name: string; source: string; description: string; body: string; command: string; args: string; url: string; enabled: boolean };
const emptyEditor = (kind: Kind): Editor => ({ kind, name: "", source: "", description: "", body: "", command: "", args: "", url: "", enabled: true });

export function ExtensionsView({ setError, notify }: { setError: (message: string) => void; notify: (message: string) => void }) {
  const [data, setData] = useState<ExtensionData>({});
  const [editor, setEditor] = useState<Editor | null>(null);

  async function load() {
    try { setData(await request<ExtensionData>("/api/extensions")); }
    catch (problem) { setError((problem as Error).message); }
  }
  useEffect(() => { void load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  async function toggle(name: string, enabled: boolean) {
    try { await post("/api/extensions/plugins", { name, enabled }); notify(`${name} ${enabled ? "enabled" : "disabled"}`); await load(); }
    catch (problem) { setError((problem as Error).message); }
  }

  async function save(event: React.FormEvent) {
    event.preventDefault(); if (!editor) return;
    try {
      await post("/api/extensions/manage", {
        kind: editor.kind, action: editor.kind === "plugin" ? "install" : "save", name: editor.name,
        source: editor.source, description: editor.description, body: editor.body,
        command: editor.command, args: editor.args.split("\n").map((item) => item.trim()).filter(Boolean), url: editor.url, enabled: editor.enabled,
      });
      notify(`${editor.kind} saved.`); setEditor(null); await load();
    } catch (problem) { setError((problem as Error).message); }
  }

  async function remove(kind: Kind, name: string) {
    if (!window.confirm(`Delete ${kind} “${name}”?`)) return;
    try { await post("/api/extensions/manage", { kind, action: "delete", name }); notify(`${kind} deleted.`); await load(); }
    catch (problem) { setError((problem as Error).message); }
  }

  return <section className="view active page-view extensions-page">
    <div className="page-head"><div><div className="eyebrow">TOOLS & INTEGRATIONS</div><h1>Extensions</h1><p>Install local plugins and manage project skills and MCP server registrations. Credentials remain outside this editor.</p></div></div>
    <div className="card-grid">{(data.capabilities || []).map((item) => <article className="detail-card" key={item.id}><h3>{item.label}</h3><p>{item.description}</p><span className="tag">{item.enabled ? "Ready" : "Not configured"}</span></article>)}</div>
    <div className="section-heading"><h2>Plugins</h2><button className="primary-button" type="button" onClick={() => setEditor(emptyEditor("plugin"))}>＋ Install plugin</button></div>
    <div className="card-grid">{(data.plugins || []).map((item) => <article className="detail-card" key={item.name}><h3>{item.name}</h3><p>Version {item.version || "unknown"} · integrity {item.integrity || "unrecorded"}</p><div className="detail-actions"><button className="secondary-button" disabled={item.valid === false && !item.enabled} type="button" onClick={() => void toggle(item.name, !item.enabled)}>{item.enabled ? "Disable" : "Enable"}</button><button className="danger-button" type="button" onClick={() => void remove("plugin", item.name)}>Uninstall</button></div></article>)}{!(data.plugins || []).length && <p>No plugins installed.</p>}</div>
    <div className="section-heading"><h2>Project skills</h2><button className="primary-button" type="button" onClick={() => setEditor(emptyEditor("skill"))}>＋ New skill</button></div>
    <div className="card-grid">{(data.skills || []).map((item) => <article className="detail-card" key={`${item.name}-${item.version}`}><h3>{item.name}</h3><p>{item.description}</p><span className="tag">v{item.version}</span>{item.editable && <div className="detail-actions"><button className="ghost-button" type="button" onClick={() => setEditor({ ...emptyEditor("skill"), original: item.name, name: item.name, description: item.description || "", body: String(item.body || "").replace(/^---[\s\S]*?---\s*/, "") })}>Edit</button><button className="danger-button" type="button" onClick={() => void remove("skill", item.name)}>Delete</button></div>}</article>)}</div>
    <div className="section-heading"><h2>MCP servers</h2><button className="primary-button" type="button" onClick={() => setEditor(emptyEditor("mcp"))}>＋ New server</button></div>
    <div className="card-grid">{(data.mcp_servers || []).map((item) => <article className="detail-card" key={item.name}><h3>{item.name}</h3><span className="tag">{item.enabled ? "Enabled" : "Disabled"}</span><p>{item.command || item.url || "No launch target"}</p><div className="detail-actions"><button className="ghost-button" type="button" onClick={() => setEditor({ ...emptyEditor("mcp"), original: item.name, name: item.name, command: item.command || "", args: (item.args || []).join("\n"), url: item.url || "", enabled: item.enabled })}>Edit</button><button className="danger-button" type="button" onClick={() => void remove("mcp", item.name)}>Delete</button></div></article>)}</div>
    {editor && <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={`${editor.kind} editor`} onClick={(event) => { if (event.target === event.currentTarget) setEditor(null); }}><form className="modal" onSubmit={save}><div className="dialog-head"><div><div className="eyebrow">{editor.kind.toUpperCase()}</div><h2>{editor.original ? "Edit" : "Create or install"} {editor.kind}</h2></div><button className="icon-button" type="button" onClick={() => setEditor(null)}>×</button></div><label>Name<input required value={editor.name} disabled={Boolean(editor.original)} onChange={(event) => setEditor({ ...editor, name: event.target.value })} /></label>{editor.kind === "plugin" && <label>Local source folder<input required placeholder="/path/to/plugin" value={editor.source} onChange={(event) => setEditor({ ...editor, source: event.target.value })} /></label>}{editor.kind === "skill" && <><label>Description<input required value={editor.description} onChange={(event) => setEditor({ ...editor, description: event.target.value })} /></label><label>Instructions<textarea required rows={10} value={editor.body} onChange={(event) => setEditor({ ...editor, body: event.target.value })} /></label></>}{editor.kind === "mcp" && <><label>Local command<input placeholder="npx" value={editor.command} onChange={(event) => setEditor({ ...editor, command: event.target.value, url: event.target.value ? "" : editor.url })} /></label><label>Arguments <small>one per line</small><textarea rows={4} value={editor.args} onChange={(event) => setEditor({ ...editor, args: event.target.value })} /></label><label>Remote URL<input placeholder="https://…" value={editor.url} onChange={(event) => setEditor({ ...editor, url: event.target.value, command: event.target.value ? "" : editor.command })} /></label><label className="checkbox-row"><input type="checkbox" checked={editor.enabled} onChange={(event) => setEditor({ ...editor, enabled: event.target.checked })} /> Enabled</label></>}<button className="primary-button" type="submit">Save</button></form></div>}
  </section>;
}
