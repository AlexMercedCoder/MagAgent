import { useEffect, useState } from "react";
import { post, request } from "../api";

type ExtensionData = {
  plugins?: { name: string; version?: string; enabled: boolean; valid?: boolean; integrity?: string }[];
  skills?: { name: string; description?: string; version?: string }[];
  mcp_servers?: { name: string; enabled: boolean }[];
  capabilities?: { id: string; label: string; description?: string; enabled: boolean }[];
};

export function ExtensionsView({ setError, notify }: { setError: (message: string) => void; notify: (message: string) => void }) {
  const [data, setData] = useState<ExtensionData>({});

  async function load() {
    try { setData(await request<ExtensionData>("/api/extensions")); }
    catch (problem) { setError((problem as Error).message); }
  }
  useEffect(() => { void load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  async function toggle(name: string, enabled: boolean) {
    try {
      await post("/api/extensions/plugins", { name, enabled });
      notify(`${name} ${enabled ? "enabled" : "disabled"}`);
      await load();
    } catch (problem) { setError((problem as Error).message); }
  }

  return (
    <section className="view active page-view">
      <div className="page-head"><div><div className="eyebrow">TOOLS & INTEGRATIONS</div><h1>Extensions</h1><p>Inspect installed plugins, skills, MCP servers, and optional browser/tool backends without exposing credentials.</p></div></div>
      <div className="card-grid">
        {(data.capabilities || []).map((item) => <article className="detail-card" key={item.id}><h3>{item.label}</h3><p>{item.description}</p><span className="tag">{item.enabled ? "Ready" : "Not configured"}</span></article>)}
      </div>
      <h2>Plugins</h2>
      <div className="card-grid">
        {(data.plugins || []).map((item) => <article className="detail-card" key={item.name}><h3>{item.name}</h3><p>Version {item.version || "unknown"} · integrity {item.integrity || "unrecorded"}</p><button className="secondary-button" disabled={item.valid === false && !item.enabled} type="button" onClick={() => void toggle(item.name, !item.enabled)}>{item.enabled ? "Disable" : "Enable"}</button></article>)}
        {!(data.plugins || []).length && <p>No plugins installed.</p>}
      </div>
      <h2>Skills</h2>
      <div className="card-grid">{(data.skills || []).map((item) => <article className="detail-card" key={`${item.name}-${item.version}`}><h3>{item.name}</h3><p>{item.description}</p><span className="tag">v{item.version}</span></article>)}</div>
      <h2>MCP servers</h2>
      <div className="card-grid">{(data.mcp_servers || []).map((item) => <article className="detail-card" key={item.name}><h3>{item.name}</h3><span className="tag">{item.enabled ? "Enabled" : "Disabled"}</span></article>)}</div>
    </section>
  );
}
