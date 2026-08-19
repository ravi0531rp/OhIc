"use client";
/* Video captions are preserved when present; generated sidecar caption tracks are not yet available. */
/* eslint-disable jsx-a11y/media-has-caption */

import { useCallback, useEffect, useRef, useState } from "react";
import type { JobRecord, VideoRecord } from "../lib/types";
import { mediaUrl } from "../lib/api";
import { ArrowLeftIcon, DownloadIcon, FilmIcon, PlaylistIcon } from "./Icons";

type Props = {
  job: JobRecord;
  video: VideoRecord;
  onBack: () => void;
  onAnother: () => void;
  onPlaylists: () => void;
};

export function ComparisonViewer({ job, video, onBack, onAnother, onPlaylists }: Props) {
  const originalRef = useRef<HTMLVideoElement>(null);
  const enhancedRef = useRef<HTMLVideoElement>(null);
  const [mode, setMode] = useState<"wipe" | "side">("wipe");
  const [position, setPosition] = useState(50);
  const [zoom, setZoom] = useState<"fit" | "100" | "200">("fit");
  const originalSource = mediaUrl(job.original_preview_url ?? video.playback_url);
  const enhancedSource = mediaUrl(job.output_url);
  const fps = video.metadata.fps || 30;

  const sync = useCallback((force = false) => {
    const source = originalRef.current;
    const target = enhancedRef.current;
    if (!source || !target || !Number.isFinite(source.currentTime)) return;
    if (force || Math.abs(target.currentTime - source.currentTime) > 0.08) {
      target.currentTime = source.currentTime;
    }
    if (target.playbackRate !== source.playbackRate) target.playbackRate = source.playbackRate;
  }, []);

  useEffect(() => {
    const source = originalRef.current;
    const target = enhancedRef.current;
    if (!source || !target) return;
    const play = () => { sync(true); void target.play().catch(() => undefined); };
    const pause = () => target.pause();
    const seek = () => sync(true);
    const tick = () => sync(false);
    const rate = () => sync(false);
    source.addEventListener("play", play);
    source.addEventListener("pause", pause);
    source.addEventListener("seeking", seek);
    source.addEventListener("timeupdate", tick);
    source.addEventListener("ratechange", rate);
    return () => {
      source.removeEventListener("play", play);
      source.removeEventListener("pause", pause);
      source.removeEventListener("seeking", seek);
      source.removeEventListener("timeupdate", tick);
      source.removeEventListener("ratechange", rate);
    };
  }, [sync, mode]);

  const stepFrame = (direction: number) => {
    const source = originalRef.current;
    if (!source) return;
    source.pause();
    source.currentTime = Math.max(0, Math.min(source.duration || Infinity, source.currentTime + direction / fps));
    sync(true);
  };

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        event.preventDefault();
        stepFrame(event.key === "ArrowLeft" ? -1 : 1);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  });

  const scale = zoom === "fit" ? 1 : zoom === "100" ? 1.35 : 2;
  const range = job.trim_end || job.trim_start
    ? `${formatTime(job.trim_start)}–${formatTime(job.trim_end ?? video.metadata.duration)}`
    : "Full video";
  const model = job.model_id.startsWith("realbasicvsr")
    ? "RealBasicVSR ×4 · Experimental"
    : "Real-ESRGAN ×2";

  return (
    <main className="compare-page">
      <header className="compare-header">
        <button className="back-button" onClick={onBack}><ArrowLeftIcon size={18} /> Back to workspace</button>
        <div className="compare-title">
          <span className="eyebrow">Enhancement complete</span>
          <h1>See what changed.</h1>
        </div>
        <div className="compare-actions"><button onClick={onPlaylists}><PlaylistIcon size={17} /> Playlists</button><a className="download-button" href={enhancedSource} download><DownloadIcon size={18} /> Download video</a></div>
      </header>

      <section className="viewer-shell">
        <div className="viewer-toolbar">
          <div className="segmented compact">
            <button className={mode === "wipe" ? "active" : ""} onClick={() => setMode("wipe")}>Comparison slider</button>
            <button className={mode === "side" ? "active" : ""} onClick={() => setMode("side")}>Side by side</button>
          </div>
          <div className="zoom-control">
            <span>Zoom</span>
            {(["fit", "100", "200"] as const).map((value) => (
              <button key={value} className={zoom === value ? "active" : ""} onClick={() => setZoom(value)}>
                {value === "fit" ? "Fit" : `${value}%`}
              </button>
            ))}
          </div>
        </div>

        <div className="viewer-overflow">
          <div className={`video-comparison ${mode}`} style={{ transform: `scale(${scale})` }}>
            {mode === "wipe" ? (
              <>
                <video ref={originalRef} className="original-video" controls playsInline src={originalSource} />
                <div className="enhanced-clip" style={{ clipPath: `inset(0 0 0 ${position}%)` }}>
                  <video ref={enhancedRef} muted playsInline src={enhancedSource} />
                </div>
                <span className="video-label original">Original</span>
                <span className="video-label enhanced">Enhanced</span>
                <div className="wipe-line" style={{ left: `${position}%` }}><span /></div>
                <input
                  aria-label="Before and after comparison position"
                  className="wipe-input"
                  max="100"
                  min="0"
                  type="range"
                  value={position}
                  onChange={(event) => setPosition(Number(event.target.value))}
                />
              </>
            ) : (
              <>
                <div className="side-video"><span className="video-label">Original</span><video ref={originalRef} controls playsInline src={originalSource} /></div>
                <div className="side-video"><span className="video-label">Enhanced</span><video ref={enhancedRef} muted playsInline src={enhancedSource} /></div>
              </>
            )}
          </div>
        </div>

        <div className="frame-tools">
          <button onClick={() => stepFrame(-1)}>← Previous frame</button>
          <span><FilmIcon size={16} /> Pause to inspect frame by frame</span>
          <button onClick={() => stepFrame(1)}>Next frame →</button>
        </div>
      </section>

      <section className="result-strip">
        <div><span>Source</span><strong>{video.metadata.width} × {video.metadata.height}</strong></div>
        <div><span>Enhanced</span><strong>{job.target_width} × {job.target_height}</strong></div>
        <div><span>Model</span><strong>{model}</strong></div>
        <div><span>Preset</span><strong>{job.preset[0].toUpperCase() + job.preset.slice(1)}</strong></div>
        <div><span>Range</span><strong>{range}</strong></div>
        <div><span>Processing time</span><strong>{job.processing_seconds ? `${Math.round(job.processing_seconds)} sec` : "—"}</strong></div>
        <button onClick={onAnother}>Enhance another video</button>
      </section>
    </main>
  );
}

function formatTime(value: number): string {
  const minutes = Math.floor(value / 60);
  const seconds = Math.floor(value % 60);
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}
