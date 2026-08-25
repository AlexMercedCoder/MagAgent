import { useState } from "react";
import { post } from "../api";
import type { SettingField } from "../types";

/**
 * Guided, non-secret configuration. The server rejects any path outside its
 * own schema, so nothing here can reach a credential.
 */
export function SettingsView({
  fields,
  refresh,
  setError,
  notify,
}: {
  fields: SettingField[];
  refresh: () => Promise<void>;
  setError: (message: string) => void;
  notify: (message: string) => void;
}) {
  const [saving, setSaving] = useState("");

  async function save(field: SettingField, value: string | boolean) {
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
              {field.choices?.length ? (
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
                  defaultValue={String(field.value ?? "")}
                  disabled={saving === field.path}
                  onBlur={(event) => {
                    if (event.target.value !== String(field.value ?? "")) void save(field, event.target.value);
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
