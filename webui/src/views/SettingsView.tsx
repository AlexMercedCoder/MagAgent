import { useEffect, useState } from "react";
import { post, request } from "../api";
import type { Profile, SettingField } from "../types";

type ImageModelChoice = { id: string; label: string; value: string; available?: boolean };

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
  const [providers, setProviders] = useState<{ name: string; display_name?: string; default_model?: string; configured?: boolean; credential_ready?: boolean; credential_reason?: string; needs_key?: boolean }[]>([]);
  const [providerChoice, setProviderChoice] = useState("");
  const [modelChoice, setModelChoice] = useState("");
  const [credential, setCredential] = useState("");
  const [credentialStorage, setCredentialStorage] = useState<"keyring" | "config">("keyring");
  const [imageModels, setImageModels] = useState<ImageModelChoice[]>([]);

  useEffect(() => {
    request<{ providers?: typeof providers; default_provider?: string; default_model?: string; image_models?: ImageModelChoice[] }>("/api/onboarding/providers")
      .then((data) => {
        setProviders(data.providers || []);
        setProviderChoice(data.default_provider || "");
        setModelChoice(data.default_model || "");
        setImageModels(data.image_models || []);
      })
      .catch(() => setProviders([]));
  }, []);

  async function configureProvider(event: React.FormEvent) {
    event.preventDefault();
    if (!providerChoice) return;
    setSaving("provider-setup");
    try {
      await post("/api/onboarding/configure", {
        provider: providerChoice,
        model: modelChoice,
        credential,
        credential_storage: credentialStorage,
      });
      setCredential("");
      await refresh();
      notify("Provider configuration saved.");
    } catch (problem) {
      setError((problem as Error).message);
    } finally {
      setSaving("");
    }
  }

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
      <form className="provider-setup-card" onSubmit={configureProvider}>
        <div><div className="eyebrow">PROVIDER ONBOARDING</div><h2>Configure model access</h2><p>Choose the workspace default and optionally store its credential. Existing credentials are never displayed.</p></div>
        <div className="form-grid">
          <label>Provider<select value={providerChoice} onChange={(event) => { const value = event.target.value; const selected = providers.find((item) => item.name === value); setProviderChoice(value); setModelChoice(selected?.default_model || ""); }}><option value="">Choose a provider…</option>{providers.map((provider) => <option key={provider.name} value={provider.name}>{provider.display_name || provider.name}{provider.configured ? " · configured" : ""}</option>)}</select></label>
          <label>Default model<input value={modelChoice} onChange={(event) => setModelChoice(event.target.value)} placeholder={providers.find((item) => item.name === providerChoice)?.default_model || "provider default"} /></label>
        </div>
        {providerChoice && providers.find((item) => item.name === providerChoice)?.needs_key && <><label>API key <small>(leave blank to keep the existing credential)</small><input type="password" autoComplete="off" value={credential} onChange={(event) => setCredential(event.target.value)} placeholder={providers.find((item) => item.name === providerChoice)?.credential_ready ? "Credential already configured" : "Paste provider API key"} /></label><label>Credential storage<select value={credentialStorage} onChange={(event) => setCredentialStorage(event.target.value as "keyring" | "config")}><option value="keyring">OS keyring (recommended)</option><option value="config">MagAgent config file</option></select></label>{credentialStorage === "config" && <p className="credential-warning">The key will be written to MagAgent's user config. File permissions are tightened, but the OS keyring is safer when available.</p>}</>}
        <div className="provider-setup-actions"><span>{providers.find((item) => item.name === providerChoice)?.credential_reason || "Select a provider to inspect readiness."}</span><button className="primary-button" disabled={!providerChoice || saving === "provider-setup"}>{saving === "provider-setup" ? "Saving…" : "Save provider"}</button></div>
      </form>
      {fields.length ? (
        <div className="setting-list">
          {fields.map((field) => (
            <article className="setting-card" key={field.path}>
              <label htmlFor={`setting-${field.path}`}>
                <b>{field.label}</b>
                {field.description && <small>{field.description}</small>}
              </label>
              {field.path === "models.image_maker" ? (
                <select id={`setting-${field.path}`} value={String(field.value ?? "")} disabled={saving === field.path} onChange={(event) => void save(field, event.target.value)}>
                  {field.value && !imageModels.some((item) => item.value === field.value) && <option value={String(field.value)}>{String(field.value)} · current custom route</option>}
                  {imageModels.some((item) => item.available) ? <option value="">Not configured</option> : <option value="">No image models detected — configure a supported provider</option>}
                  {imageModels.map((item) => <option key={item.id} value={item.value} disabled={!item.available}>{item.label}{item.available ? "" : " · provider unavailable"}</option>)}
                </select>
              ) : field.path === "defaults.provider" ? (
                <select id={`setting-${field.path}`} value={String(field.value ?? "")} disabled={saving === field.path} onChange={(event) => void save(field, event.target.value)}>
                  {field.value && !providers.some((item) => item.name === field.value) && <option value={String(field.value)}>{String(field.value)}</option>}
                  <option value="">Choose a provider…</option>{providers.map((provider) => <option value={provider.name} key={provider.name}>{provider.display_name || provider.name}</option>)}
                </select>
              ) : field.path === "defaults.model" ? (
                <select id={`setting-${field.path}`} value={String(field.value ?? "")} disabled={saving === field.path} onChange={(event) => void save(field, event.target.value)}>
                  {field.value && !providers.some((item) => item.default_model === field.value) && <option value={String(field.value)}>{String(field.value)}</option>}
                  <option value="">Use provider default</option>{Array.from(new Set(providers.map((item) => item.default_model).filter(Boolean))).map((model) => <option value={model} key={model}>{model}</option>)}
                </select>
              ) : field.path === "agent_profiles.default_profile" ? (
                <select id={`setting-${field.path}`} value={String(field.value ?? "")} disabled={saving === field.path} onChange={(event) => void save(field, event.target.value)}>
                  <option value="">No default profile</option>{profiles.map((profile) => <option value={profile.name} key={profile.name}>@{profile.name}</option>)}
                </select>
              ) : field.choices?.length ? (
                <select
                  id={`setting-${field.path}`}
                  value={String(field.value ?? "")}
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
                  checked={Boolean(field.value)}
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
