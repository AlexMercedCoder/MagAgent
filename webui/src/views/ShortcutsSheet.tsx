type Row = { describe: string; keys: string };

export function ShortcutsSheet({ rows, onClose }: { rows: Row[]; onClose: () => void }) {
  return (
    <div
      className="modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label="Keyboard shortcuts"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="modal shortcuts-sheet">
        <div className="dialog-head">
          <div>
            <div className="eyebrow">KEYBOARD</div>
            <h2>Shortcuts</h2>
          </div>
          <button className="icon-button" type="button" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <ul>
          {rows.map((row) => (
            <li key={`${row.describe}-${row.keys}`}>
              <span>{row.describe}</span>
              <kbd>{row.keys}</kbd>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
