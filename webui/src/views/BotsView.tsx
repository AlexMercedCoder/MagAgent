import { post } from "../api";
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
  async function start(profile: Profile) {
    try {
      const created = await post<{ conversation: Conversation }>("/api/conversations", {
        kind: "bot",
        profiles: [profile.name],
        title: `Chat with ${profile.name}`,
      });
      await refresh();
      setActiveId(created.conversation.id);
      onStart();
    } catch (problem) {
      setError((problem as Error).message);
    }
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <div className="eyebrow">SPECIALISTS</div>
          <h1>Your bots</h1>
          <p>Start a focused conversation with any Open Agent Profile.</p>
        </div>
      </div>
      {profiles.length ? (
        <div className="bot-grid">
          {profiles.map((profile) => (
            <article className="bot-card" key={profile.name}>
              <div className="mini-mark">{initials(profile.name)}</div>
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
