import { useEffect, useState } from "react";
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
  error?: string;
};

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
  const [form, setForm] = useState({ name: "", description: "", instructions: "" });

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
      await post("/api/profiles", form);
      setCreating(false);
      setForm({ name: "", description: "", instructions: "" });
      await refresh();
      notify(`Profile ${form.name} created.`);
      setSelected(form.name);
    } catch (problem) {
      setError((problem as Error).message);
    }
  }

  const permissions = detail?.permissions;

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <div className="eyebrow">OPEN AGENT PROFILE</div>
          <h1>Profiles</h1>
          <p>Inspect effective authority or create a reusable specialist.</p>
        </div>
        <button className="primary-button" type="button" onClick={() => setCreating(true)}>
          ＋ New profile
        </button>
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
              <div><div className="eyebrow">NEW PROFILE</div><h2>Create a specialist</h2></div>
              <button className="icon-button" type="button" onClick={() => setCreating(false)} aria-label="Close">×</button>
            </div>
            <label htmlFor="profileName">Name</label>
            <input id="profileName" required value={form.name}
                   onChange={(e) => setForm({ ...form, name: e.target.value })} />
            <label htmlFor="profileDescription">Description</label>
            <input id="profileDescription" value={form.description}
                   onChange={(e) => setForm({ ...form, description: e.target.value })} />
            <label htmlFor="profileInstructions">Role instructions</label>
            <textarea id="profileInstructions" rows={4} value={form.instructions}
                      onChange={(e) => setForm({ ...form, instructions: e.target.value })} />
            <button className="primary-button" type="submit">Create profile</button>
          </form>
        </div>
      )}
    </div>
  );
}
