"use client";
/* Source video captions are not extracted into browser sidecar tracks in this release. */
/* eslint-disable jsx-a11y/media-has-caption */

import { useEffect, useMemo, useRef, useState } from "react";
import type { JobKind, JobRecord, QualityPreset, ResolutionTarget, VideoRecord } from "../lib/types";
import { ChevronIcon, PlayIcon, ShieldIcon, SparkIcon } from "./Icons";
import { mediaUrl } from "../lib/api";

type Props = {
  video: VideoRecord;
  initialJob?: JobRecord | null;
  busy: boolean;
  onRun: (
    kind: JobKind,
    target: ResolutionTarget,
    preset: QualityPreset,
    timestamp: number,
    trimStart: number,
    trimEnd?: number,
  ) => void;
};

const presets: { id: QualityPreset; title: string; description: string }[] = [
  { id: "fast", title: "Fast", description: "Quick tests and long videos" },
  { id: "balanced", title: "Balanced", description: "Best detail-to-time ratio" },
  { id: "maximum", title: "Maximum", description: "Slowest, finest tile pass" },
];

function formatTime(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  const rest = Math.floor(seconds % 60);
  return `${minutes}:${String(rest).padStart(2, "0")}`;
}

function formatBytes(bytes: number) {
  if (bytes > 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
}

export function EnhancementWorkspace({ video, initialJob, busy, onRun }: Props) {
  const [selected, setSelected] = useState(
    video.targets.find(
      (target) =>
        target.width === initialJob?.target_width && target.height === initialJob?.target_height,
    ) ?? video.targets.find((target) => target.recommended) ?? video.targets[0],
  );
  const [preset, setPreset] = useState<QualityPreset>(initialJob?.preset ?? "balanced");
  const [timestamp, setTimestamp] = useState(
    initialJob?.preview_timestamp ?? Math.min(video.metadata.duration / 2, 30),
  );
  const [customRange, setCustomRange] = useState(
    Boolean(initialJob && (initialJob.trim_start > 0 || initialJob.trim_end != null)),
  );
  const [trimStart, setTrimStart] = useState(initialJob?.trim_start ?? 0);
  const [trimEnd, setTrimEnd] = useState(initialJob?.trim_end ?? video.metadata.duration);
  const playerRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    const player = playerRef.current;
    if (player && Number.isFinite(timestamp)) player.currentTime = timestamp;
  }, [timestamp]);

  const workload = useMemo(() => {
    const pixels = selected.width * selected.height;
    const duration = customRange ? trimEnd - trimStart : video.metadata.duration;
    const frames = Math.max(1, Math.round(duration * video.metadata.fps));
    const level = pixels * frames < 1.5e10 ? "Moderate" : pixels * frames < 8e10 ? "High" : "Intensive";
    return { frames, level };
  }, [customRange, selected, trimEnd, trimStart, video]);

  const setBoundaryFromPlayer = (boundary: "start" | "end") => {
    const value = Math.max(0, Math.min(playerRef.current?.currentTime ?? timestamp, video.metadata.duration));
    if (boundary === "start") setTrimStart(Math.min(value, trimEnd - 0.1));
    else setTrimEnd(Math.max(value, trimStart + 0.1));
  };

  return (
    <main className="workspace-grid">
      <section className="video-stage-column">
        <div className="video-stage">
          <video ref={playerRef} controls playsInline src={mediaUrl(video.playback_url)} />
          <div className="stage-gradient" />
          <div className="stage-meta">
            <span>{video.metadata.resolution_label}</span>
            <span>{video.metadata.fps.toFixed(video.metadata.fps % 1 ? 2 : 0)} FPS</span>
            <span>{video.metadata.video_codec}</span>
          </div>
        </div>

        <div className="source-summary">
          <div className="source-title">
            <span className="eyebrow">Source video</span>
            <h2>{video.title ?? video.original_name}</h2>
          </div>
          <div className="summary-metrics">
            <div><span>Resolution</span><strong>{video.metadata.width} × {video.metadata.height}</strong></div>
            <div><span>Duration</span><strong>{formatTime(video.metadata.duration)}</strong></div>
            <div><span>Size</span><strong>{formatBytes(video.metadata.file_size)}</strong></div>
            <div><span>Range</span><strong>{video.metadata.dynamic_range}</strong></div>
          </div>
        </div>

        <div className="preview-section">
          <div>
            <span className="eyebrow">Preview section</span>
            <h3>Choose the moment worth checking.</h3>
            <p>OhIc will process five seconds centered around this point.</p>
          </div>
          <strong className="timecode">{formatTime(timestamp)}</strong>
          <input
            aria-label="Preview timestamp"
            max={Math.max(0.1, video.metadata.duration)}
            min="0"
            step="0.1"
            type="range"
            disabled={busy}
            value={timestamp}
            onChange={(event) => setTimestamp(Number(event.target.value))}
          />
          <div className="timeline-labels"><span>0:00</span><span>{formatTime(video.metadata.duration)}</span></div>
        </div>

        <div className="range-section">
          <div className="range-heading">
            <div><span className="eyebrow">Saved output range</span><h3>{customRange ? `${formatTime(trimStart)} to ${formatTime(trimEnd)}` : "Full video"}</h3><p>{customRange ? `${formatTime(trimEnd - trimStart)} will be enhanced and saved.` : "The complete source will be enhanced by default."}</p></div>
            <div className="range-toggle" role="group" aria-label="Output range">
              <button disabled={busy} className={!customRange ? "active" : ""} onClick={() => setCustomRange(false)}>Full</button>
              <button disabled={busy} className={customRange ? "active" : ""} onClick={() => setCustomRange(true)}>Custom</button>
            </div>
          </div>
          {customRange && (
            <div className="range-controls">
              <label><span>Start <strong>{formatTime(trimStart)}</strong></span><input disabled={busy} aria-label="Enhancement start timestamp" type="range" min="0" max={Math.max(0, trimEnd - 0.1)} step="0.1" value={trimStart} onChange={(event) => setTrimStart(Number(event.target.value))} /><button disabled={busy} onClick={() => setBoundaryFromPlayer("start")}>Use playhead</button></label>
              <label><span>End <strong>{formatTime(trimEnd)}</strong></span><input disabled={busy} aria-label="Enhancement end timestamp" type="range" min={Math.min(video.metadata.duration, trimStart + 0.1)} max={video.metadata.duration} step="0.1" value={trimEnd} onChange={(event) => setTrimEnd(Number(event.target.value))} /><button disabled={busy} onClick={() => setBoundaryFromPlayer("end")}>Use playhead</button></label>
            </div>
          )}
        </div>
      </section>

      <aside className="controls-panel">
        <div className="control-heading">
          <span className="eyebrow">Enhancement setup</span>
          <h1>Bring the detail forward.</h1>
          <p>OhIc selected sensible targets for this {video.metadata.resolution_label} source.</p>
        </div>

        <section className="control-section">
          <div className="section-label"><span>01</span><div><strong>Enhance to</strong><small>Aspect ratio stays {video.metadata.aspect_ratio}</small></div></div>
          <div className="resolution-options">
            {video.targets.map((target) => (
              <button disabled={busy} key={`${target.width}x${target.height}`} className={selected === target ? "selected" : ""} onClick={() => setSelected(target)}>
                <span>{target.label}</span>
                <small>{target.width} × {target.height}</small>
                {target.recommended && <em>Recommended</em>}
              </button>
            ))}
          </div>
          {selected.note && <p className="recommendation"><SparkIcon size={15} /> {selected.note}</p>}
        </section>

        <section className="control-section">
          <div className="section-label"><span>02</span><div><strong>Quality mode</strong><small>Balanced is a strong starting point</small></div></div>
          <div className="preset-options">
            {presets.map((option) => (
              <button disabled={busy} key={option.id} className={preset === option.id ? "selected" : ""} onClick={() => setPreset(option.id)}>
                <span className="radio-dot" />
                <span><strong>{option.title}</strong><small>{option.description}</small></span>
              </button>
            ))}
          </div>
        </section>

        <details className="advanced-settings">
          <summary>Advanced details <ChevronIcon size={16} /></summary>
          <div className="advanced-grid">
            <span>AI model<strong>Real-ESRGAN ×2</strong></span>
            <span>Final resize<strong>Lanczos</strong></span>
            <span>Output<strong>H.264 · MP4</strong></span>
            <span>Workload<strong>{workload.level}</strong></span>
          </div>
          <p>AI enhancement creates plausible detail; it should not be used as forensic evidence.</p>
        </details>

        <div className="action-stack">
          <button className="primary-action" disabled={busy} onClick={() => onRun("preview", selected, preset, timestamp, 0)}>
            <PlayIcon size={18} fill="currentColor" /> {busy ? "Preparing…" : "Preview enhancement"}
            <span>5 sec</span>
          </button>
          <button className="secondary-action" disabled={busy} onClick={() => onRun("full", selected, preset, timestamp, customRange ? trimStart : 0, customRange ? trimEnd : undefined)}>
            {customRange ? "Enhance selected range" : "Enhance full video"} <small>{workload.frames.toLocaleString()} frames</small>
          </button>
          <button className="stream-action" disabled={busy} onClick={() => onRun("stream", selected, preset, timestamp, customRange ? trimStart : 0, customRange ? trimEnd : undefined)}>
            <span><PlayIcon size={15} fill="currentColor" /> Watch while enhancing</span>
            <small>Plays in rolling parts as they finish</small>
          </button>
        </div>
        <p className="private-note"><ShieldIcon size={15} /> Video never leaves this computer</p>
      </aside>
    </main>
  );
}
