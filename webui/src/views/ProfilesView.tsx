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
  error?: string;
};

type ProviderChoice = { name?: string; id?: string; display_name?: string; default_model?: string };

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
  const [form, setForm] = useState({
    name: "",
    description: "",
    instructions: "",
    provider: "",
    model: "",
  });
  const importInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    request<{ providers?: ProviderChoice[] }>("/api/onboarding/providers")
      .then((data) => setProviders(data.providers || []))
      .catch(() => setProviders([]));
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
        const data = await request<{ profile?: Effective }>(
          `/api/profile?name=${encodeURIComponent(selected)}`,
        );
        if (!cancelled) setDetail(data.profile ?? null);
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
      });
      setCreating(false);
      setForm({ name: "", description: "", instructions: "", provider: "", model: "" });
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
      setForm({
        name: selected,
        description: String(metadata.description || detail?.description || ""),
        instructions: String(spec.role?.instructions || ""),
        provider: String(spec.model?.provider || ""),
        model: String(spec.model?.id || ""),
      });
      setEditing(true);
      setCreating(true);
    } catch (problem) { setError((problem as Error).message); }
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
          <button className="primary-button" type="button" onClick={() => setCreating(true)}>
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
              </div> : <p className="context-note">This managed profile is read-only. Create a project profile to customize or remove it.</p>}
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
            <p className="context-note">
              Leave both blank to inherit the workspace route. A profile can narrow authority, never widen it.
            </p>
            <button className="primary-button" type="submit">{editing ? "Save changes" : "Create profile"}</button>
          </form>
        </div>
      )}
    </div>
  );
}
