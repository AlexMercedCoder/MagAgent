import { useEffect, useState } from "react";
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
  onDelete,
  onProjectChange,
  open,
  setOpen,
}: {
  conversations: Conversation[];
  activeId: string | null;
  setActiveId: (id: string) => void;
  profiles: Profile[];
  boot: Bootstrap | null;
  onCreate: (kind: "chat" | "bot" | "group", profileNames?: string[], project?: string, coordinator?: string) => void;
  onDelete: (conversation: Conversation) => void;
  onProjectChange: (conversation: Conversation, project: string) => void;
  open: boolean;
  setOpen: (open: boolean) => void;
}) {
  const [search, setSearch] = useState("");
  const [menu, setMenu] = useState(false);
  const [creating, setCreating] = useState(false);
  const [kind, setKind] = useState<"chat" | "bot" | "group">("chat");
  const [project, setProject] = useState(boot?.project || "");
  const [chosen, setChosen] = useState<string[]>([]);
  const [coordinator, setCoordinator] = useState("");

  useEffect(() => {
    const openDialog = () => { setKind("chat"); setCreating(true); };
    window.addEventListener("magent:new-conversation", openDialog);
    return () => window.removeEventListener("magent:new-conversation", openDialog);
  }, []);
  useEffect(() => {
    if (!project && boot?.project) setProject(boot.project);
  }, [boot?.project, project]);

  const shown = search
    ? conversations.filter((item) => item.title.toLowerCase().includes(search.toLowerCase()))
    : conversations;

  return (
    <aside className={`sidebar ${open ? "open" : ""}`}>
      <div className="sidebar-head">
        <div>
          <div className="eyebrow">LOCAL WORKSPACE</div>
          <p className="brand-name">MagAgent</p>
        </div>
        <button className="icon-button" onClick={() => setOpen(false)} aria-label="Close sidebar">
          ×
        </button>
      </div>

      <div className="new-actions">
        <button className="primary-button" type="button" onClick={() => { setKind("chat"); setCreating(true); }}>
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
                setKind("bot"); setChosen([]); setCreating(true);
              }}
            >
              Bot conversation
            </button>
            <button
              type="button"
              disabled={profiles.length < 2}
              onClick={() => {
                setMenu(false);
                setKind("group"); setChosen([]); setCreating(true);
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
          <div className={`conversation-item ${activeId === item.id ? "active" : ""}`} key={item.id}>
          <button
            type="button"
            className="conversation-select"
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
          <div className="conversation-row-actions">
            <button className="conversation-project" type="button" title="Change project folder" aria-label={`Change project for ${item.title}`}
              onClick={() => { const next = window.prompt("Project folder for this conversation", item.project); if (next && next !== item.project) onProjectChange(item, next); }}>▱</button>
            <button className="conversation-delete" type="button" aria-label={`Delete ${item.title}`}
              onClick={() => { if (window.confirm(`Delete “${item.title}” and its transcript?`)) onDelete(item); }}>×</button>
          </div>
          </div>
        ))}
        {!shown.length && (
          <div className="empty-small">
            <b>{search ? "No matches" : "No conversations yet"}</b>
            <p>{search ? "Try a different search." : "Start a chat above."}</p>
          </div>
        )}
      </div>
      {creating && (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="New conversation"
          onClick={(event) => { if (event.target === event.currentTarget) setCreating(false); }}>
          <form className="modal" onSubmit={(event) => {
            event.preventDefault();
            const selected = kind === "chat" ? [] : chosen;
            onCreate(kind, selected, project || boot?.project || ".", kind === "group" ? (coordinator || selected[0] || "") : "");
            setCreating(false);
          }}>
            <div className="dialog-head"><div><div className="eyebrow">NEW CONVERSATION</div><h2>Choose context first</h2></div><button className="icon-button" type="button" onClick={() => setCreating(false)}>×</button></div>
            <label htmlFor="conversationKind">Type</label>
            <select id="conversationKind" value={kind} onChange={(event) => { setKind(event.target.value as typeof kind); setChosen([]); setCoordinator(""); }}>
              <option value="chat">Standard chat</option><option value="bot">Bot conversation</option><option value="group">Group conversation</option>
            </select>
            <label htmlFor="conversationProject">Project folder</label>
            <input id="conversationProject" required value={project} list="recentProjects" onChange={(event) => setProject(event.target.value)} />
            <datalist id="recentProjects">{Array.from(new Set([boot?.project, ...conversations.map((item) => item.project)].filter(Boolean))).map((item) => <option key={item} value={item} />)}</datalist>
            {kind !== "chat" && <fieldset className="profile-picker"><legend>Participants</legend>{profiles.map((profile) => <label className="profile-choice" key={profile.name}><input type={kind === "bot" ? "radio" : "checkbox"} name="participants" checked={chosen.includes(profile.name)} onChange={(event) => setChosen((current) => kind === "bot" ? (event.target.checked ? [profile.name] : []) : event.target.checked ? [...current, profile.name] : current.filter((name) => name !== profile.name))} />@{profile.name}</label>)}</fieldset>}
            {kind === "group" && <><label htmlFor="conversationCoordinator">Coordinator</label><select id="conversationCoordinator" value={coordinator} onChange={(event) => setCoordinator(event.target.value)}><option value="">Choose automatically</option>{chosen.map((name) => <option key={name} value={name}>@{name}</option>)}</select></>}
            <p className="context-note">The project and participants are pinned before the first message. You can create chats in any existing local folder.</p>
            <button className="primary-button" type="submit" disabled={(kind === "bot" && chosen.length !== 1) || (kind === "group" && (chosen.length < 2 || chosen.length > 5))}>Create conversation</button>
          </form>
        </div>
      )}

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
