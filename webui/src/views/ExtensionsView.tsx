import { useEffect, useState } from "react";
import { post, request } from "../api";

type Plugin = { name: string; version?: string; enabled: boolean; valid?: boolean; integrity?: string };
type Skill = { name: string; description?: string; version?: string; editable?: boolean; body?: string };
type Mcp = {
  name: string; enabled: boolean; transport?: "stdio" | "streamable-http" | "legacy-sse";
  protocol_mode?: "auto" | "modern" | "legacy"; command?: string; args?: string[];
  cwd?: string; env?: Record<string, string>; url?: string; headers?: Record<string, string>;
  timeout?: number; allow_deprecated_transport?: boolean;
};
type ExtensionData = { plugins?: Plugin[]; skills?: Skill[]; mcp_servers?: Mcp[]; capabilities?: { id: string; label: string; description?: string; enabled: boolean }[] };
type Kind = "plugin" | "skill" | "mcp";
type Editor = {
  kind: Kind; original?: string; name: string; source: string; description: string; body: string;
  transport: "stdio" | "streamable-http" | "legacy-sse"; protocol_mode: "auto" | "modern" | "legacy";
  command: string; args: string; cwd: string; env: string; url: string; headers: string;
  credential_env: string; timeout: number; allow_deprecated_transport: boolean; enabled: boolean;
};

const emptyEditor = (kind: Kind): Editor => ({
  kind, name: "", source: "", description: "", body: "", transport: "stdio",
  protocol_mode: "auto", command: "", args: "", cwd: "", env: "", url: "", headers: "",
  credential_env: "", timeout: 30, allow_deprecated_transport: false, enabled: true,
});

function mappingText(value?: Record<string, string>, skipAuthorization = false): string {
  return Object.entries(value || {}).filter(([key]) => !(skipAuthorization && key.toLowerCase() === "authorization"))
    .map(([key, item]) => `${key}=${item}`).join("\n");
}

function parseMapping(value: string, label: string): Record<string, string> {
  const result: Record<string, string> = {};
  for (const line of value.split("\n").map((item) => item.trim()).filter(Boolean)) {
    const separator = line.indexOf("=");
    if (separator < 1 || !line.slice(separator + 1).trim()) throw new Error(`${label} must use NAME=value, one entry per line.`);
    result[line.slice(0, separator).trim()] = line.slice(separator + 1).trim();
  }
  return result;
}

function mcpEditor(item: Mcp): Editor {
  const authorization = item.headers?.Authorization || item.headers?.authorization || "";
  const bearer = authorization.match(/^Bearer \$\{([^}]+)\}$/i)?.[1] || "";
  return {
    ...emptyEditor("mcp"), original: item.name, name: item.name, enabled: item.enabled,
    transport: item.transport || (item.url ? "streamable-http" : "stdio"),
    protocol_mode: item.protocol_mode || "auto", command: item.command || "",
    args: (item.args || []).join("\n"), cwd: item.cwd || "", env: mappingText(item.env),
    url: item.url || "", headers: mappingText(item.headers, Boolean(bearer)), credential_env: bearer,
    timeout: item.timeout || 30, allow_deprecated_transport: Boolean(item.allow_deprecated_transport),
  };
}

function mcpPayload(editor: Editor) {
  const headers = parseMapping(editor.headers, "Headers");
  if (editor.credential_env.trim()) {
    const name = editor.credential_env.trim();
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(name)) throw new Error("Credential environment variable must be a valid environment name.");
    headers.Authorization = `Bearer \${${name}}`;
  }
  return {
    kind: "mcp", action: "save", name: editor.name, transport: editor.transport,
    protocol_mode: editor.protocol_mode, command: editor.command,
    args: editor.args.split("\n").map((item) => item.trim()).filter(Boolean), cwd: editor.cwd,
    env: parseMapping(editor.env, "Environment variables"), url: editor.url, headers,
    timeout: editor.timeout, allow_deprecated_transport: editor.allow_deprecated_transport,
    enabled: editor.enabled,
  };
}

export function ExtensionsView({ setError, notify }: { setError: (message: string) => void; notify: (message: string) => void }) {
  const [data, setData] = useState<ExtensionData>({});
  const [editor, setEditor] = useState<Editor | null>(null);
  const [testing, setTesting] = useState(false);

  async function load() { try { setData(await request<ExtensionData>("/api/extensions")); } catch (problem) { setError((problem as Error).message); } }
  useEffect(() => { void load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  async function toggle(name: string, enabled: boolean) {
    try { await post("/api/extensions/plugins", { name, enabled }); notify(`${name} ${enabled ? "enabled" : "disabled"}`); await load(); }
    catch (problem) { setError((problem as Error).message); }
  }

  async function save(event: React.FormEvent) {
    event.preventDefault(); if (!editor) return;
    try {
      const payload = editor.kind === "mcp" ? mcpPayload(editor) : { kind: editor.kind, action: editor.kind === "plugin" ? "install" : "save", name: editor.name, source: editor.source, description: editor.description, body: editor.body };
      await post("/api/extensions/manage", payload); notify(`${editor.kind} saved.`); setEditor(null); await load();
    } catch (problem) { setError((problem as Error).message); }
  }

  async function testConnection() {
    if (!editor || editor.kind !== "mcp") return;
    setTesting(true);
    try { const result = await post<{ message?: string }>("/api/extensions/mcp/test", mcpPayload(editor)); notify(result.message || "MCP connection succeeded."); }
    catch (problem) { setError((problem as Error).message); } finally { setTesting(false); }
  }

  async function remove(kind: Kind, name: string) {
    if (!window.confirm(`Delete ${kind} “${name}”?`)) return;
    try { await post("/api/extensions/manage", { kind, action: "delete", name }); notify(`${kind} deleted.`); await load(); }
    catch (problem) { setError((problem as Error).message); }
  }

  return <section className="view active page-view extensions-page">
    <div className="page-head"><div><div className="eyebrow">TOOLS & INTEGRATIONS</div><h1>Extensions</h1><p>Install local plugins and manage project skills and MCP connections. Credentials are referenced by environment variable and are never revealed here.</p></div></div>
    <div className="card-grid">{(data.capabilities || []).map((item) => <article className="detail-card" key={item.id}><h3>{item.label}</h3><p>{item.description}</p><span className="tag">{item.enabled ? "Ready" : "Not configured"}</span></article>)}</div>
    <div className="section-heading"><h2>Plugins</h2><button className="primary-button" type="button" onClick={() => setEditor(emptyEditor("plugin"))}>＋ Install plugin</button></div>
    <div className="card-grid">{(data.plugins || []).map((item) => <article className="detail-card" key={item.name}><h3>{item.name}</h3><p>Version {item.version || "unknown"} · integrity {item.integrity || "unrecorded"}</p><div className="detail-actions"><button className="secondary-button" disabled={item.valid === false && !item.enabled} type="button" onClick={() => void toggle(item.name, !item.enabled)}>{item.enabled ? "Disable" : "Enable"}</button><button className="danger-button" type="button" onClick={() => void remove("plugin", item.name)}>Uninstall</button></div></article>)}{!(data.plugins || []).length && <p>No plugins installed.</p>}</div>
    <div className="section-heading"><h2>Project skills</h2><button className="primary-button" type="button" onClick={() => setEditor(emptyEditor("skill"))}>＋ New skill</button></div>
    <div className="card-grid">{(data.skills || []).map((item) => <article className="detail-card" key={`${item.name}-${item.version}`}><h3>{item.name}</h3><p>{item.description}</p><span className="tag">v{item.version}</span>{item.editable && <div className="detail-actions"><button className="ghost-button" type="button" onClick={() => setEditor({ ...emptyEditor("skill"), original: item.name, name: item.name, description: item.description || "", body: String(item.body || "").replace(/^---[\s\S]*?---\s*/, "") })}>Edit</button><button className="danger-button" type="button" onClick={() => void remove("skill", item.name)}>Delete</button></div>}</article>)}</div>
    <div className="section-heading"><div><h2>MCP servers</h2><p className="context-note">Auto-negotiation supports modern MCP and legacy-compatible servers. Transport and protocol version are separate choices.</p></div><button className="primary-button" type="button" onClick={() => setEditor(emptyEditor("mcp"))}>＋ New server</button></div>
    <div className="card-grid">{(data.mcp_servers || []).map((item) => <article className="detail-card" key={item.name}><h3>{item.name}</h3><span className="tag">{item.enabled ? "Enabled" : "Disabled"}</span><span className="tag">{item.transport || "stdio"}</span><span className="tag">protocol {item.protocol_mode || "auto"}</span><p>{item.command || item.url || "No launch target"}</p><div className="detail-actions"><button className="ghost-button" type="button" onClick={() => setEditor(mcpEditor(item))}>Edit</button><button className="danger-button" type="button" onClick={() => void remove("mcp", item.name)}>Delete</button></div></article>)}</div>
    {editor && <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={`${editor.kind} editor`} onClick={(event) => { if (event.target === event.currentTarget) setEditor(null); }}><form className="modal" onSubmit={save}><div className="dialog-head"><div><div className="eyebrow">{editor.kind.toUpperCase()}</div><h2>{editor.original ? "Edit" : "Create or install"} {editor.kind}</h2></div><button className="icon-button" type="button" onClick={() => setEditor(null)}>×</button></div><label>Name<input required value={editor.name} disabled={Boolean(editor.original)} onChange={(event) => setEditor({ ...editor, name: event.target.value })} /></label>
      {editor.kind === "plugin" && <label>Local source folder<input required placeholder="/path/to/plugin" value={editor.source} onChange={(event) => setEditor({ ...editor, source: event.target.value })} /></label>}
      {editor.kind === "skill" && <><label>Description<input required value={editor.description} onChange={(event) => setEditor({ ...editor, description: event.target.value })} /></label><label>Instructions<textarea required rows={10} value={editor.body} onChange={(event) => setEditor({ ...editor, body: event.target.value })} /></label></>}
      {editor.kind === "mcp" && <>
        <div className="form-grid"><label>Transport<select value={editor.transport} onChange={(event) => setEditor({ ...editor, transport: event.target.value as Editor["transport"] })}><option value="stdio">Local process (stdio)</option><option value="streamable-http">Remote Streamable HTTP</option><option value="legacy-sse">Legacy SSE (deprecated)</option></select></label><label>Protocol compatibility<select value={editor.protocol_mode} onChange={(event) => setEditor({ ...editor, protocol_mode: event.target.value as Editor["protocol_mode"] })}><option value="auto">Auto-negotiate (recommended)</option><option value="modern">Modern MCP only</option><option value="legacy">Legacy MCP only</option></select></label></div>
        {editor.transport === "stdio" ? <><label>Command<input required placeholder="npx" value={editor.command} onChange={(event) => setEditor({ ...editor, command: event.target.value })} /></label><label>Arguments <small>one per line</small><textarea rows={4} value={editor.args} onChange={(event) => setEditor({ ...editor, args: event.target.value })} /></label><label>Working directory <small>optional</small><input placeholder="/path/to/server" value={editor.cwd} onChange={(event) => setEditor({ ...editor, cwd: event.target.value })} /></label><label>Environment mapping <small>NAME=value, one per line; use ${"${ENV_VAR}"} for credentials</small><textarea rows={4} placeholder={"API_TOKEN=${API_TOKEN}"} value={editor.env} onChange={(event) => setEditor({ ...editor, env: event.target.value })} /></label></> : <><label>Server URL<input required type="url" placeholder="https://example.com/mcp" value={editor.url} onChange={(event) => setEditor({ ...editor, url: event.target.value })} /></label><label>Bearer credential environment variable <small>optional</small><input placeholder="MCP_ACCESS_TOKEN" value={editor.credential_env} onChange={(event) => setEditor({ ...editor, credential_env: event.target.value })} /></label><label>Additional headers <small>NAME=value, one per line; environment references supported</small><textarea rows={4} placeholder={"X-Tenant=${MCP_TENANT}"} value={editor.headers} onChange={(event) => setEditor({ ...editor, headers: event.target.value })} /></label></>}
        <div className="form-grid"><label>Connection timeout (seconds)<input type="number" min={1} max={300} value={editor.timeout} onChange={(event) => setEditor({ ...editor, timeout: Number(event.target.value) })} /></label><label className="checkbox-row"><input type="checkbox" checked={editor.enabled} onChange={(event) => setEditor({ ...editor, enabled: event.target.checked })} /> Enable after saving</label></div>
        {editor.transport === "legacy-sse" && <label className="checkbox-row warning-choice"><input type="checkbox" required checked={editor.allow_deprecated_transport} onChange={(event) => setEditor({ ...editor, allow_deprecated_transport: event.target.checked })} /> I understand legacy SSE is deprecated and explicitly allow it.</label>}
        <p className="context-note">“Modern” and “legacy” select protocol eras; the exact server version is negotiated during connection. Use Auto unless the server documents a fixed era.</p>
        <div className="mcp-test-row"><button className="ghost-button" type="button" disabled={testing} onClick={() => void testConnection()}>{testing ? "Testing…" : "Test connection"}</button><span>Testing may start the local command or contact the remote URL, but does not save it.</span></div>
      </>}
      <button className="primary-button" type="submit">Save</button></form></div>}
  </section>;
}
