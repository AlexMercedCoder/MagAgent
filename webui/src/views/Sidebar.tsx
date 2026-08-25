import { useState } from "react";
import type { Bootstrap, Conversation, Profile } from "../types";

/**
 * Conversation rail. A direct child of `.app-shell`, which is a four-column
 * grid: rail, sidebar, workspace, context panel.
 */
export function Sidebar({
  conversations,
  activeId,
  setActiveId,
  profiles,
  boot,
  onCreate,
  open,
  setOpen,
}: {
  conversations: Conversation[];
  activeId: string | null;
  setActiveId: (id: string) => void;
  profiles: Profile[];
  boot: Bootstrap | null;
  onCreate: (kind: "chat" | "bot" | "group", profileNames?: string[]) => void;
  open: boolean;
  setOpen: (open: boolean) => void;
}) {
  const [search, setSearch] = useState("");
  const [menu, setMenu] = useState(false);

  const shown = search
    ? conversations.filter((item) => item.title.toLowerCase().includes(search.toLowerCase()))
    : conversations;

  return (
    <aside className={`sidebar ${open ? "open" : ""}`}>
      <div className="sidebar-head">
        <div>
          <div className="eyebrow">LOCAL WORKSPACE</div>
          <h1>MagAgent</h1>
        </div>
        <button className="icon-button" onClick={() => setOpen(false)} aria-label="Close sidebar">
          ×
        </button>
      </div>

      <div className="new-actions">
        <button className="primary-button" type="button" onClick={() => onCreate("chat")}>
          <span>＋</span> New chat
        </button>
        <button
          className="split-button"
          type="button"
          aria-label="More new conversation options"
          aria-expanded={menu}
          onClick={() => setMenu((value) => !value)}
        >
          ⌄
        </button>
        {menu && (
          <div className="new-menu">
            <button
              type="button"
              disabled={!profiles.length}
              onClick={() => {
                setMenu(false);
                onCreate("bot", profiles[0] ? [profiles[0].name] : []);
              }}
            >
              Bot conversation
            </button>
            <button
              type="button"
              disabled={profiles.length < 2}
              onClick={() => {
                setMenu(false);
                onCreate("group", profiles.slice(0, 2).map((item) => item.name));
              }}
            >
              Group conversation
            </button>
          </div>
        )}
      </div>

      <label className="search">
        <span aria-hidden="true">⌕</span>
        <input
          id="conversationSearch"
          placeholder="Search conversations"
          aria-label="Search conversations"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      </label>

      <div className="sidebar-section-label">
        <span>CONVERSATIONS</span>
        <span>{shown.length}</span>
      </div>

      <div className="conversation-list">
        {shown.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`conversation-item ${activeId === item.id ? "active" : ""}`}
            onClick={() => {
              setActiveId(item.id);
              setOpen(false);
            }}
          >
            <div className="mini-avatar">{(item.profiles?.[0] || "M").slice(0, 1).toUpperCase()}</div>
            <div>
              <b>{item.title}</b>
              <small>{item.profiles?.join(", ") || "MagAgent"}</small>
            </div>
          </button>
        ))}
        {!shown.length && (
          <div className="empty-small">
            <b>{search ? "No matches" : "No conversations yet"}</b>
            <p>{search ? "Try a different search." : "Start a chat above."}</p>
          </div>
        )}
      </div>

      <div className="project-card">
        <div className="project-icon">⌘</div>
        <div>
          <strong>{boot?.project ? boot.project.split("/").pop() : "Workspace"}</strong>
          <span>{boot?.project || "Loading…"}</span>
        </div>
      </div>
    </aside>
  );
}
