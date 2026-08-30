import { useEffect, useState } from "react";
import { request, post } from "./api";

/**
 * First-run setup.
 *
 * The UI assumed a provider was already configured: open it on a machine that
 * has never run `magent setup` and the first message failed with a credential
 * error, with nothing saying a provider was never chosen. This shows the same
 * readiness `magent doctor` reports and lets a provider be picked here.
 *
 * Hosted credentials can be saved to the OS keyring, or explicitly to the
 * protected MagAgent config when keyring integration is unavailable. Existing
 * secrets are never returned to the browser.
 */

type Step = {
  id: string;
  label: string;
  ok: boolean;
  local?: boolean;
  detail: string;
  env?: string;
  action: string;
};

type Readiness = {
  ready?: boolean;
  local?: boolean;
  reason?: string;
  steps?: Step[];
  blocking?: string[];
};

type Provider = {
  name: string;
  display_name: string;
  default_model: string;
  api_key_env: string;
  needs_key: boolean;
  local: boolean;
  credential_ready?: boolean;
};

export function FirstRun({
  onReady,
  setError,
}: {
  onReady: () => void;
  setError: (message: string) => void;
}) {
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [chosen, setChosen] = useState("");
  const [model, setModel] = useState("");
  const [saving, setSaving] = useState(false);
  const [credential, setCredential] = useState("");
  const [credentialStorage, setCredentialStorage] = useState<"keyring" | "config">("keyring");

  useEffect(() => {
    (async () => {
      try {
        const [state, list] = await Promise.all([
          request<Readiness>("/api/onboarding/readiness"),
          request<{ providers: Provider[]; default_provider?: string; default_model?: string }>("/api/onboarding/providers"),
        ]);
        setReadiness(state);
        setProviders(list.providers || []);
        setChosen(list.default_provider || "");
        setModel(list.default_model || "");
      } catch (problem) {
        setError((problem as Error).message);
      }
    })();
  }, [setError]);

  async function apply(provider: string, chosenModel = "") {
    setSaving(true);
    try {
      const state = await post<Readiness>("/api/onboarding/configure", {
        provider,
        model: chosenModel,
        credential,
        credential_storage: credentialStorage,
      });
      setCredential("");
      setReadiness(state);
      if (state.ready) onReady();
    } catch (problem) {
      setError((problem as Error).message);
    } finally {
      setSaving(false);
    }
  }

  if (!readiness) return null;

  const selected = providers.find((item) => item.name === chosen);
  // Offering "run a local model" is useless when the local model is exactly
  // what is failing, which is the shipped default's most common first run.
  const localOption = readiness.local ? undefined : providers.find((item) => item.local);

  return (
    <div className="first-run">
      <div className="first-run-card">
        <span className="glyph" aria-hidden="true">◆</span>
        <h1>Set up MagAgent</h1>
        <p>{readiness.reason || "This machine cannot run a turn yet."}</p>

        <ol className="first-run-steps">
          {(readiness.steps || []).map((step) => (
            <li key={step.id} className={step.ok ? "done" : "todo"}>
              <span className="mark" aria-hidden="true">{step.ok ? "✓" : "•"}</span>
              <div>
                <b>
                  {step.label}
                  {step.local && <i className="tag">local</i>}
                </b>
                <small>{step.detail}</small>
                {!step.ok && <em>{step.action}</em>}
              </div>
            </li>
          ))}
        </ol>

        <div className="first-run-choose">
          <label htmlFor="providerPick">Provider</label>
          <select
            id="providerPick"
            value={chosen}
            onChange={(event) => { const value = event.target.value; setChosen(value); setModel(providers.find((item) => item.name === value)?.default_model || ""); }}
          >
            <option value="">Choose a provider…</option>
            {providers.map((provider) => (
              <option key={provider.name} value={provider.name}>
                {provider.display_name}
              </option>
            ))}
          </select>

          {selected && (
            <>
              <label htmlFor="modelPick">Model</label>
              <input
                id="modelPick"
                value={model}
                onChange={(event) => setModel(event.target.value)}
                placeholder={selected.default_model}
              />
              {selected.needs_key && (
                <div className="first-run-credential">
                  <label htmlFor="credentialPick">API key <small>{selected.credential_ready ? "leave blank to keep the existing credential" : `or export ${selected.api_key_env}`}</small></label>
                  <input id="credentialPick" type="password" autoComplete="off" value={credential} onChange={(event) => setCredential(event.target.value)} placeholder={selected.credential_ready ? "Credential already configured" : "Paste provider API key"} />
                  <label htmlFor="credentialStorage">Credential storage</label>
                  <select id="credentialStorage" value={credentialStorage} onChange={(event) => setCredentialStorage(event.target.value as "keyring" | "config")}><option value="keyring">OS keyring (recommended)</option><option value="config">MagAgent config file</option></select>
                  {credentialStorage === "config" && <p className="credential-warning">This writes the key to MagAgent's user config. Its permissions are tightened, but the OS keyring is safer when available.</p>}
                </div>
              )}
            </>
          )}

          <div className="first-run-actions">
            <button
              className="primary-button"
              type="button"
              disabled={!chosen || saving}
              onClick={() => void apply(chosen, model)}
            >
              {saving ? "Saving…" : "Use this provider"}
            </button>
            {localOption && (
              <button
                className="secondary-button"
                type="button"
                disabled={saving}
                onClick={() => void apply(localOption.name)}
              >
                Run a local model instead
              </button>
            )}
          </div>
          {localOption && (
            <p className="first-run-note">
              A local runtime needs no key, so the whole loop can be seen before finding one.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
