"use client";

import { useMemo, useState } from "react";
import type { StorageItem } from "../lib/types";
import { FilmIcon, TrashIcon, XIcon } from "./Icons";

type Props = {
  items: StorageItem[];
  open: boolean;
  busy: boolean;
  onClose: () => void;
  onCleanup: (ids: string[]) => void;
};

export function StorageDrawer({ items, open, busy, onClose, onCleanup }: Props) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const validSelected = useMemo(
    () => new Set([...selected].filter((id) => items.some((item) => item.id === id))),
    [items, selected],
  );
  const selectedItems = useMemo(() => items.filter((item) => validSelected.has(item.id)), [items, validSelected]);
  const total = items.reduce((sum, item) => sum + item.size, 0);
  const selectedBytes = selectedItems.reduce((sum, item) => sum + item.size, 0);

  const toggle = (item: StorageItem) => {
    if (item.active) return;
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(item.id)) next.delete(item.id);
      else next.add(item.id);
      return next;
    });
  };

  return (
    <>
      <button className={`drawer-scrim ${open ? "visible" : ""}`} aria-label="Close storage" onClick={onClose} />
      <aside className={`history-drawer storage-drawer ${open ? "open" : ""}`} aria-hidden={!open}>
        <div className="drawer-heading">
          <div><span className="eyebrow">Local files · {formatBytes(total)}</span><h2>Manage storage</h2></div>
          <button className="icon-button" aria-label="Close storage" onClick={onClose}><XIcon size={18} /></button>
        </div>
        <p className="storage-intro">Select downloaded sources, uploads, or completed results to remove from this Mac.</p>
        <div className="storage-list">
          {items.length === 0 ? (
            <div className="history-empty"><FilmIcon size={24} /><strong>No saved videos</strong><span>Imported videos and results will appear here.</span></div>
          ) : items.map((item) => (
            <label className={`${validSelected.has(item.id) ? "selected" : ""} ${item.active ? "disabled" : ""}`} key={item.id}>
              <input type="checkbox" checked={validSelected.has(item.id)} disabled={item.active} onChange={() => toggle(item)} />
              <span className="storage-check">✓</span>
              <span><strong>{item.name}</strong><small>{item.kind} · {item.detail}{item.active ? " · stop job first" : ""}</small></span>
              <time>{formatBytes(item.size)}</time>
            </label>
          ))}
        </div>
        <div className="storage-actions">
          <p>{validSelected.size ? `${validSelected.size} selected · ${formatBytes(selectedBytes)}` : "Choose files to clean up"}</p>
          <button
            disabled={!validSelected.size || busy}
            onClick={() => {
              if (window.confirm(`Permanently delete ${validSelected.size} selected item(s) from this Mac?`)) {
                onCleanup([...validSelected]);
              }
            }}
          ><TrashIcon size={15} /> {busy ? "Removing…" : "Delete selected"}</button>
          {selectedItems.some((item) => item.kind !== "output") && <small>Deleting a source also removes its linked results and history.</small>}
        </div>
      </aside>
    </>
  );
}

function formatBytes(value: number): string {
  if (!value) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  return `${(value / 1024 ** index).toFixed(index > 1 ? 1 : 0)} ${units[index]}`;
}
