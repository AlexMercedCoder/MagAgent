import { useEffect, useRef, useState } from "react";
import { post, request } from "../api";
import type { Profile } from "../types";

type Effective = {
  ok?: boolean;
  name?: string;
  description?: string;
  tools?: string[];
  permissions?: Record<string, string> | string[];
  model?: string;
  provider?: string;
  digest?: string;
  profile_digest?: string;
  revision?: number;
  trust?: string;
  source?: string;
  skills?: string[] | null;
  mcp_servers?: string[] | null;
  permission_mode?: string;
  network_access?: string;
  document?: Record<string, any>;
  error?: string;
};

type ProviderChoice = { name?: string; id?: string; display_name?: string; default_model?: string };
type ProfileChoices = {
  tools: { name: string; description?: string }[];
  skills: { name: string; description?: string }[];
  mcp_servers: string[];
  permission_modes: string[];
  network_modes: string[];
};

const emptyChoices: ProfileChoices = { tools: [], skills: [], mcp_servers: [], permission_modes: ["paranoid", "balanced", "silent", "yolo"], network_modes: ["none", "read", "full"] };

/** Browse Open Agent Profiles and inspect the authority each one resolves to. */
export function ProfilesView({
  profiles,
  refresh,
  setError,
  notify,
}: {
  profiles: Profile[];
  refresh: () => Promise<void>;
  setError: (message: string) => void;
  notify: (message: string) => void;
}) {
  const [selected, setSelected] = useState<string>(profiles[0]?.name ?? "");
  const [detail, setDetail] = useState<Effective | null>(null);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState(false);
  const [providers, setProviders] = useState<ProviderChoice[]>([]);
  const [choices, setChoices] = useState<ProfileChoices>(emptyChoices);
  const [cloneName, setCloneName] = useState("");
  const [form, setForm] = useState({
    name: "",
    description: "",
    instructions: "",
    provider: "",
    model: "",
    tools: [] as string[],
    skills: [] as string[],
    mcp_servers: [] as string[],
    permission_mode: "",
    network_mode: "",
  });
  const importInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    request<{ providers?: ProviderChoice[] }>("/api/onboarding/providers")
      .then((data) => setProviders(data.providers || []))
      .catch(() => setProviders([]));
  }, []);

  useEffect(() => {
    request<{ choices?: Partial<ProfileChoices> }>("/api/profiles/contract")
      .then((data) => setChoices({ ...emptyChoices, ...(data.choices || {}) }))
      .catch(() => setChoices(emptyChoices));
  }, []);

  /** Download the selected identity as a portable OAP document. */
  async function exportProfile(name: string) {
    try {
      const payload = await request<{ filename: string; document: unknown }>(
        `/api/profiles/export?name=${encodeURIComponent(name)}`,
      );
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(payload.document, null, 2)], { type: "application/json" }),
      );
      const anchor = window.document.createElement("a");
      anchor.href = url;
      anchor.download = payload.filename.replace(/\.md$/, ".json");
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (problem) {
      setError((problem as Error).message);
    }
  }

  /** Adopt an OAP document from a file as a project profile. */
  async function importProfile(file: File) {
    try {
      const document = JSON.parse(await file.text());
      await post("/api/profiles/import", { document, scope: "project" });
      await refresh();
      notify("Profile imported.");
    } catch (problem) {
      setError(
        String(problem).includes("JSON")
          ? "That file is not a JSON agent profile. Export one first to see the shape."
          : (problem as Error).message,
      );
    }
  }

  useEffect(() => {
    if (!selected && profiles[0]) setSelected(profiles[0].name);
  }, [profiles, selected]);

  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    (async () => {
      try {
        const data = await request<{ profile?: Effective; effective_profile?: Effective }>(
          `/api/profile?name=${encodeURIComponent(selected)}`,
        );
        if (!cancelled) {
          const resolved = data.profile || {};
          const effective = data.effective_profile || {};
          const metadata = resolved.document?.metadata || {};
          setDetail({ ...resolved, ...effective, description: String(metadata.description || "") });
          setError("");
        }
      } catch (problem) {
        if (!cancelled) setError((problem as Error).message);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selected, setError]);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    try {
      await post("/api/profiles", {
        ...form,
        // Only send a route when one was actually chosen; otherwise inherit.
        ...(form.provider || form.model
          ? { model: { provider: form.provider || undefined, model: form.model || undefined } }
          : {}),
        ...(editing ? { expected_digest: detail?.profile_digest || detail?.digest || "" } : {}),
        tools: form.tools,
        skills: form.skills,
        mcp_servers: form.mcp_servers,
        permission_mode: form.permission_mode || undefined,
        network_mode: form.network_mode || undefined,
      });
      setCreating(false);
      setForm({ name: "", description: "", instructions: "", provider: "", model: "", tools: [], skills: [], mcp_servers: [], permission_mode: "", network_mode: "" });
      await refresh();
      notify(`Profile ${form.name} ${editing ? "updated" : "created"}.`);
      setSelected(form.name);
      setEditing(false);
    } catch (problem) {
      setError((problem as Error).message);
    }
  }

  const permissions = detail?.permissions;
  const writable = Boolean(detail && detail.source !== "managed");

  async function editProfile() {
    if (!selected) return;
    try {
      const exported = await request<{ document?: Record<string, any> }>(`/api/profiles/export?name=${encodeURIComponent(selected)}`);
      const document = exported.document || {};
      const metadata = document.metadata || {};
      const spec = document.spec || {};
      const tools = spec.tools || {};
      const references = (value: any[]) => (value || []).map((item) => typeof item === "string" ? item : item.name).filter(Boolean);
      setForm({
        name: selected,
        description: String(metadata.description || detail?.description || ""),
        instructions: String(spec.role?.instructions || ""),
        provider: String(spec.model?.provider || ""),
        model: String(spec.model?.id || ""),
        tools: (tools.allow || []).map(String),
        skills: references(tools.skills || []),
        mcp_servers: references(tools.mcp_servers || []),
        permission_mode: String({ deny: "paranoid", ask: "balanced", allow: "silent" }[spec.permissions?.default as "deny"] || spec.permissions?.default || ""),
        network_mode: String({ deny: "none", allow: "read" }[spec.permissions?.network as "deny"] || spec.permissions?.network || ""),
      });
      setEditing(true);
      setCreating(true);
    } catch (problem) { setError((problem as Error).message); }
  }

  async function cloneManaged(event: React.FormEvent) {
    event.preventDefault();
    if (!selected || !cloneName.trim()) return;
    try {
      await post("/api/profiles/clone", { source: selected, name: cloneName.trim(), scope: "project" });
      await refresh();
      setSelected(cloneName.trim());
      setCloneName("");
      notify(`Created editable profile @${cloneName.trim()}.`);
    } catch (problem) {
      setError((problem as Error).message);
    }
  }

  async function deleteSelected() {
    if (!selected || !detail) return;
    if (!window.confirm(`Delete profile @${selected}? Existing conversations keep their transcript but can no longer run with it.`)) return;
    try {
      await post("/api/profiles/delete", { name: selected, expected_digest: detail.profile_digest || detail.digest || "" });
      setSelected("");
      setDetail(null);
      await refresh();
      notify(`Profile ${selected} deleted.`);
    } catch (problem) { setError((problem as Error).message); }
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <div className="eyebrow">OPEN AGENT PROFILE</div>
          <h1>Profiles</h1>
          <p>Inspect effective authority or create a reusable specialist.</p>
        </div>
        <div className="profile-actions">
          <input
            ref={importInput}
            type="file"
            accept=".json,application/json"
            hidden
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void importProfile(file);
              event.target.value = "";
            }}
          />
          <button className="ghost-button" type="button" onClick={() => importInput.current?.click()}>
            ↑ Import
          </button>
          <button className="ghost-button" type="button" disabled={!selected}
                  onClick={() => selected && void exportProfile(selected)}>
            ↓ Export
          </button>
          <button className="primary-button" type="button" onClick={() => { setEditing(false); setForm({ name: "", description: "", instructions: "", provider: "", model: "", tools: [], skills: [], mcp_servers: [], permission_mode: "", network_mode: "" }); setCreating(true); }}>
            ＋ New profile
          </button>
        </div>
      </div>

      <div className="profile-layout">
        <div className="profile-list">
          {profiles.map((profile) => (
            <button
              key={profile.name}
              type="button"
              className={`profile-row ${selected === profile.name ? "active" : ""}`}
              onClick={() => setSelected(profile.name)}
            >
              <b>@{profile.name}</b>
              <small>{profile.trust || profile.source || "project"}</small>
            </button>
          ))}
          {!profiles.length && <div className="empty-small"><b>No profiles</b></div>}
        </div>

        <div className="detail-card">
          {detail ? (
            <>
              <div className="eyebrow">PROFILE DETAIL</div>
              <h3>@{detail.name || selected}</h3>
              <p>{detail.description || "No description."}</p>
              <dl>
                <dt>Provider</dt><dd>{detail.provider || "inherit"}</dd>
                <dt>Model</dt><dd>{detail.model || "inherit"}</dd>
                <dt>Permission mode</dt><dd>{detail.permission_mode || "inherit"}</dd>
                <dt>Network</dt><dd>{detail.network_access || "inherit"}</dd>
                <dt>Digest</dt><dd className="mono">{(detail.profile_digest || detail.digest || "—").slice(0, 24)}</dd>
              </dl>
              {detail.tools?.length ? (
                <>
                  <div className="eyebrow">TOOLS</div>
                  <div className="chip-row">
                    {detail.tools.map((tool) => <span className="chip" key={tool}>{tool}</span>)}
                  </div>
                </>
              ) : null}
              {detail.skills?.length ? <><div className="eyebrow">SKILLS</div><div className="chip-row">{detail.skills.map((skill) => <span className="chip" key={skill}>{skill}</span>)}</div></> : null}
              {detail.mcp_servers?.length ? <><div className="eyebrow">MCP SERVERS</div><div className="chip-row">{detail.mcp_servers.map((server) => <span className="chip" key={server}>{server}</span>)}</div></> : null}
              {permissions && (
                <>
                  <div className="eyebrow">EFFECTIVE AUTHORITY</div>
                  <div className="authority-grid">
                    {Array.isArray(permissions)
                      ? permissions.map((item) => (
                          <div key={item}><b>{item}</b></div>
                        ))
                      : Object.entries(permissions).map(([key, value]) => (
                          <div key={key}><small>{key}</small><b>{String(value)}</b></div>
                        ))}
                  </div>
                </>
              )}
              <p className="context-note">
                A profile can narrow the configured tools and permissions, never widen them.
              </p>
              {writable ? <div className="detail-actions">
                <button className="ghost-button" type="button" onClick={() => void editProfile()}>Edit profile</button>
                <button className="danger-button" type="button" onClick={() => void deleteSelected()}>Delete profile</button>
              </div> : <><p className="context-note">Managed profiles are immutable OAP baselines. Make an editable project copy to choose its tools, skills, MCP servers, model, and narrower permissions.</p><button className="ghost-button" type="button" onClick={() => setCloneName(`${selected}-custom`)}>Customize as a copy</button></>}
            </>
          ) : (
            <div className="empty-panel"><h2>Select a profile</h2></div>
          )}
        </div>
      </div>

      {creating && (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="New profile"
             onClick={(event) => { if (event.target === event.currentTarget) setCreating(false); }}>
          <form className="modal" onSubmit={create}>
            <div className="dialog-head">
              <div><div className="eyebrow">{editing ? "EDIT PROFILE" : "NEW PROFILE"}</div><h2>{editing ? `Edit @${selected}` : "Create a specialist"}</h2></div>
              <button className="icon-button" type="button" onClick={() => { setCreating(false); setEditing(false); }} aria-label="Close">×</button>
            </div>
            <label htmlFor="profileName">Name</label>
            <input id="profileName" required value={form.name} disabled={editing}
                   onChange={(e) => setForm({ ...form, name: e.target.value })} />
            <label htmlFor="profileDescription">Description</label>
            <input id="profileDescription" value={form.description}
                   onChange={(e) => setForm({ ...form, description: e.target.value })} />
            <label htmlFor="profileInstructions">Role instructions</label>
            <textarea id="profileInstructions" rows={4} value={form.instructions}
                      onChange={(e) => setForm({ ...form, instructions: e.target.value })} />
            <div className="form-grid">
              <div>
                <label htmlFor="profileProvider">Provider</label>
                <select id="profileProvider" value={form.provider}
                       onChange={(e) => { const provider = providers.find((item) => (item.name || item.id) === e.target.value); setForm({ ...form, provider: e.target.value, model: provider?.default_model || form.model }); }}>
                  <option value="">Inherit workspace provider</option>{providers.map((item) => { const id = item.name || item.id || ""; return <option value={id} key={id}>{item.display_name || id}</option>; })}
                </select>
              </div>
              <div>
                <label htmlFor="profileModel">Model</label>
                <input id="profileModel" list="profileModels" placeholder="inherit" value={form.model}
                       onChange={(e) => setForm({ ...form, model: e.target.value })} />
                <datalist id="profileModels">{providers.filter((item) => !form.provider || (item.name || item.id) === form.provider).map((item) => <option key={`${item.name}-model`} value={item.default_model || ""} />)}</datalist>
              </div>
            </div>
            <div className="form-grid"><div><label htmlFor="profilePermission">Permission ceiling</label><select id="profilePermission" value={form.permission_mode} onChange={(event) => setForm({ ...form, permission_mode: event.target.value })}><option value="">Inherit workspace mode</option>{choices.permission_modes.map((mode) => <option key={mode} value={mode}>{mode}</option>)}</select></div><div><label htmlFor="profileNetwork">Network ceiling</label><select id="profileNetwork" value={form.network_mode} onChange={(event) => setForm({ ...form, network_mode: event.target.value })}><option value="">Inherit workspace network</option>{choices.network_modes.map((mode) => <option key={mode} value={mode}>{mode}</option>)}</select></div></div>
            <fieldset className="capability-picker"><legend>Allowed tools</legend><p>Unchecked tools are unavailable to this profile. Selecting none inherits the harness tool set.</p><div>{choices.tools.map((tool) => <label key={tool.name}><input type="checkbox" checked={form.tools.includes(tool.name)} onChange={(event) => setForm({ ...form, tools: event.target.checked ? [...form.tools, tool.name] : form.tools.filter((item) => item !== tool.name) })} /><span><b>{tool.name}</b><small>{tool.description}</small></span></label>)}</div></fieldset>
            {(choices.skills.length > 0 || choices.mcp_servers.length > 0) && <div className="form-grid"><fieldset className="compact-picker"><legend>Skills</legend>{choices.skills.map((skill) => <label key={skill.name}><input type="checkbox" checked={form.skills.includes(skill.name)} onChange={(event) => setForm({ ...form, skills: event.target.checked ? [...form.skills, skill.name] : form.skills.filter((item) => item !== skill.name) })} />{skill.name}</label>)}</fieldset><fieldset className="compact-picker"><legend>MCP servers</legend>{choices.mcp_servers.map((name) => <label key={name}><input type="checkbox" checked={form.mcp_servers.includes(name)} onChange={(event) => setForm({ ...form, mcp_servers: event.target.checked ? [...form.mcp_servers, name] : form.mcp_servers.filter((item) => item !== name) })} />{name}</label>)}</fieldset></div>}
            <p className="context-note">
              Leave both blank to inherit the workspace route. A profile can narrow authority, never widen it.
            </p>
            <button className="primary-button" type="submit">{editing ? "Save changes" : "Create profile"}</button>
          </form>
        </div>
      )}
      {cloneName && <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="Customize managed profile" onClick={(event) => { if (event.target === event.currentTarget) setCloneName(""); }}><form className="modal" onSubmit={cloneManaged}><div className="dialog-head"><div><div className="eyebrow">EDITABLE COPY</div><h2>Customize @{selected}</h2></div><button className="icon-button" type="button" onClick={() => setCloneName("")}>×</button></div><p>The managed original stays intact. This project copy starts with the same OAP policy and can be narrowed independently.</p><label>New profile name<input required pattern="[a-z0-9][a-z0-9._-]*" value={cloneName} onChange={(event) => setCloneName(event.target.value)} /></label><button className="primary-button" type="submit">Create editable copy</button></form></div>}
    </div>
  );
}
