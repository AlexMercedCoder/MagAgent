import { useEffect, useMemo, useState } from "react";
import { post, request } from "../api";
import type { WorkspaceFile } from "../types";

type Preview = { path: string; mime: string; text: boolean; content?: string; data_url?: string };
type GitState = { status?: string[]; branches?: string[]; worktrees?: Record<string, string>[] };

export function WorkspaceView({
  selected,
  setSelected,
  activeConversation,
  setError,
  notify,
}: {
  selected: string[];
  setSelected: (paths: string[]) => void;
  activeConversation: string | null;
  setError: (message: string) => void;
  notify: (message: string) => void;
}) {
  const [files, setFiles] = useState<WorkspaceFile[]>([]);
  const [query, setQuery] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [git, setGit] = useState<GitState>({});
  const [diff, setDiff] = useState("");
  const [command, setCommand] = useState("git status --short");
  const [terminal, setTerminal] = useState("");
  const [busy, setBusy] = useState(false);
  const [branch, setBranch] = useState("");
  const [worktreeDir, setWorktreeDir] = useState("");

  async function load() {
    try {
      const [fileData, gitData] = await Promise.all([
        request<{ files: WorkspaceFile[] }>(`/api/workspace/files?q=${encodeURIComponent(query)}`),
        request<GitState>("/api/workspace/git"),
      ]);
      setFiles(fileData.files || []);
      setGit(gitData);
    } catch (problem) {
      setError((problem as Error).message);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const artifacts = useMemo(() => files.filter((file) => file.artifact), [files]);

  async function open(path: string) {
    try {
      setPreview(await request<Preview>(`/api/workspace/file?path=${encodeURIComponent(path)}`));
    } catch (problem) {
      setError((problem as Error).message);
    }
  }

  async function showDiff(staged: boolean) {
    try {
      const result = await request<{ diff: string }>(`/api/workspace/diff?staged=${staged}`);
      setDiff(result.diff || "No changes in this view.");
    } catch (problem) {
      setError((problem as Error).message);
    }
  }

  async function upload(file: File) {
    if (file.size > 5 * 1024 * 1024) {
      setError("Uploads are limited to 5 MB.");
      return;
    }
    const data = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onerror = () => reject(reader.error);
      reader.onload = () => resolve(String(reader.result).split(",", 2)[1] || "");
      reader.readAsDataURL(file);
    });
    try {
      const result = await post<{ file: WorkspaceFile }>("/api/workspace/upload", {
        name: file.name,
        data,
        conversation_id: activeConversation || "shared",
      });
      setSelected([...new Set([...selected, result.file.path])].slice(0, 20));
      notify(`${file.name} attached`);
      await load();
    } catch (problem) {
      setError((problem as Error).message);
    }
  }

  async function runCommand() {
    setBusy(true);
    try {
      const result = await post<{ stdout?: string; stderr?: string; returncode?: number }>(
        "/api/workspace/terminal",
        { command },
      );
      setTerminal(`${result.stdout || ""}${result.stderr || ""}` || `Exited ${result.returncode}`);
    } catch (problem) {
      setError((problem as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function gitAction(action: string, path: string) {
    if (action === "discard" && !window.confirm(`Discard uncommitted changes in ${path}? This cannot be undone.`)) return;
    try {
      await post("/api/workspace/git", { action, path });
      notify(`${action} completed for ${path}`);
      await load();
    } catch (problem) { setError((problem as Error).message); }
  }

  async function createWorktree() {
    try {
      await post("/api/workspace/worktrees", { action: "create", branch, directory: worktreeDir, create_branch: true });
      notify(`Worktree created for ${branch}`);
      setBranch(""); setWorktreeDir("");
      await load();
    } catch (problem) { setError((problem as Error).message); }
  }

  async function removeWorktree(directory: string) {
    if (!window.confirm(`Remove the Git worktree at ${directory}? Uncommitted worktrees are refused by Git.`)) return;
    try {
      await post("/api/workspace/worktrees", { action: "remove", directory });
      notify("Worktree removed");
      await load();
    } catch (problem) { setError((problem as Error).message); }
  }

  function statusPath(line: string): string {
    const raw = line.slice(3).trim();
    return raw.includes(" -> ") ? raw.split(" -> ").pop() || raw : raw;
  }

  return (
    <section className="view active page-view">
      <div className="page-head">
        <div>
          <div className="eyebrow">PROJECT CONTEXT</div>
          <h1>Workspace</h1>
          <p>Inspect files and artifacts, attach context, review Git, and run explicit local commands.</p>
        </div>
        <label className="upload-button">
          Attach file
          <input type="file" onChange={(event) => event.target.files?.[0] && void upload(event.target.files[0])} />
        </label>
      </div>

      <div className="workspace-tools">
        <div className="detail-card workspace-browser">
          <div className="toolbar-row">
            <input aria-label="Search workspace files" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Filter files" />
            <button className="secondary-button" type="button" onClick={() => void load()}>Search</button>
          </div>
          <p className="selection-note">{selected.length}/20 files attached to the next message</p>
          <div className="file-list">
            {files.map((file) => (
              <div className="file-row" key={file.path}>
                <input
                  type="checkbox"
                  aria-label={`Attach ${file.path}`}
                  checked={selected.includes(file.path)}
                  onChange={() => setSelected(selected.includes(file.path) ? selected.filter((item) => item !== file.path) : [...selected, file.path].slice(0, 20))}
                />
                <button type="button" onClick={() => void open(file.path)}>{file.path}</button>
                <small>{Math.ceil(file.size / 1024)} KB</small>
              </div>
            ))}
          </div>
        </div>
        <article className="detail-card file-preview">
          <h2>{preview?.path || "Preview"}</h2>
          {!preview && <p>Select a file to inspect it without leaving MagAgent.</p>}
          {preview?.text && <pre>{preview.content}</pre>}
          {preview?.data_url && preview.mime.startsWith("image/") && <img src={preview.data_url} alt={preview.path} />}
          {preview?.data_url && !preview.mime.startsWith("image/") && <p>Binary preview ready ({preview.mime}).</p>}
        </article>
      </div>

      <div className="ops-grid">
        <article className="ops-card">
          <h3>Git status</h3>
          <div className="git-file-list">
            {(git.status || []).filter((line) => !line.startsWith("##")).map((line) => {
              const path = statusPath(line);
              return <div className="git-file-row" key={line}><code>{line}</code><div><button type="button" onClick={() => void gitAction("stage", path)}>Stage</button><button type="button" onClick={() => void gitAction("unstage", path)}>Unstage</button><button className="danger-link" type="button" onClick={() => void gitAction("discard", path)}>Discard</button></div></div>;
            })}
          </div>
          {!(git.status || []).filter((line) => !line.startsWith("##")).length && <p>Clean or not a Git repository.</p>}
          <div className="toolbar-row">
            <button className="secondary-button" type="button" onClick={() => void showDiff(false)}>Working diff</button>
            <button className="secondary-button" type="button" onClick={() => void showDiff(true)}>Staged diff</button>
          </div>
        </article>
        <article className="ops-card">
          <h3>Branches & worktrees</h3>
          <pre>{(git.branches || []).join("\n")}</pre>
          {(git.worktrees || []).map((item) => <div className="git-file-row" key={item.worktree}><code>{item.worktree} {item.branch || ""}</code>{item.worktree && item.current !== "true" && <div><button className="danger-link" type="button" onClick={() => void removeWorktree(item.worktree)}>Remove</button></div>}</div>)}
          <div className="worktree-form">
            <input aria-label="New worktree branch" value={branch} onChange={(event) => setBranch(event.target.value)} placeholder="feature/name" />
            <input aria-label="New worktree directory" value={worktreeDir} onChange={(event) => setWorktreeDir(event.target.value)} placeholder="../project-feature" />
            <button className="secondary-button" type="button" disabled={!branch || !worktreeDir} onClick={() => void createWorktree()}>Create branch + worktree</button>
          </div>
        </article>
        <article className="ops-card">
          <h3>Artifacts</h3>
          <p>{artifacts.length} previewable project files discovered.</p>
          <div className="artifact-links">{artifacts.slice(0, 12).map((item) => <button key={item.path} type="button" onClick={() => void open(item.path)}>{item.name}</button>)}</div>
        </article>
      </div>
      {diff && <pre className="diff-view">{diff}</pre>}
      <article className="detail-card terminal-card">
        <h2>Command console</h2>
        <p>Commands run as an argument list in the selected workspace, with no shell expansion and a 60-second limit.</p>
        <div className="toolbar-row">
          <input aria-label="Workspace command" value={command} onChange={(event) => setCommand(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void runCommand(); }} />
          <button className="primary-button" type="button" disabled={busy} onClick={() => void runCommand()}>{busy ? "Running…" : "Run"}</button>
        </div>
        {terminal && <pre>{terminal}</pre>}
      </article>
    </section>
  );
}
