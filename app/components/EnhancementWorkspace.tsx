"use client";
/* Source video captions are not extracted into browser sidecar tracks in this release. */
/* eslint-disable jsx-a11y/media-has-caption */

import { useEffect, useMemo, useRef, useState } from "react";
import type { EnhancementModel, JobKind, JobRecord, QualityPreset, ResolutionTarget, VideoRecord } from "../lib/types";
import { ChevronIcon, PlayIcon, SparkIcon } from "./Icons";
import { api, mediaUrl } from "../lib/api";

type Props = {
  video: VideoRecord;
  models: EnhancementModel[];
  initialJob?: JobRecord | null;
  busy: boolean;
  onRun: (
    kind: JobKind,
    target: ResolutionTarget,
    preset: QualityPreset,
    modelId: string,
    timestamp: number,
    trimStart: number,
    trimEnd?: number,
    output?: {
      output_container: "mp4" | "mkv";
      track_policy: "compatible" | "preserve";
      preserve_metadata: boolean;
      preserve_chapters: boolean;
      scan_treatment: "auto" | "off" | "deinterlace" | "ivtc";
      resource_policy: "auto" | "conservative" | "performance";
      memory_limit_mb?: number;
      scene_aware: boolean;
      scene_threshold: number;
    },
  ) => void;
  onMultiPreview: (
    target: ResolutionTarget,
    modelId: string,
    timestamp: number,
    scanTreatment: "auto" | "off" | "deinterlace" | "ivtc",
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

export function EnhancementWorkspace({ video, models, initialJob, busy, onRun, onMultiPreview }: Props) {
  const [selected, setSelected] = useState(
    video.targets.find(
      (target) =>
        target.width === initialJob?.target_width && target.height === initialJob?.target_height,
    ) ?? video.targets.find((target) => target.recommended) ?? video.targets[0],
  );
  const [preset, setPreset] = useState<QualityPreset>(initialJob?.preset ?? "balanced");
  const [modelId, setModelId] = useState(initialJob?.model_id ?? "realesrgan-x2plus");
  const [timestamp, setTimestamp] = useState(
    initialJob?.preview_timestamp ?? Math.min(video.metadata.duration / 2, 30),
  );
  const [customRange, setCustomRange] = useState(
    Boolean(initialJob && (initialJob.trim_start > 0 || initialJob.trim_end != null)),
  );
  const [trimStart, setTrimStart] = useState(initialJob?.trim_start ?? 0);
  const [trimEnd, setTrimEnd] = useState(initialJob?.trim_end ?? video.metadata.duration);
  const [preserveTracks, setPreserveTracks] = useState(
    initialJob?.track_policy === "preserve",
  );
  const [presetSaved, setPresetSaved] = useState(false);
  const [scanTreatment, setScanTreatment] = useState<"auto" | "off" | "deinterlace" | "ivtc">(
    initialJob?.scan_treatment ?? "auto",
  );
  const [resourcePolicy, setResourcePolicy] = useState<"auto" | "conservative" | "performance">(
    initialJob?.resource_policy ?? "auto",
  );
  const [memoryLimit, setMemoryLimit] = useState<number | undefined>(initialJob?.memory_limit_mb);
  const [sceneAware, setSceneAware] = useState(initialJob?.scene_aware ?? true);
  const [sceneThreshold, setSceneThreshold] = useState(initialJob?.scene_threshold ?? 0.35);
  const playerRef = useRef<HTMLVideoElement>(null);
  const selectedModel = models.find((model) => model.identifier === modelId) ?? models[0];
  const modelUnavailable = Boolean(
    selectedModel?.max_input_pixels
      && video.metadata.width * video.metadata.height > selectedModel.max_input_pixels,
  );

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

  const applyDiagnosisRecipe = () => {
    const recipe = video.diagnosis?.recipe;
    if (!recipe) return;
    const target = video.targets.find((item) => item.height === recipe.target_height);
    if (target) setSelected(target);
    setPreset(recipe.preset);
    if (models.some((model) => model.identifier === recipe.model_id)) {
      setModelId(recipe.model_id);
    }
    setScanTreatment(recipe.deinterlace === "auto" ? "auto" : "off");
  };

  const savePreset = async () => {
    const name = window.prompt("Name this enhancement preset");
    if (!name?.trim()) return;
    await api.createPreset({
      name: name.trim(),
      target_height: selected.height,
      quality: preset,
      model_id: selectedModel.identifier,
      output_container: preserveTracks ? "mkv" : "mp4",
      track_policy: preserveTracks ? "preserve" : "compatible",
      scan_treatment: scanTreatment,
      resource_policy: resourcePolicy,
      memory_limit_mb: memoryLimit,
      scene_aware: sceneAware,
      scene_threshold: sceneThreshold,
    });
    setPresetSaved(true);
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
            <div><span>Media</span><strong>{video.metadata.tracks.filter((track) => track.kind === "audio").length} audio · {video.metadata.tracks.filter((track) => track.kind === "subtitle").length} subs</strong></div>
          </div>
        </div>

        {video.diagnosis && (
          <div className="source-diagnosis">
            <div className="diagnosis-heading">
              <div><span className="eyebrow">Source diagnosis · {video.diagnosis.confidence} confidence</span><h3>{video.diagnosis.verdict}</h3></div>
              <button disabled={busy} onClick={applyDiagnosisRecipe}>Apply recipe</button>
            </div>
            <div className="diagnosis-body">
              <div className="diagnosis-issues">
                {video.diagnosis.issues.length ? video.diagnosis.issues.map((issue) => (
                  <span key={issue.code} className={issue.severity}><i /> <strong>{issue.title}</strong><small>{issue.detail}</small></span>
                )) : <span className="healthy"><i /><strong>No obvious source defects</strong><small>Use a restrained upscale to preserve the original character.</small></span>}
              </div>
              <div className="diagnosis-recipe"><span>Recommended recipe</span><strong>{video.diagnosis.recipe.summary}</strong><small>{video.diagnosis.recipe.reasons.join(" · ")}</small></div>
            </div>
          </div>
        )}

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

        <section className="control-section">
          <div className="section-label"><span>03</span><div><strong>AI engine</strong><small>Real-ESRGAN remains the default</small></div></div>
          <div className="engine-options">
            {models.map((model) => {
              const unavailable = Boolean(
                model.max_input_pixels
                  && video.metadata.width * video.metadata.height > model.max_input_pixels,
              );
              return (
                <button
                  aria-pressed={modelId === model.identifier}
                  className={modelId === model.identifier ? "selected" : ""}
                  disabled={busy || unavailable}
                  key={model.identifier}
                  onClick={() => setModelId(model.identifier)}
                >
                  <span className="radio-dot" />
                  <span className="engine-copy">
                    <strong>{model.display_name}{model.experimental && <em>Experimental</em>}</strong>
                    <small>{unavailable ? "Available for sources up to 720p" : model.description}</small>
                  </span>
                </button>
              );
            })}
          </div>
          {selectedModel?.temporal && !modelUnavailable && (
            <p className="engine-warning">Uses adjacent frames for steadier restoration. Significantly slower, with experimental MPS support.</p>
          )}
        </section>

        <details className="advanced-settings">
          <summary>Advanced details <ChevronIcon size={16} /></summary>
          <div className="advanced-grid">
            <span>AI model<strong>{selectedModel?.display_name ?? "Real-ESRGAN ×2"}</strong></span>
            <span>Final resize<strong>Lanczos</strong></span>
            <span>Output<strong>{preserveTracks ? "H.264 · MKV archive" : "H.264 · MP4"}</strong></span>
            <span>Workload<strong>{workload.level}</strong></span>
          </div>
          <label className="track-policy" htmlFor="preserve-tracks">
            <input id="preserve-tracks" checked={preserveTracks} disabled={busy} type="checkbox" onChange={(event) => setPreserveTracks(event.target.checked)} />
            Preserve every media track
            <small>Use MKV to copy all audio, subtitles, attachments, chapters, and metadata.</small>
          </label>
          <label className="scan-treatment" htmlFor="scan-treatment">Scan treatment<select id="scan-treatment" disabled={busy} value={scanTreatment} onChange={(event) => setScanTreatment(event.target.value as typeof scanTreatment)}><option value="auto">Auto-detect</option><option value="off">Keep original scan</option><option value="deinterlace">Motion-adaptive deinterlace</option><option value="ivtc" disabled={video.metadata.fps < 29 || video.metadata.fps > 31}>Inverse telecine (29.97/30 FPS)</option></select></label>
          <label className="scan-treatment" htmlFor="resource-policy">Resource mode<select id="resource-policy" disabled={busy} value={resourcePolicy} onChange={(event) => setResourcePolicy(event.target.value as typeof resourcePolicy)}><option value="auto">Adaptive</option><option value="conservative">Conservative</option><option value="performance">Performance</option></select></label>
          <label className="scan-treatment" htmlFor="memory-limit">Memory ceiling<select id="memory-limit" disabled={busy} value={memoryLimit ?? ""} onChange={(event) => setMemoryLimit(event.target.value ? Number(event.target.value) : undefined)}><option value="">Automatic</option><option value="2048">2 GB</option><option value="4096">4 GB</option><option value="8192">8 GB</option><option value="16384">16 GB</option></select></label>
          {initialJob?.resource_allocation && <p className="resource-plan">Active plan · {initialJob.resource_allocation.tile_size}px tiles · {initialJob.resource_allocation.temporal_window}-frame temporal window<br />{initialJob.resource_allocation.rationale}</p>}
          {selectedModel?.temporal && <div className="scene-controls"><label htmlFor="scene-aware"><input id="scene-aware" checked={sceneAware} disabled={busy} type="checkbox" onChange={(event) => setSceneAware(event.target.checked)} /> Reset temporal context at scene cuts</label><label htmlFor="scene-threshold">Cut sensitivity <input id="scene-threshold" disabled={busy || !sceneAware} type="range" min="0.15" max="0.65" step="0.05" value={sceneThreshold} onChange={(event) => setSceneThreshold(Number(event.target.value))} /><strong>{sceneThreshold.toFixed(2)}</strong></label></div>}
          <button className="save-preset" disabled={busy} onClick={() => void savePreset()}>{presetSaved ? "Preset saved" : "Save these settings as a preset"}</button>
          <p>AI enhancement creates plausible detail; it should not be used as forensic evidence.</p>
        </details>

        <div className="action-stack">
          <button className="lab-action" disabled={busy || modelUnavailable} onClick={() => onMultiPreview(selected, selectedModel.identifier, timestamp, scanTreatment)}><SparkIcon size={15} /> Compare Fast · Balanced · Maximum</button>
          <button className="primary-action" disabled={busy || modelUnavailable} onClick={() => onRun("preview", selected, preset, selectedModel.identifier, timestamp, 0, undefined, { output_container: "mp4", track_policy: "compatible", preserve_metadata: true, preserve_chapters: true, scan_treatment: scanTreatment, resource_policy: resourcePolicy, memory_limit_mb: memoryLimit, scene_aware: sceneAware, scene_threshold: sceneThreshold })}>
            <PlayIcon size={18} fill="currentColor" /> {busy ? "Preparing…" : "Preview enhancement"}
            <span>5 sec</span>
          </button>
          <button className="secondary-action" disabled={busy || modelUnavailable} onClick={() => onRun("full", selected, preset, selectedModel.identifier, timestamp, customRange ? trimStart : 0, customRange ? trimEnd : undefined, { output_container: preserveTracks ? "mkv" : "mp4", track_policy: preserveTracks ? "preserve" : "compatible", preserve_metadata: true, preserve_chapters: true, scan_treatment: scanTreatment, resource_policy: resourcePolicy, memory_limit_mb: memoryLimit, scene_aware: sceneAware, scene_threshold: sceneThreshold })}>
            {customRange ? "Enhance selected range" : "Enhance full video"} <small>{workload.frames.toLocaleString()} frames</small>
          </button>
          <button className={`stream-action ${!selectedModel.supports_stream ? "unsupported" : ""}`} disabled={busy || modelUnavailable || !selectedModel.supports_stream} onClick={() => onRun("stream", selected, preset, selectedModel.identifier, timestamp, customRange ? trimStart : 0, customRange ? trimEnd : undefined, { output_container: "mp4", track_policy: "compatible", preserve_metadata: true, preserve_chapters: true, scan_treatment: scanTreatment, resource_policy: resourcePolicy, memory_limit_mb: memoryLimit, scene_aware: sceneAware, scene_threshold: sceneThreshold })}>
            <span><PlayIcon size={15} fill="currentColor" /> Watch while enhancing</span>
            <small>{selectedModel.supports_stream ? "Plays in rolling parts as they finish" : "Not available for this experimental engine"}</small>
          </button>
        </div>
        <p className="output-note">{preserveTracks ? "MKV · every source track retained" : "Browser-compatible MP4 · all audio tracks retained"}</p>
      </aside>
    </main>
  );
}
