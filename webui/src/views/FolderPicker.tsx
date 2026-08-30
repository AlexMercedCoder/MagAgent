import { useEffect, useState } from "react";
import { request } from "../api";

type Listing = {
  path: string;
  parent?: string;
  directories?: { name: string; path: string }[];
  roots?: { name: string; path: string }[];
};

export function FolderPicker({ initial, onChoose, onClose, setError }: {
  initial: string;
  onChoose: (path: string) => void;
  onClose: () => void;
  setError?: (message: string) => void;
}) {
  const [listing, setListing] = useState<Listing | null>(null);
  const [path, setPath] = useState(initial);
  const [busy, setBusy] = useState(false);

  async function open(target: string) {
    setBusy(true);
    try {
      const found = await request<Listing>(`/api/folders?path=${encodeURIComponent(target)}`);
      setListing(found);
      setPath(found.path);
    } catch (problem) {
      setError?.((problem as Error).message);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => { void open(initial); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  return <div className="modal-backdrop folder-picker-backdrop" role="dialog" aria-modal="true" aria-label="Choose project folder" onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <div className="modal folder-picker">
      <div className="dialog-head"><div><div className="eyebrow">LOCAL FOLDER</div><h2>Choose a project</h2></div><button className="icon-button" type="button" onClick={onClose}>×</button></div>
      <div className="folder-roots">{(listing?.roots || []).map((root) => <button className="ghost-button" type="button" key={root.path} onClick={() => void open(root.path)}>{root.name}</button>)}</div>
      <form className="folder-path" onSubmit={(event) => { event.preventDefault(); void open(path); }}><input aria-label="Folder path" value={path} onChange={(event) => setPath(event.target.value)} /><button className="ghost-button" disabled={busy} type="submit">Go</button></form>
      <div className="folder-list">
        {listing?.parent && <button type="button" onClick={() => void open(listing.parent!)}><span className="folder-icon">↰</span><span><b>Parent folder</b><small>{listing.parent}</small></span></button>}
        {(listing?.directories || []).map((directory) => <button type="button" key={directory.path} onClick={() => void open(directory.path)}><span className="folder-icon">▱</span><span><b>{directory.name}</b><small>{directory.path}</small></span></button>)}
        {!busy && listing && !(listing.directories || []).length && <p>This folder has no subfolders.</p>}
        {busy && <p>Opening folder…</p>}
      </div>
      <div className="dialog-actions"><button className="ghost-button" type="button" onClick={onClose}>Cancel</button><button className="primary-button" type="button" disabled={!listing} onClick={() => listing && onChoose(listing.path)}>Choose this folder</button></div>
    </div>
  </div>;
}
