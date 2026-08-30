import type { Bootstrap, Conversation } from "../types";

function initials(name = "M"): string {
  return name.split(/\s+|[-_]/).map((p) => p[0]).join("").slice(0, 2).toUpperCase() || "M";
}

/** Right-hand detail column; a direct child of the four-column app shell. */
export function ContextPanel({
  active,
  boot,
  onPermissionChange,
  onClose,
}: {
  active: Conversation | null;
  boot: Bootstrap | null;
  onPermissionChange: (conversation: Conversation, permissionMode: string) => void;
  onClose: () => void;
}) {
  const kind =
    active?.kind === "group" ? "Group chat" : active?.kind === "bot" ? "Bot chat" : "Standard chat";

  return (
    <aside className="context-panel">
      <div className="context-head">
        <div>
          <div className="eyebrow">CONTEXT</div>
          <h2>Conversation details</h2>
        </div>
        <button className="icon-button" type="button" onClick={onClose} aria-label="Close details">
          ×
        </button>
      </div>
      <div className="context-identity">
        <div className="context-avatar">{initials(active?.profiles?.[0] || "M")}</div>
        <strong>{active?.profiles?.[0] || "MagAgent"}</strong>
        <span>{kind}</span>
      </div>
      <div className="context-field">
        <span className="eyebrow">Project</span>
        <div className="context-value">{active?.project || boot?.project || "—"}</div>
      </div>
      <div className="context-field">
        <span className="eyebrow">Participants</span>
        <div className="context-value">{active?.profiles?.join(", ") || "—"}</div>
      </div>
      <div className="context-field">
        <span className="eyebrow">Safety</span>
        <label className="context-permission">Permission mode<select disabled={!active} value={active?.permission_mode || boot?.permission_mode || "balanced"} onChange={(event) => active && onPermissionChange(active, event.target.value)}><option value="paranoid">Paranoid</option><option value="balanced">Balanced</option><option value="silent">Silent</option><option value="yolo">Yolo</option></select></label>
        <p className="context-note">
          Profiles can narrow authority, but never widen the configured ceiling.
        </p>
      </div>
    </aside>
  );
}
