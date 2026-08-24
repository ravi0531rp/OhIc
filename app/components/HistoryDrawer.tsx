"use client";

import type { HistoryEntry } from "../lib/types";
import { FilmIcon, PauseIcon, PlayIcon, StopIcon, XIcon } from "./Icons";

type Props = {
  entries: HistoryEntry[];
  open: boolean;
  onClose: () => void;
  onSelect: (entry: HistoryEntry) => void;
  onCancel: (entry: HistoryEntry) => void;
  onPause: (entry: HistoryEntry) => void;
  onResume: (entry: HistoryEntry) => void;
};

export function HistoryDrawer({ entries, open, onClose, onSelect, onCancel, onPause, onResume }: Props) {
  return (
    <>
      <button className={`drawer-scrim ${open ? "visible" : ""}`} aria-label="Close history" onClick={onClose} />
      <aside className={`history-drawer ${open ? "open" : ""}`} aria-hidden={!open}>
        <div className="drawer-heading">
          <div><span className="eyebrow">Saved sessions</span><h2>Recent activity</h2></div>
          <button className="icon-button" aria-label="Close history" onClick={onClose}><XIcon size={18} /></button>
        </div>
        <div className="history-list">
          {entries.length === 0 ? (
            <div className="history-empty"><FilmIcon size={24} /><strong>No activity yet</strong><span>Enhancements, camera captures, and Pro analyses will appear here.</span></div>
          ) : entries.map((entry) => {
            const active = entry.can_cancel && entry.status !== "paused";
            const action = active ? "View live" : entry.status === "paused" ? "Resume" : entry.kind === "pro" ? "Open Pro" : entry.kind === "camera" ? "Open capture" : entry.status === "complete" ? "View result" : "Open";
            return (
              <div className={`history-row history-${entry.kind}`} key={entry.id}>
                <button className="history-main" aria-label={`Open ${entry.title}`} onClick={() => onSelect(entry)}>
                  <span className={`job-status ${entry.status}`} />
                  <span><strong>{entry.title}</strong><small>{entry.detail} · {active ? entry.stage : entry.status}</small></span>
                  <span className="history-meta"><time>{new Date(entry.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })}</time><b>{action}</b></span>
                </button>
                {entry.can_pause && <button className="history-pause" aria-label="Pause enhancement" title="Pause enhancement" onClick={() => onPause(entry)}><PauseIcon size={13} /> Pause</button>}
                {entry.status === "paused" && <button className="history-resume" aria-label="Resume enhancement" title="Resume enhancement" onClick={() => onResume(entry)}><PlayIcon size={13} /> Resume</button>}
                {entry.can_cancel && <button className="history-stop" aria-label={`Stop ${entry.kind}`} title={`Stop ${entry.kind}`} onClick={() => onCancel(entry)}><StopIcon size={13} /> Stop</button>}
              </div>
            );
          })}
        </div>
        <p className="drawer-footnote">Open an activity to return to its enhancement, captured video, or Pro workspace.</p>
      </aside>
    </>
  );
}
