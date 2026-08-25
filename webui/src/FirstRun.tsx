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
 * Credentials are deliberately absent. `set_default_provider` can persist an
 * inline key into the global config file, and a key typed into a browser form
 * would land there, so keys stay in the environment or the system keyring and
 * this panel reports only whether one was found and which variable it expects.
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

  useEffect(() => {
    (async () => {
      try {
        const [state, list] = await Promise.all([
          request<Readiness>("/api/onboarding/readiness"),
          request<{ providers: Provider[] }>("/api/onboarding/providers"),
        ]);
        setReadiness(state);
        setProviders(list.providers || []);
      } catch (problem) {
        setError((problem as Error).message);
      }
    })();
  }, [setError]);

  useEffect(() => {
    setModel(providers.find((item) => item.name === chosen)?.default_model ?? "");
  }, [chosen, providers]);

  async function apply(provider: string, chosenModel = "") {
    setSaving(true);
    try {
      const state = await post<Readiness>("/api/onboarding/configure", {
        provider,
        model: chosenModel,
      });
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
            onChange={(event) => setChosen(event.target.value)}
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
                <p className="first-run-key">
                  Export <code>{selected.api_key_env}</code> in the shell that runs{" "}
                  <code>magent ui</code>, or store it with <code>magent auth add</code>. Keys are
                  never typed into this page.
                </p>
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
