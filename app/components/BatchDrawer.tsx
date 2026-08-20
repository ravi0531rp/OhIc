"use client";

import type { BatchRecord } from "../lib/types";
import { PauseIcon, PlayIcon, StopIcon, XIcon } from "./Icons";

type Props = {
  batches: BatchRecord[];
  open: boolean;
  onClose: () => void;
  onPause: (batch: BatchRecord) => void;
  onResume: (batch: BatchRecord) => void;
  onCancel: (batch: BatchRecord) => void;
  onOpenResult: (jobId: string) => void;
};

export function BatchDrawer({
  batches,
  open,
  onClose,
  onPause,
  onResume,
  onCancel,
  onOpenResult,
}: Props) {
  return (
    <>
      <button className={`drawer-scrim ${open ? "visible" : ""}`} aria-label="Close batch queue" onClick={onClose} />
      <aside className={`history-drawer batch-drawer ${open ? "open" : ""}`} aria-hidden={!open}>
        <div className="drawer-heading">
          <div><span className="eyebrow">Persistent local queue</span><h2>Batch enhancements</h2></div>
          <button className="icon-button" aria-label="Close batch queue" onClick={onClose}><XIcon size={18} /></button>
        </div>
        <div className="batch-list">
          {batches.length === 0 ? <p className="batch-empty">Choose multiple files on Upload to create a batch.</p> : batches.map((batch) => (
            <section className="batch-card" key={batch.id}>
              <div className="batch-card-head"><span><strong>{batch.name}</strong><small>{batch.status} · {Math.round(batch.progress)}%</small></span><div>{["queued", "running"].includes(batch.status) && <button aria-label="Pause batch" onClick={() => onPause(batch)}><PauseIcon size={12} /></button>}{batch.status === "paused" && <button aria-label="Resume batch" onClick={() => onResume(batch)}><PlayIcon size={12} /></button>}{["queued", "running", "paused"].includes(batch.status) && <button aria-label="Stop batch" onClick={() => onCancel(batch)}><StopIcon size={12} /></button>}</div></div>
              <div className="batch-track"><i style={{ width: `${batch.progress}%` }} /></div>
              <div className="batch-items">
                {batch.items.map((item) => (
                  <button disabled={item.status !== "complete" || !item.job_id} key={item.id} onClick={() => item.job_id && onOpenResult(item.job_id)}>
                    <span><strong>{item.name}</strong><small>{item.error ?? item.status}</small></span><b>{Math.round(item.progress)}%</b>
                  </button>
                ))}
              </div>
            </section>
          ))}
        </div>
        <p className="drawer-footnote">Queues and presets stay on this device across app restarts.</p>
      </aside>
    </>
  );
}
