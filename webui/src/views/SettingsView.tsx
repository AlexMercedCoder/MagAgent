import { useEffect, useState } from "react";
import { post, request } from "../api";
import type { Profile, SettingField } from "../types";

/**
 * Guided, non-secret configuration. The server rejects any path outside its
 * own schema, so nothing here can reach a credential.
 */
export function SettingsView({
  fields,
  profiles,
  refresh,
  setError,
  notify,
}: {
  fields: SettingField[];
  profiles: Profile[];
  refresh: () => Promise<void>;
  setError: (message: string) => void;
  notify: (message: string) => void;
}) {
  const [saving, setSaving] = useState("");
  const [providers, setProviders] = useState<{ name: string; display_name?: string; default_model?: string }[]>([]);

  useEffect(() => {
    request<{ providers?: { name: string; display_name?: string; default_model?: string }[] }>("/api/onboarding/providers")
      .then((data) => setProviders(data.providers || []))
      .catch(() => setProviders([]));
  }, []);

  async function save(field: SettingField, value: string | number | boolean) {
    setSaving(field.path);
    try {
      await post("/api/settings", { path: field.path, value });
      await refresh();
      notify(`${field.label} saved.`);
    } catch (problem) {
      setError((problem as Error).message);
    } finally {
      setSaving("");
    }
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <div className="eyebrow">GUIDED CONFIGURATION</div>
          <h1>Settings</h1>
          <p>Safe defaults only. Credentials stay in your environment or the OS keyring.</p>
        </div>
      </div>
      {fields.length ? (
        <div className="setting-list">
          {fields.map((field) => (
            <article className="setting-card" key={field.path}>
              <label htmlFor={`setting-${field.path}`}>
                <b>{field.label}</b>
                {field.description && <small>{field.description}</small>}
              </label>
              {field.path === "defaults.provider" ? (
                <select id={`setting-${field.path}`} defaultValue={String(field.value ?? "")} disabled={saving === field.path} onChange={(event) => void save(field, event.target.value)}>
                  {field.value && !providers.some((item) => item.name === field.value) && <option value={String(field.value)}>{String(field.value)}</option>}
                  <option value="">Choose a provider…</option>{providers.map((provider) => <option value={provider.name} key={provider.name}>{provider.display_name || provider.name}</option>)}
                </select>
              ) : field.path === "defaults.model" ? (
                <select id={`setting-${field.path}`} defaultValue={String(field.value ?? "")} disabled={saving === field.path} onChange={(event) => void save(field, event.target.value)}>
                  {field.value && !providers.some((item) => item.default_model === field.value) && <option value={String(field.value)}>{String(field.value)}</option>}
                  <option value="">Use provider default</option>{Array.from(new Set(providers.map((item) => item.default_model).filter(Boolean))).map((model) => <option value={model} key={model}>{model}</option>)}
                </select>
              ) : field.path === "agent_profiles.default_profile" ? (
                <select id={`setting-${field.path}`} defaultValue={String(field.value ?? "")} disabled={saving === field.path} onChange={(event) => void save(field, event.target.value)}>
                  <option value="">No default profile</option>{profiles.map((profile) => <option value={profile.name} key={profile.name}>@{profile.name}</option>)}
                </select>
              ) : field.choices?.length ? (
                <select
                  id={`setting-${field.path}`}
                  defaultValue={String(field.value ?? "")}
                  disabled={saving === field.path}
                  onChange={(event) => void save(field, event.target.value)}
                >
                  {field.choices.map((choice) => (
                    <option key={choice} value={choice}>{choice}</option>
                  ))}
                </select>
              ) : field.type === "boolean" ? (
                <input
                  id={`setting-${field.path}`}
                  type="checkbox"
                  defaultChecked={Boolean(field.value)}
                  disabled={saving === field.path}
                  onChange={(event) => void save(field, event.target.checked)}
                />
              ) : (
                <input
                  id={`setting-${field.path}`}
                  type={field.type === "integer" ? "number" : "text"}
                  defaultValue={String(field.value ?? "")}
                  disabled={saving === field.path}
                  onBlur={(event) => {
                    if (event.target.value !== String(field.value ?? "")) {
                      void save(field, field.type === "integer" ? Number(event.target.value) : event.target.value);
                    }
                  }}
                />
              )}
            </article>
          ))}
        </div>
      ) : (
        <div className="empty-panel">
          <h2>Nothing editable here</h2>
          <p>Run <code>magent configure</code> for the full wizard.</p>
        </div>
      )}
    </div>
  );
}
