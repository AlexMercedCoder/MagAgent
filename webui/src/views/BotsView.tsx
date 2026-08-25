import { useState } from "react";
import { post } from "../api";

/** The server caps a group at five participants. */
const MAX_GROUP = 5;
import type { Conversation, Profile } from "../types";

function initials(name = "M"): string {
  return name.split(/\s+|[-_]/).map((p) => p[0]).join("").slice(0, 2).toUpperCase() || "M";
}

/** Every Open Agent Profile, ready to start a focused conversation with. */
export function BotsView({
  profiles,
  setError,
  onStart,
  refresh,
  setActiveId,
}: {
  profiles: Profile[];
  setError: (message: string) => void;
  onStart: () => void;
  refresh: () => Promise<void>;
  setActiveId: (id: string) => void;
}) {
  const [selected, setSelected] = useState<string[]>([]);

  function toggle(name: string) {
    setSelected((current) =>
      current.includes(name)
        ? current.filter((item) => item !== name)
        : current.length >= MAX_GROUP
          ? current
          : [...current, name],
    );
  }

  async function open(kind: "bot" | "group", names: string[]) {
    try {
      const created = await post<{ conversation: Conversation }>("/api/conversations", {
        kind,
        profiles: names,
        title: kind === "group" ? `Group: ${names.join(", ")}` : `Chat with ${names[0]}`,
        // A group needs a coordinator drawn from its own participants; the
        // first one picked synthesises the round.
        ...(kind === "group" ? { coordinator: names[0] } : {}),
      });
      await refresh();
      setActiveId(created.conversation.id);
      setSelected([]);
      onStart();
    } catch (problem) {
      setError((problem as Error).message);
    }
  }

  const start = (profile: Profile) => open("bot", [profile.name]);

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <div className="eyebrow">SPECIALISTS</div>
          <h1>Your bots</h1>
          <p>Talk to any profile on its own, or pick several and put them in a room together.</p>
        </div>
      </div>
      {selected.length > 0 && (
        <div className="group-bar" role="status">
          <div>
            <b>{selected.length} selected</b>
            <span>{selected.join(" · ")}</span>
          </div>
          <div className="group-bar-actions">
            <button className="ghost-button" type="button" onClick={() => setSelected([])}>Clear</button>
            <button className="primary-button" type="button" disabled={selected.length < 2}
                    onClick={() => void open("group", selected)}>
              Start group chat
            </button>
          </div>
          {selected.length < 2 && <small className="group-hint">Pick at least two profiles for a group.</small>}
          {selected.length === MAX_GROUP && <small className="group-hint">Five is the maximum.</small>}
        </div>
      )}
      {profiles.length ? (
        <div className="bot-grid">
          {profiles.map((profile) => (
            <article className={`bot-card ${selected.includes(profile.name) ? "picked" : ""}`} key={profile.name}>
              <div className="bot-card-head">
                <div className="mini-mark">{initials(profile.name)}</div>
                <label className="bot-pick">
                  <input
                    type="checkbox"
                    checked={selected.includes(profile.name)}
                    onChange={() => toggle(profile.name)}
                    aria-label={`Add ${profile.name} to a group chat`}
                  />
                  <span>Group</span>
                </label>
              </div>
              <h2>@{profile.name}</h2>
              <p>{profile.description || "Profile-backed MagAgent specialist."}</p>
              <div className="chip-row">
                {profile.trust && <span className="chip">{profile.trust}</span>}
                {profile.revision !== undefined && <span className="chip">r{profile.revision}</span>}
              </div>
              <button type="button" className="ghost-button" onClick={() => void start(profile)}>
                Start chat →
              </button>
            </article>
          ))}
        </div>
      ) : (
        <div className="empty-panel">
          <h2>No profiles yet</h2>
          <p>Create one in Profiles, or run <code>magent profile create</code>.</p>
        </div>
      )}
    </div>
  );
}
