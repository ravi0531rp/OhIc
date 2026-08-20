"use client";
/* eslint-disable jsx-a11y/media-has-caption */

import type { ComparisonRecord, VideoRecord } from "../lib/types";
import { mediaUrl } from "../lib/api";
import { ArrowLeftIcon, StopIcon } from "./Icons";

type Props = {
  comparison: ComparisonRecord;
  video: VideoRecord;
  onBack: () => void;
  onCancel: () => void;
};

export function MultiPreviewViewer({ comparison, video, onBack, onCancel }: Props) {
  const active = ["queued", "running"].includes(comparison.status);
  return (
    <main className="preview-lab-page">
      <header className="preview-lab-header">
        <button onClick={onBack}><ArrowLeftIcon size={16} /> Back to setup</button>
        <div><span className="eyebrow">Multi-preview comparison</span><h1>Preview Lab</h1><p>Same five-second moment · different quality recipes</p></div>
        {active && <button className="async-stop" onClick={onCancel}><StopIcon size={13} /> Stop lab</button>}
      </header>
      <div className="preview-lab-progress"><span>Overall progress</span><strong>{Math.round(comparison.progress)}%</strong><i><b style={{ width: `${comparison.progress}%` }} /></i></div>
      <section className="preview-lab-grid">
        <article><div className="preview-lab-video"><video controls playsInline preload="metadata" src={`${mediaUrl(video.playback_url)}#t=${Math.max(0, comparison.timestamp - 2.5)},${comparison.timestamp + 2.5}`} /></div><h2>Original source</h2><p>{video.metadata.resolution_label} · untreated reference</p></article>
        {comparison.items.map((item) => (
          <article key={item.id}>
            <div className="preview-lab-video">
              {item.output_url ? <video controls playsInline preload="metadata" src={mediaUrl(item.output_url)} /> : <div className="preview-lab-wait"><strong>{Math.round(item.progress)}%</strong><span>{item.status}</span></div>}
            </div>
            <h2>{item.label}</h2><p>{item.target_height}p · {item.preset} · {item.model_id.startsWith("realbasic") ? "Temporal" : "Frame"}</p>
            {item.error && <small>{item.error}</small>}
          </article>
        ))}
      </section>
    </main>
  );
}
