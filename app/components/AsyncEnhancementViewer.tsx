"use client";
/* Enhanced media is generated locally; sidecar caption tracks are not available in this release. */
/* eslint-disable jsx-a11y/media-has-caption */

import { useEffect, useMemo, useRef, useState } from "react";
import type { JobRecord, VideoRecord } from "../lib/types";
import { mediaUrl } from "../lib/api";
import {
  ArrowLeftIcon,
  DownloadIcon,
  ExpandIcon,
  HistoryIcon,
  PauseIcon,
  PlayIcon,
  StopIcon,
  VolumeIcon,
  VolumeOffIcon,
} from "./Icons";

type Props = {
  job: JobRecord;
  video: VideoRecord;
  onLeave: () => void;
  onCancel: () => void;
  onHistory: () => void;
};

const ACTIVE = ["queued", "preparing", "processing", "encoding"];

function formatTime(value: number): string {
  const safe = Math.max(0, Number.isFinite(value) ? value : 0);
  const hours = Math.floor(safe / 3600);
  const minutes = Math.floor((safe % 3600) / 60);
  const seconds = Math.floor(safe % 60);
  return `${hours ? `${hours}:` : ""}${hours ? String(minutes).padStart(2, "0") : minutes}:${String(seconds).padStart(2, "0")}`;
}

function displayStage(stage: string): string {
  if (stage.startsWith("Enhancing part") || stage.startsWith("Part ")) return "Enhancing video";
  if (stage.startsWith("Preparing part")) return "Preparing playback";
  if (stage.startsWith("Packaging part")) return "Extending playable buffer";
  if (stage === "Joining enhanced parts") return "Finalizing video";
  return stage;
}

export function AsyncEnhancementViewer({ job, video, onLeave, onCancel, onHistory }: Props) {
  const playerRef = useRef<HTMLVideoElement>(null);
  const playerShellRef = useRef<HTMLDivElement>(null);
  const pendingSeekRef = useRef<number | null>(null);
  const finalSourceRef = useRef("");
  const stream = job.stream;
  const ready = useMemo(
    () => stream?.chunks.filter((chunk) => chunk.status === "ready" && chunk.playback_url) ?? [],
    [stream],
  );
  const [currentIndex, setCurrentIndex] = useState<number | null>(ready[0]?.index ?? null);
  const [shouldPlay, setShouldPlay] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const [waitingForNext, setWaitingForNext] = useState(false);
  const [playheadSeconds, setPlayheadSeconds] = useState(0);
  const [volume, setVolume] = useState(1);
  const [muted, setMuted] = useState(false);

  const automaticallyReadyNext = waitingForNext && currentIndex != null
    ? stream?.chunks.find(
        (chunk) => chunk.index === currentIndex + 1 && chunk.status === "ready",
      )
    : undefined;
  const playbackIndex = automaticallyReadyNext?.index ?? currentIndex ?? ready[0]?.index ?? null;
  const current = stream?.chunks.find((chunk) => chunk.index === playbackIndex);
  const nextReady = current
    ? stream?.chunks.find(
        (chunk) => chunk.index === current.index + 1 && chunk.status === "ready" && chunk.playback_url,
      )
    : undefined;
  const finalSource = job.status === "complete" && job.output_url ? mediaUrl(job.output_url) : "";
  const currentSource = current?.playback_url ? mediaUrl(current.playback_url) : "";
  const videoSource = finalSource || currentSource;
  const active = ACTIVE.includes(job.status);
  const selectedDuration = Math.max(
    0.1,
    (job.trim_end ?? video.metadata.duration) - job.trim_start,
  );
  const bufferedSeconds = finalSource
    ? selectedDuration
    : Math.min(selectedDuration, stream?.buffered_seconds ?? 0);
  const bufferPercent = Math.min(100, bufferedSeconds / selectedDuration * 100);
  const playedPercent = Math.min(100, playheadSeconds / selectedDuration * 100);
  const initialPartDuration = stream?.chunks[0]
    ? stream.chunks[0].end - stream.chunks[0].start
    : 0;
  const followupPartDuration = stream?.chunk_duration ?? 5;
  const hasLargeInitialPart = initialPartDuration > followupPartDuration;
  const processingChunk = stream?.chunks.find((chunk) => chunk.status === "processing");

  useEffect(() => {
    if (finalSource && finalSource !== finalSourceRef.current) {
      pendingSeekRef.current = playheadSeconds;
      finalSourceRef.current = finalSource;
    }
  }, [finalSource, playheadSeconds]);

  useEffect(() => {
    const player = playerRef.current;
    if (!player) return;
    player.volume = volume;
    player.muted = muted;
  }, [muted, videoSource, volume]);

  useEffect(() => {
    if (!shouldPlay || !videoSource) return;
    const player = playerRef.current;
    if (player) void player.play().catch(() => undefined);
  }, [shouldPlay, videoSource]);

  const updatePlayhead = () => {
    const player = playerRef.current;
    if (!player) return;
    const value = finalSource
      ? player.currentTime
      : Math.max(0, (current?.start ?? job.trim_start) - job.trim_start + player.currentTime);
    setPlayheadSeconds(Math.min(selectedDuration, value));
  };

  const togglePlayback = () => {
    const player = playerRef.current;
    if (!player || !videoSource) return;
    if (isPlaying || (waitingForNext && shouldPlay)) {
      setShouldPlay(false);
      setIsPlaying(false);
      player.pause();
      return;
    }
    setShouldPlay(true);
    void player.play().catch(() => undefined);
  };

  const seekTo = (requested: number) => {
    if (!videoSource || bufferedSeconds <= 0) return;
    const maximum = Math.max(0, bufferedSeconds - 0.02);
    const bounded = Math.min(maximum, Math.max(0, requested));
    setPlayheadSeconds(bounded);
    setWaitingForNext(false);

    if (finalSource) {
      if (playerRef.current) playerRef.current.currentTime = bounded;
      return;
    }

    const absoluteTime = job.trim_start + bounded;
    const target = ready.find(
      (chunk) => absoluteTime >= chunk.start && absoluteTime < chunk.end - 0.001,
    ) ?? ready.at(-1);
    if (!target) return;
    const localTime = Math.min(
      Math.max(0, target.end - target.start - 0.02),
      Math.max(0, absoluteTime - target.start),
    );
    if (target.index === current?.index && playerRef.current) {
      playerRef.current.currentTime = localTime;
    } else {
      pendingSeekRef.current = localTime;
      setCurrentIndex(target.index);
    }
  };

  const onEnded = () => {
    if (finalSource) {
      setPlayheadSeconds(selectedDuration);
      setShouldPlay(false);
      setIsPlaying(false);
      return;
    }
    if (playbackIndex == null || !stream) return;
    setPlayheadSeconds(
      Math.min(selectedDuration, (current?.end ?? job.trim_start) - job.trim_start),
    );
    const next = stream.chunks.find((chunk) => chunk.index === playbackIndex + 1);
    if (next?.status === "ready") {
      setCurrentIndex(next.index);
    } else if (next) {
      setWaitingForNext(true);
      setIsPlaying(false);
    } else {
      setShouldPlay(false);
      setIsPlaying(false);
    }
  };

  const loadPlaybackPosition = () => {
    const player = playerRef.current;
    if (!player) return;
    if (automaticallyReadyNext) {
      setCurrentIndex(automaticallyReadyNext.index);
      setWaitingForNext(false);
    }
    if (pendingSeekRef.current != null) {
      player.currentTime = pendingSeekRef.current;
      pendingSeekRef.current = null;
    }
    player.volume = volume;
    player.muted = muted;
    if (shouldPlay) void player.play().catch(() => undefined);
  };

  const toggleFullscreen = () => {
    const shell = playerShellRef.current;
    if (!shell) return;
    if (document.fullscreenElement) void document.exitFullscreen();
    else void shell.requestFullscreen();
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
          <div
            className="async-player"
            ref={playerShellRef}
          >
            {videoSource ? (
              <video
                key={videoSource}
                ref={playerRef}
                playsInline
                preload="auto"
                src={videoSource}
                onClick={togglePlayback}
                onEnded={onEnded}
                onLoadedMetadata={loadPlaybackPosition}
                onPause={() => setIsPlaying(false)}
                onPlay={() => {
                  setCurrentIndex(playbackIndex);
                  setShouldPlay(true);
                  setIsPlaying(true);
                }}
                onTimeUpdate={updatePlayhead}
              />
            ) : (
              <div className="async-waiting">
                <span className="stream-pulse"><PlayIcon size={22} fill="currentColor" /></span>
                <strong>Preparing enhanced playback</strong>
                <p>Playback starts as soon as the initial buffer is ready.</p>
              </div>
            )}
            {!finalSource && nextReady?.playback_url && (
              <video className="async-next-preload" aria-hidden muted playsInline preload="auto" src={mediaUrl(nextReady.playback_url)} />
            )}
            {waitingForNext && (
              <div className="async-buffering"><span /><strong>Extending the buffer…</strong><small>Playback resumes automatically.</small></div>
            )}
            <div className="async-video-controls">
              <div className="async-timeline">
                <i className="buffered" style={{ width: `${bufferPercent}%` }} />
                <i className="played" style={{ width: `${playedPercent}%` }} />
                <input
                  aria-label="Video position"
                  disabled={!videoSource}
                  max={selectedDuration}
                  min="0"
                  step="0.05"
                  type="range"
                  value={Math.min(selectedDuration, playheadSeconds)}
                  onChange={(event) => seekTo(Number(event.target.value))}
                />
              </div>
              <div className="async-control-row">
                <button aria-label={isPlaying ? "Pause" : "Play"} disabled={!videoSource} onClick={togglePlayback}>
                  {isPlaying ? <PauseIcon size={18} fill="currentColor" /> : <PlayIcon size={18} fill="currentColor" />}
                </button>
                <time>{formatTime(playheadSeconds)} / {formatTime(selectedDuration)}</time>
                <span />
                <button aria-label={muted ? "Unmute" : "Mute"} disabled={!videoSource} onClick={() => setMuted((value) => !value)}>
                  {muted || volume === 0 ? <VolumeOffIcon size={18} /> : <VolumeIcon size={18} />}
                </button>
                <input aria-label="Volume" className="async-volume" max="1" min="0" step="0.05" type="range" value={volume} onChange={(event) => { const value = Number(event.target.value); setVolume(value); setMuted(value === 0); }} />
                <button aria-label="Toggle fullscreen" disabled={!videoSource} onClick={toggleFullscreen}><ExpandIcon size={18} /></button>
              </div>
            </div>
          </div>

          <div className="async-buffer-status">
            <div><span>Rolling buffer</span><strong>{formatTime(bufferedSeconds)} ready</strong></div>
            <div className="async-buffer-track"><i style={{ width: `${bufferPercent}%` }} /></div>
            <small>Enhanced through {formatTime(bufferedSeconds)} of {formatTime(selectedDuration)} · processing continues in the background</small>
          </div>
        </div>

        <aside className="async-queue">
          <div className="async-progress-copy">
            <span className="eyebrow">Enhancement progress</span>
            <div><h2>{displayStage(job.progress.stage)}</h2><strong>{Math.round(job.progress.percent)}%</strong></div>
            <p>{bufferedSeconds ? `${formatTime(bufferedSeconds)} enhanced and ready to watch` : "Preparing the beginning of the video"}</p>
          </div>
          <div className="async-overall-track"><i style={{ width: `${job.progress.percent}%` }} /></div>
          <div className="async-plan">
            <span>Initial buffer</span>
            <strong>{formatTime(initialPartDuration)}</strong>
            <small>{hasLargeInitialPart ? `Then delivered in ${formatTime(followupPartDuration)} increments.` : `Delivered in ${formatTime(followupPartDuration)} increments.`}</small>
          </div>
          <div className="async-delivery">
            <article><span>Ready to watch</span><strong>{formatTime(bufferedSeconds)}</strong></article>
            <article><span>Now enhancing</span><strong>{processingChunk ? `${formatTime(processingChunk.start - job.trim_start)}–${formatTime(processingChunk.end - job.trim_start)}` : active ? "Preparing" : "Complete"}</strong></article>
            <article><span>Remaining</span><strong>{formatTime(Math.max(0, selectedDuration - bufferedSeconds))}</strong></article>
          </div>
          <p className="async-note">The player uses one continuous timeline. If playback reaches the edge of the available buffer, it pauses and resumes automatically.</p>
        </aside>
      </section>
    </main>
  );
}
