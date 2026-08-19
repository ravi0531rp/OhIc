"use client";
/* Enhanced parts are local generated media; captions remain in the source container. */
/* eslint-disable jsx-a11y/media-has-caption */

import { useEffect, useMemo, useRef, useState } from "react";
import type { JobRecord, StreamChunk, VideoRecord } from "../lib/types";
import { mediaUrl } from "../lib/api";
import { ArrowLeftIcon, DownloadIcon, HistoryIcon, PlayIcon, StopIcon } from "./Icons";

type Props = {
  job: JobRecord;
  video: VideoRecord;
  onLeave: () => void;
  onCancel: () => void;
  onHistory: () => void;
};

const ACTIVE = ["queued", "preparing", "processing", "encoding"];

function formatTime(value: number): string {
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  const seconds = Math.floor(value % 60);
  return `${hours ? `${hours}:` : ""}${hours ? String(minutes).padStart(2, "0") : minutes}:${String(seconds).padStart(2, "0")}`;
}

export function AsyncEnhancementViewer({ job, video, onLeave, onCancel, onHistory }: Props) {
  const playerRef = useRef<HTMLVideoElement>(null);
  const stream = job.stream;
  const ready = useMemo(
    () => stream?.chunks.filter((chunk) => chunk.status === "ready" && chunk.playback_url) ?? [],
    [stream],
  );
  const [currentIndex, setCurrentIndex] = useState<number | null>(ready[0]?.index ?? null);
  const [continuePlaying, setContinuePlaying] = useState(false);
  const [waitingForNext, setWaitingForNext] = useState(false);
  const automaticallyReadyNext = waitingForNext && currentIndex != null
    ? stream?.chunks.find(
        (chunk) => chunk.index === currentIndex + 1 && chunk.status === "ready",
      )
    : undefined;
  const playbackIndex = automaticallyReadyNext?.index ?? currentIndex ?? ready[0]?.index ?? null;
  const current = stream?.chunks.find((chunk) => chunk.index === playbackIndex);
  const active = ACTIVE.includes(job.status);
  const selectedDuration = Math.max(
    0.1,
    (job.trim_end ?? video.metadata.duration) - job.trim_start,
  );
  const bufferPercent = Math.min(100, ((stream?.buffered_seconds ?? 0) / selectedDuration) * 100);
  const initialPartDuration = stream?.chunks[0]
    ? stream.chunks[0].end - stream.chunks[0].start
    : 0;

  useEffect(() => {
    if (!continuePlaying || !current?.playback_url) return;
    const player = playerRef.current;
    if (player) void player.play().catch(() => undefined);
  }, [continuePlaying, current?.playback_url]);

  const onEnded = () => {
    if (playbackIndex == null || !stream) return;
    const next = stream.chunks.find((chunk) => chunk.index === playbackIndex + 1);
    if (next?.status === "ready") {
      setCurrentIndex(next.index);
      setContinuePlaying(true);
    } else if (next) {
      setWaitingForNext(true);
    }
  };

  const selectChunk = (chunk: StreamChunk) => {
    if (chunk.status !== "ready") return;
    setCurrentIndex(chunk.index);
    setWaitingForNext(false);
    setContinuePlaying(true);
  };

  return (
    <main className="async-page">
      <header className="async-header">
        <button className="back-button" onClick={onLeave}><ArrowLeftIcon size={18} /> Leave session</button>
        <div className="async-title"><span className="eyebrow">Watch while enhancing</span><h1>{video.title ?? video.original_name}</h1></div>
        <div className="async-actions">
          <button onClick={onHistory}><HistoryIcon size={16} /> History</button>
          {active ? <button className="async-stop" onClick={onCancel}><StopIcon size={14} /> Stop</button> : job.output_url ? <a href={mediaUrl(job.output_url)} download><DownloadIcon size={16} /> Download</a> : null}
        </div>
      </header>

      <section className="async-layout">
        <div className="async-player-shell">
          <div className="async-player">
            {current?.playback_url ? (
              <video
                key={current.playback_url}
                ref={playerRef}
                controls
                playsInline
                src={mediaUrl(current.playback_url)}
                onEnded={onEnded}
                onLoadedData={() => {
                  if (automaticallyReadyNext) {
                    setCurrentIndex(automaticallyReadyNext.index);
                    setWaitingForNext(false);
                    setContinuePlaying(true);
                  }
                }}
                onPlay={() => {
                  setCurrentIndex(playbackIndex);
                  setContinuePlaying(true);
                }}
              />
            ) : (
              <div className="async-waiting">
                <span className="stream-pulse"><PlayIcon size={22} fill="currentColor" /></span>
                <strong>Preparing the first enhanced part</strong>
                <p>Playback unlocks as soon as the startup part is encoded. The full video does not need to finish first.</p>
              </div>
            )}
            {waitingForNext && (
              <div className="async-buffering"><span /><strong>Building the next part…</strong><small>Playback resumes automatically.</small></div>
            )}
            {current && <span className="async-part-label">Enhanced · Part {current.index + 1}</span>}
          </div>

          <div className="async-buffer-status">
            <div><span>Rolling buffer</span><strong>{formatTime(stream?.buffered_seconds ?? 0)} ready</strong></div>
            <div className="async-buffer-track"><i style={{ width: `${bufferPercent}%` }} /></div>
            <small>{stream?.ready_chunks ?? 0} of {stream?.total_chunks ?? 0} parts playable · next parts are produced in the background</small>
          </div>
        </div>

        <aside className="async-queue">
          <div className="async-progress-copy">
            <span className="eyebrow">Enhancement progress</span>
            <div><h2>{job.progress.stage}</h2><strong>{Math.round(job.progress.percent)}%</strong></div>
            <p>{job.progress.detail ?? `${job.target_width} × ${job.target_height} · ${job.preset}`}</p>
          </div>
          <div className="async-overall-track"><i style={{ width: `${job.progress.percent}%` }} /></div>
          <div className="async-plan">
            <span>Initial buffer</span>
            <strong>{formatTime(initialPartDuration)}</strong>
            <small>Largest part first · later parts are {formatTime(stream?.chunk_duration ?? 20)} max.</small>
          </div>
          <div className="async-parts" aria-label="Enhanced video parts">
            {stream?.chunks.map((chunk) => (
              <button
                key={chunk.index}
                className={`${chunk.status} ${playbackIndex === chunk.index ? "active" : ""}`}
                disabled={chunk.status !== "ready"}
                onClick={() => selectChunk(chunk)}
              >
                <span>{String(chunk.index + 1).padStart(2, "0")}</span>
                <span><strong>{formatTime(chunk.start)}–{formatTime(chunk.end)}</strong><small>{chunk.status === "processing" ? `${Math.round(chunk.progress)}% processing` : chunk.status}</small></span>
                <i />
              </button>
            ))}
          </div>
          <p className="async-note">If playback catches the processor, OhIc pauses at the part boundary and resumes automatically when the next part is ready.</p>
        </aside>
      </section>
    </main>
  );
}
