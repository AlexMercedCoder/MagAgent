import { useCallback, useEffect, useMemo, useState } from "react";
import { captureLaunchToken, post, request } from "./api";
import { registerShortcuts, chord, type Shortcut } from "./shortcuts";
import {
  applyTheme,
  initTheme,
  nextTheme,
  storeTheme,
  themeGlyph,
  themeLabel,
  themeShort,
  type ThemeChoice,
} from "./theme";
import type { Bootstrap, Conversation, Profile, SettingField } from "./types";
import { FirstRun } from "./FirstRun";
import { ChatView } from "./views/ChatView";
import { Sidebar } from "./views/Sidebar";
import { ContextPanel } from "./views/ContextPanel";
import { BotsView } from "./views/BotsView";
import { GraphsView } from "./views/GraphsView";
import { ProfilesView } from "./views/ProfilesView";
import { MemoryView } from "./views/MemoryView";
import { SettingsView } from "./views/SettingsView";
import { OperationsView } from "./views/OperationsView";
import { ShortcutsSheet } from "./views/ShortcutsSheet";

export type View =
  | "chat"
  | "bots"
  | "graphs"
  | "profiles"
  | "memory"
  | "settings"
  | "operations";

const NAV: { id: View; glyph: string; label: string }[] = [
  { id: "chat", glyph: "✦", label: "Chats" },
  { id: "bots", glyph: "◉", label: "Bots" },
  { id: "graphs", glyph: "⌘", label: "Graphs" },
  { id: "profiles", glyph: "◇", label: "Profiles" },
  { id: "memory", glyph: "❖", label: "Memory" },
  { id: "settings", glyph: "⚙", label: "Settings" },
  { id: "operations", glyph: "⌁", label: "Ops" },
];

export default function App() {
  const [theme, setTheme] = useState<ThemeChoice>(initTheme);
  const [view, setView] = useState<View>("chat");
  const [boot, setBoot] = useState<Bootstrap | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [settings, setSettings] = useState<SettingField[]>([]);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const [showShortcuts, setShowShortcuts] = useState(false);
  const [ready, setReady] = useState(false);
  const [needsSetup, setNeedsSetup] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [contextOpen, setContextOpen] = useState(true);

  const notify = useCallback((message: string) => {
    setToast(message);
    window.setTimeout(() => setToast(""), 2600);
  }, []);

  const refreshConversations = useCallback(async () => {
    const data = await request<{ conversations: Conversation[] }>("/api/conversations");
    setConversations(data.conversations || []);
    setActiveId((current) => {
      const items = data.conversations || [];
      return current && items.some((item) => item.id === current) ? current : items[0]?.id || null;
    });
  }, []);

  /** One call returns conversations, profiles and the settings schema. */
  const load = useCallback(async () => {
    // `profiles` and `settings` arrive as envelopes, not bare lists.
    const data = await request<Bootstrap & {
      conversations?: Conversation[];
      profiles?: { profiles?: Profile[]; default_profile?: string };
      settings?: { fields?: SettingField[] };
    }>("/api/bootstrap");
    setBoot(data);
    setConversations(data.conversations || []);
    setProfiles(data.profiles?.profiles || []);
    setSettings(data.settings?.fields || []);
    setActiveId((current) => {
      const items = data.conversations || [];
      return current && items.some((item) => item.id === current) ? current : items[0]?.id || null;
    });
  }, []);

  useEffect(() => {
    captureLaunchToken();
    (async () => {
      try {
        // Ask whether a turn can actually run before showing a workspace whose
        // composer would fail on the first message.
        const readiness = await request<{ ready?: boolean }>(
          "/api/onboarding/readiness",
        ).catch(() => ({ ready: true }));
        // Only an explicit "no". Replacing the whole workspace with a setup
        // panel is a strong intervention, so an unreachable or unexpected
        // answer must not trigger it: the composer reports its own errors.
        if (readiness.ready === false) {
          setNeedsSetup(true);
          return;
        }
        await load();
      } catch (problem) {
        setError((problem as Error).message);
      } finally {
        setReady(true);
      }
    })();
  }, [load]);

  const shortcuts = useMemo<Shortcut[]>(
    () => [
      {
        key: "k",
        mod: true,
        describe: "Focus the message box",
        run: () => {
          setView("chat");
          window.setTimeout(
            () => document.querySelector<HTMLTextAreaElement>(".composer textarea")?.focus(),
            0,
          );
        },
      },
      {
        key: "f",
        mod: true,
        describe: "Search conversations",
        run: () => {
          setView("chat");
          window.setTimeout(
            () => document.querySelector<HTMLInputElement>("#conversationSearch")?.focus(),
            0,
          );
        },
      },
      {
        key: "n",
        mod: true,
        shift: true,
        describe: "New chat",
        run: () => {
          setView("chat");
          window.dispatchEvent(new CustomEvent("magent:new-conversation"));
        },
      },
      ...NAV.map((item, index) => ({
        key: String(index + 1),
        mod: true,
        describe: `Go to ${item.label}`,
        run: () => setView(item.id),
      })),
      { key: "/", describe: "Show keyboard shortcuts", run: () => setShowShortcuts(true) },
      {
        key: "Escape",
        describe: "Close a dialog or clear an error",
        run: () => {
          setShowShortcuts(false);
          setError("");
        },
      },
    ],
    [],
  );

  useEffect(() => registerShortcuts(shortcuts), [shortcuts]);

  const createConversation = useCallback(
    async (kind: "chat" | "bot" | "group", chosen: string[] = []) => {
      try {
        const created = await post<{ conversation: Conversation }>("/api/conversations", {
          kind,
          profiles: chosen,
          title: kind === "bot" && chosen[0] ? `Chat with ${chosen[0]}` : "New conversation",
        });
        await refreshConversations();
        setActiveId(created.conversation.id);
        setSidebarOpen(false);
        setView("chat");
      } catch (problem) {
        setError((problem as Error).message);
      }
    },
    [refreshConversations],
  );

  useEffect(() => {
    const open = () => void createConversation("chat");
    window.addEventListener("magent:new-conversation", open);
    return () => window.removeEventListener("magent:new-conversation", open);
  }, [createConversation]);

  const active = conversations.find((item) => item.id === activeId) || null;

  if (!ready) {
    return (
      <div className="splash">
        <div className="brand-mark">M</div>
        <p>Opening the workspace…</p>
      </div>
    );
  }

  // A machine with no provider has no working composer; saying so beats
  // presenting one whose first message is guaranteed to fail.
  if (needsSetup) {
    return (
      <FirstRun
        setError={setError}
        onReady={() => {
          setNeedsSetup(false);
          void load();
        }}
      />
    );
  }

  return (
    <div className="app-shell">
      <aside className="rail" aria-label="Primary navigation">
        <div className="brand-mark">M</div>
        <nav>
          {NAV.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`rail-button ${view === item.id ? "active" : ""}`}
              data-view={item.id}
              title={item.label}
              aria-current={view === item.id ? "page" : undefined}
              onClick={() => setView(item.id)}
            >
              {item.glyph}
              <span>{item.label}</span>
            </button>
          ))}
        </nav>
        <button
          type="button"
          className="rail-button theme-toggle"
          onClick={() => {
            const choice = nextTheme(theme);
            setTheme(choice);
            applyTheme(choice);
            storeTheme(choice);
          }}
          aria-label={`Theme: ${themeLabel[theme]}. Activate to change.`}
          title={`Theme: ${themeLabel[theme]}`}
        >
          <span aria-hidden="true">{themeGlyph[theme]}</span>
          <i>{themeShort[theme]}</i>
        </button>
        <div className="connection-dot" title="Local connection" />
      </aside>

      <Sidebar
        conversations={conversations}
        activeId={activeId}
        setActiveId={setActiveId}
        profiles={profiles}
        boot={boot}
        onCreate={createConversation}
        open={sidebarOpen}
        setOpen={setSidebarOpen}
      />

      <main className="workspace">
        {error && (
          <div className="error-banner" role="alert">
            {error}
            <button type="button" onClick={() => setError("")} aria-label="Dismiss">
              ×
            </button>
          </div>
        )}
        <div className="workspace-head">
          <button
            className="icon-button sidebar-open"
            type="button"
            onClick={() => setSidebarOpen(true)}
            aria-label="Show conversations"
          >
            ☰
          </button>
          <div className="workspace-title">
            {/* The chat view had no page heading at all: with a conversation
                open the only heading on the page was the context panel's, so
                heading navigation skipped straight past the transcript. */}
            {view === "chat" ? <h1>{active?.title || "New conversation"}</h1> : <b />}
          </div>
          <button
            className="icon-button"
            type="button"
            onClick={() => setContextOpen((open) => !open)}
            aria-label="Toggle conversation details"
            aria-expanded={contextOpen}
          >
            ☷
          </button>
        </div>

        {view === "chat" && (
          <ChatView active={active} refresh={refreshConversations} setError={setError} notify={notify} />
        )}
        {view === "bots" && (
          <BotsView profiles={profiles} setError={setError} onStart={() => setView("chat")}
                    refresh={refreshConversations} setActiveId={setActiveId} />
        )}
        {view === "graphs" && <GraphsView profiles={profiles} setError={setError} notify={notify} />}
        {view === "profiles" && <ProfilesView profiles={profiles} refresh={load} setError={setError} notify={notify} />}
        {view === "memory" && <MemoryView setError={setError} />}
        {view === "settings" && <SettingsView fields={settings} refresh={load} setError={setError} notify={notify} />}
        {view === "operations" && <OperationsView setError={setError} />}
      </main>

      {contextOpen && (
        <ContextPanel active={active} boot={boot} onClose={() => setContextOpen(false)} />
      )}

      {showShortcuts && (
        <ShortcutsSheet
          rows={[
            ...shortcuts.map((item) => ({ describe: item.describe, keys: chord(item) })),
            { describe: "Send the message", keys: "Enter" },
            { describe: "Newline in the message box", keys: "Shift+Enter" },
          ]}
          onClose={() => setShowShortcuts(false)}
        />
      )}

      {toast && (
        <div className="toast" role="status">
          {toast}
        </div>
      )}
    </div>
  );
}
