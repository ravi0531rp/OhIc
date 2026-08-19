"use client";

import type { JobRecord } from "../lib/types";
import { SparkIcon, XIcon } from "./Icons";

type Props = { job: JobRecord; onCancel: () => void };

function timeLabel(seconds?: number) {
  if (seconds == null || !Number.isFinite(seconds)) return "Calculating…";
  if (seconds < 60) return `${Math.max(1, Math.round(seconds))} sec`;
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.ceil((seconds % 3600) / 60);
  return hours ? `${hours} hr ${minutes} min` : `${minutes} min`;
}

export function ProgressPanel({ job, onCancel }: Props) {
  const { progress } = job;
  const active = !["complete", "failed", "cancelled"].includes(job.status);
  return (
    <section className="progress-panel" aria-live="polite">
      <div className="progress-orb"><SparkIcon size={21} /></div>
      <div className="progress-main">
        <div className="progress-heading">
          <div>
            <span className="eyebrow">{job.kind === "stream" ? "Watch while enhancing" : job.kind === "preview" ? "5-second preview" : job.trim_end || job.trim_start ? "Selected range" : "Full enhancement"}</span>
            <h2>{progress.stage}</h2>
          </div>
          <strong>{Math.round(progress.percent)}%</strong>
        </div>
        <div className="progress-track"><span style={{ width: `${progress.percent}%` }} /></div>
        <div className="progress-stats">
          <span>{progress.frames_total ? `${progress.frames_done.toLocaleString()} / ${progress.frames_total.toLocaleString()} frames` : progress.detail ?? "Preparing pipeline"}</span>
          <span>{progress.processing_fps ? `${progress.processing_fps.toFixed(2)} FPS` : "Local AI"}</span>
          <span>{progress.eta_seconds ? `${timeLabel(progress.eta_seconds)} remaining` : timeLabel(progress.elapsed_seconds)}</span>
        </div>
      </div>
      {active && <button className="icon-button cancel" aria-label="Cancel enhancement" onClick={onCancel}><XIcon size={18} /></button>}
    </section>
  );
}
