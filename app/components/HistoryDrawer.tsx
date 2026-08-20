"use client";

import type { JobRecord } from "../lib/types";
import { FilmIcon, PauseIcon, PlayIcon, StopIcon, XIcon } from "./Icons";

type Props = {
  jobs: JobRecord[];
  open: boolean;
  onClose: () => void;
  onSelect: (job: JobRecord) => void;
  onCancel: (job: JobRecord) => void;
  onPause: (job: JobRecord) => void;
  onResume: (job: JobRecord) => void;
};

const ACTIVE = ["queued", "preparing", "processing", "encoding"];

function modelLabel(modelId: string) {
  return modelId.startsWith("realbasicvsr") ? "RealBasicVSR · Experimental" : "Real-ESRGAN";
}

export function HistoryDrawer({ jobs, open, onClose, onSelect, onCancel, onPause, onResume }: Props) {
  return (
    <>
      <button className={`drawer-scrim ${open ? "visible" : ""}`} aria-label="Close history" onClick={onClose} />
      <aside className={`history-drawer ${open ? "open" : ""}`} aria-hidden={!open}>
        <div className="drawer-heading">
          <div><span className="eyebrow">Saved sessions</span><h2>Recent enhancements</h2></div>
          <button className="icon-button" aria-label="Close history" onClick={onClose}><XIcon size={18} /></button>
        </div>
        <div className="history-list">
          {jobs.length === 0 ? (
            <div className="history-empty"><FilmIcon size={24} /><strong>No jobs yet</strong><span>Enhancement jobs will appear here.</span></div>
          ) : jobs.map((job) => {
            const active = ACTIVE.includes(job.status);
            const name = job.playlist_id ? "Playlist enhancement" : job.kind === "stream" ? "Watch-while-enhancing" : job.kind === "preview" ? "Preview enhancement" : job.trim_end || job.trim_start ? "Range enhancement" : "Full video enhancement";
            return (
              <div className="history-row" key={job.id}>
                <button className="history-main" aria-label={`Open ${name}`} onClick={() => onSelect(job)}>
                  <span className={`job-status ${job.status}`} />
                  <span><strong>{name}</strong><small>{modelLabel(job.model_id)} · {job.target_width} × {job.target_height} · {job.preset} · {active ? job.progress.stage : job.status}</small></span>
                  <span className="history-meta"><time>{new Date(job.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })}</time><b>{active ? "View live" : job.status === "paused" ? "Resume" : job.status === "complete" ? "View result" : "Open"}</b></span>
                </button>
                {active && <button className="history-pause" aria-label="Pause job" title="Pause job" onClick={() => onPause(job)}><PauseIcon size={13} /> Pause</button>}
                {job.status === "paused" && <button className="history-resume" aria-label="Resume job" title="Resume job" onClick={() => onResume(job)}><PlayIcon size={13} /> Resume</button>}
                {(active || job.status === "paused") && <button className="history-stop" aria-label="Stop job" title="Stop job" onClick={() => onCancel(job)}><StopIcon size={13} /> Stop</button>}
              </div>
            );
          })}
        </div>
        <p className="drawer-footnote">Open a session to restore its settings, live progress, or completed result.</p>
      </aside>
    </>
  );
}
