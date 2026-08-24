"use client";

import { useCallback, useEffect, useState } from "react";
import { api, API_URL } from "./lib/api";
import type {
  EnhancementModel,
  BatchRecord,
  ComparisonRecord,
  Health,
  HistoryEntry,
  JobKind,
  JobRecord,
  PlaylistRecord,
  QualityPreset,
  ResolutionTarget,
  StorageItem,
  VideoRecord,
  VideoAnalysis,
} from "./lib/types";
import { ComparisonViewer } from "./components/ComparisonViewer";
import { AsyncEnhancementViewer } from "./components/AsyncEnhancementViewer";
import { EnhancementWorkspace } from "./components/EnhancementWorkspace";
import { HistoryDrawer } from "./components/HistoryDrawer";
import { HardDriveIcon, HistoryIcon, SparkIcon, XIcon } from "./components/Icons";
import { PlaylistIcon } from "./components/Icons";
import { ProgressPanel } from "./components/ProgressPanel";
import { SourcePicker } from "./components/SourcePicker";
import { StorageDrawer } from "./components/StorageDrawer";
import { PlaylistDrawer } from "./components/PlaylistDrawer";
import { BatchDrawer } from "./components/BatchDrawer";
import { MultiPreviewViewer } from "./components/MultiPreviewViewer";
import { ProIntelligenceWorkspace } from "./components/ProIntelligenceWorkspace";

const FALLBACK_MODELS: EnhancementModel[] = [{
  identifier: "realesrgan-x2plus",
  display_name: "Real-ESRGAN ×2",
  scale_factors: [2],
  supported_devices: ["mps", "cuda", "cpu"],
  weights: ["RealESRGAN_x2plus.pth"],
  license: "BSD-3-Clause",
  source_url: "https://github.com/xinntao/Real-ESRGAN",
  description: "Fast frame-based enhancement",
  experimental: false,
  temporal: false,
  supports_stream: true,
}, {
  identifier: "resize-lanczos",
  display_name: "Precision resize",
  scale_factors: [1],
  supported_devices: ["cpu"],
  weights: [],
  license: "MIT",
  source_url: "https://pillow.readthedocs.io/",
  description: "Fast Lanczos downsize without generated detail",
  experimental: false,
  temporal: false,
  supports_stream: true,
}];

type SourceDestination = "enhancement" | "pro";

export function OhIcApp() {
  const [health, setHealth] = useState<Health | null>(null);
  const [models, setModels] = useState<EnhancementModel[]>(FALLBACK_MODELS);
  const [video, setVideo] = useState<VideoRecord | null>(null);
  const [job, setJob] = useState<JobRecord | null>(null);
  const [comparison, setComparison] = useState<JobRecord | null>(null);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [storage, setStorage] = useState<StorageItem[]>([]);
  const [storageOpen, setStorageOpen] = useState(false);
  const [storageBusy, setStorageBusy] = useState(false);
  const [playlists, setPlaylists] = useState<PlaylistRecord[]>([]);
  const [playlistsOpen, setPlaylistsOpen] = useState(false);
  const [batches, setBatches] = useState<BatchRecord[]>([]);
  const [batchesOpen, setBatchesOpen] = useState(false);
  const [previewLab, setPreviewLab] = useState<ComparisonRecord | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [proOpen, setProOpen] = useState(false);
  const [sourceDestination, setSourceDestination] = useState<SourceDestination>("enhancement");

  const refreshHistory = useCallback(async () => {
    try { setHistory(await api.history()); } catch { /* backend state is shown separately */ }
  }, []);

  const refreshStorage = useCallback(async () => {
    try { setStorage(await api.storage()); } catch { /* surfaced when the user performs cleanup */ }
  }, []);

  const refreshPlaylists = useCallback(async () => {
    try { setPlaylists(await api.playlists()); } catch { /* local engine status is surfaced separately */ }
  }, []);

  const refreshBatches = useCallback(async () => {
    try { setBatches(await api.batches()); } catch { /* local engine status is surfaced separately */ }
  }, []);

  useEffect(() => {
    void api.health().then(setHealth).catch(() => setError("OhIc's local engine is not running. Start the backend, then refresh this page."));
    void api.models().then(setModels).catch(() => undefined);
    void api.history().then(setHistory).catch(() => undefined);
    void api.playlists().then(setPlaylists).catch(() => undefined);
    void api.batches().then(setBatches).catch(() => undefined);
  }, [refreshHistory]);

  const hasActivePlaylist = playlists.some((playlist) => ["queued", "running"].includes(playlist.status));
  const hasActiveBatch = batches.some((batch) => ["queued", "running"].includes(batch.status));
  useEffect(() => {
    if (!hasActivePlaylist && !playlistsOpen) return;
    const timer = window.setInterval(() => void refreshPlaylists(), 900);
    return () => window.clearInterval(timer);
  }, [hasActivePlaylist, playlistsOpen, refreshPlaylists]);
  useEffect(() => {
    if (!hasActiveBatch && !batchesOpen) return;
    const timer = window.setInterval(() => void refreshBatches(), 900);
    return () => window.clearInterval(timer);
  }, [batchesOpen, hasActiveBatch, refreshBatches]);

  useEffect(() => {
    if (!historyOpen) return;
    const timer = window.setInterval(() => void refreshHistory(), 900);
    return () => window.clearInterval(timer);
  }, [historyOpen, refreshHistory]);

  useEffect(() => {
    if (!previewLab || !["queued", "running"].includes(previewLab.status)) return;
    const timer = window.setInterval(() => {
      void api.comparison(previewLab.id).then(setPreviewLab).catch(() => undefined);
    }, 800);
    return () => window.clearInterval(timer);
  }, [previewLab]);

  const activeJobId = job && !["complete", "failed", "cancelled", "paused"].includes(job.status) ? job.id : null;
  useEffect(() => {
    if (!activeJobId) return;
    let disposed = false;
    let events: EventSource | null = null;
    let reconnectTimer: number | null = null;
    let reconnectAttempts = 0;

    const applyUpdate = (next: JobRecord) => {
      if (disposed) return;
      setJob(next);
      if (next.status === "complete") {
        if (next.kind !== "stream") setComparison(next);
        setBusy(false);
        void refreshHistory();
      } else if (["failed", "cancelled", "paused"].includes(next.status)) {
        if (next.error) setError(next.error);
        setBusy(false);
      } else {
        setBusy(true);
      }
    };

    const connect = () => {
      if (disposed) return;
      events = new EventSource(`${API_URL}/api/jobs/${activeJobId}/events`);
      events.addEventListener("progress", (event) => {
        reconnectAttempts = 0;
        const next = JSON.parse((event as MessageEvent).data) as JobRecord;
        applyUpdate(next);
        if (["complete", "failed", "cancelled", "paused"].includes(next.status)) events?.close();
      });
      events.onerror = () => {
        events?.close();
        if (disposed) return;
        void api.job(activeJobId).then((latest) => {
          applyUpdate(latest);
          if (!["complete", "failed", "cancelled", "paused"].includes(latest.status)) {
            reconnectAttempts += 1;
            if (reconnectAttempts === 3) {
              setError("Live progress is reconnecting. The enhancement is still running locally.");
            }
            reconnectTimer = window.setTimeout(connect, 1200);
          }
        }).catch(() => {
          reconnectAttempts += 1;
          reconnectTimer = window.setTimeout(connect, 1500);
        });
      };
    };

    connect();
    return () => {
      disposed = true;
      events?.close();
      if (reconnectTimer != null) window.clearTimeout(reconnectTimer);
    };
  }, [activeJobId, refreshHistory]);

  const runJob = async (
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
  ) => {
    if (!video) return;
    setBusy(true);
    setError(null);
    try {
      setJob(await api.createJob({
        video_id: video.id,
        kind,
        target_width: target.width,
        target_height: target.height,
        preset,
        model_id: modelId,
        preview_timestamp: timestamp,
        trim_start: trimStart,
        trim_end: trimEnd,
        ...output,
      }));
    } catch (requestError) {
      setBusy(false);
      setError(requestError instanceof Error ? requestError.message : "Enhancement could not start.");
    }
  };

  const runMultiPreview = async (
    target: ResolutionTarget,
    modelId: string,
    timestamp: number,
    scanTreatment: "auto" | "off" | "deinterlace" | "ivtc",
  ) => {
    if (!video) return;
    setBusy(true);
    setError(null);
    try {
      const variants = (["fast", "balanced", "maximum"] as QualityPreset[]).map((preset) => ({
        label: preset === "fast" ? "Fast pass" : preset === "balanced" ? "Balanced pass" : "Maximum pass",
        target_width: target.width,
        target_height: target.height,
        preset,
        model_id: modelId,
        scan_treatment: scanTreatment,
      }));
      setPreviewLab(await api.createComparison({ video_id: video.id, timestamp, variants }));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Preview Lab could not start.");
    } finally {
      setBusy(false);
    }
  };

  const cancelPlaylist = async (selected: PlaylistRecord) => {
    try {
      await api.cancelPlaylist(selected.id);
      await Promise.all([refreshPlaylists(), refreshHistory()]);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Playlist cancellation failed.");
    }
  };

  const deletePlaylist = async (selected: PlaylistRecord) => {
    try {
      await api.deletePlaylist(selected.id);
      await refreshPlaylists();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Playlist removal failed.");
    }
  };

  const openPlaylistResult = async (jobId: string) => {
    try {
      const selectedJob = await api.job(jobId);
      const source = await api.video(selectedJob.video_id);
      setVideo(source);
      setJob(selectedJob);
      setComparison(selectedJob);
      setPlaylistsOpen(false);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "This playlist result is unavailable.");
    }
  };

  const updateBatch = async (action: "pause" | "resume" | "cancel", selected: BatchRecord) => {
    try {
      if (action === "pause") await api.pauseBatch(selected.id);
      else if (action === "resume") await api.resumeBatch(selected.id);
      else await api.cancelBatch(selected.id);
      await Promise.all([refreshBatches(), refreshHistory()]);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Batch action failed.");
    }
  };

  const cancel = async () => {
    if (!job) return;
    try {
      setJob(await api.cancelJob(job.id));
      setBusy(false);
      await refreshHistory();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Cancellation failed.");
    }
  };

  const pause = async (selected = job) => {
    if (!selected) return;
    try {
      const pausing = await api.pauseJob(selected.id);
      if (job?.id === selected.id) setJob(pausing);
      await refreshHistory();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Pause failed.");
    }
  };

  const resume = async (selected = job) => {
    if (!selected) return;
    try {
      const resumed = await api.resumeJob(selected.id);
      if (job?.id === selected.id) setJob(resumed);
      setBusy(true);
      await refreshHistory();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Resume failed.");
    }
  };

  const cancelFromHistory = async (selected: HistoryEntry) => {
    try {
      if (selected.kind === "pro") {
        await api.cancelAnalysis(selected.reference_id);
      } else if (selected.kind === "enhancement") {
        const cancelled = await api.cancelJob(selected.reference_id);
        if (job?.id === cancelled.id) {
          setJob(cancelled);
          setBusy(false);
        }
      }
      await refreshHistory();
      if (storageOpen) await refreshStorage();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Cancellation failed.");
    }
  };

  const cleanupStorage = async (ids: string[]) => {
    setStorageBusy(true);
    setError(null);
    try {
      await api.cleanupStorage(ids);
      const removedCurrentSource = video && ids.includes(`video:${video.id}`);
      if (removedCurrentSource) reset();
      await Promise.all([refreshStorage(), refreshHistory()]);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Cleanup failed.");
    } finally {
      setStorageBusy(false);
    }
  };

  const pauseFromHistory = async (selected: HistoryEntry) => {
    if (selected.kind !== "enhancement") return;
    try {
      await pause(await api.job(selected.reference_id));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Pause failed.");
    }
  };

  const resumeFromHistory = async (selected: HistoryEntry) => {
    if (selected.kind !== "enhancement") return;
    try {
      await resume(await api.job(selected.reference_id));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Resume failed.");
    }
  };

  const selectHistory = async (selected: HistoryEntry) => {
    try {
      if (selected.kind === "pro") {
        await openProAnalysis(await api.analysis(selected.reference_id));
      } else if (selected.kind === "camera") {
        setVideo(await api.video(selected.video_id));
        setJob(null);
        setComparison(null);
        setPreviewLab(null);
        setBusy(false);
        setProOpen(false);
      } else {
        const latest = await api.job(selected.reference_id);
        const source = await api.video(latest.video_id);
        const active = !["complete", "failed", "cancelled"].includes(latest.status);
        setVideo(source);
        setJob(latest);
        setComparison(latest.status === "complete" && latest.kind !== "stream" ? latest : null);
        setBusy(active);
        setProOpen(false);
      }
      setError(null);
      setHistoryOpen(false);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "This history entry is unavailable.");
    }
  };

  const reset = () => {
    setVideo(null);
    setJob(null);
    setComparison(null);
    setBusy(false);
    setPreviewLab(null);
    setSourceDestination("enhancement");
  };

  const chooseProSource = () => {
    reset();
    setSourceDestination("pro");
    setProOpen(false);
  };

  const sourceLoaded = (source: VideoRecord) => {
    setVideo(source);
    setError(null);
    void refreshHistory();
    if (sourceDestination === "pro") {
      setProOpen(true);
      setSourceDestination("enhancement");
    }
  };

  const openProAnalysis = async (analysis: VideoAnalysis) => {
    try {
      setVideo(await api.video(analysis.video_id));
      setJob(null);
      setComparison(null);
      setPreviewLab(null);
      setProOpen(true);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "This analyzed video is unavailable.");
    }
  };

  if (job?.kind === "stream" && video) {
    return (
      <div className="app-shell">
        <AsyncEnhancementViewer
          job={job}
          video={video}
          onLeave={reset}
          onCancel={() => void cancel()}
          onPause={() => void pause()}
          onResume={() => void resume()}
          onHistory={() => { setHistoryOpen(true); void refreshHistory(); }}
        />
        <HistoryDrawer entries={history} open={historyOpen} onClose={() => setHistoryOpen(false)} onSelect={(selected) => void selectHistory(selected)} onCancel={(selected) => void cancelFromHistory(selected)} onPause={(selected) => void pauseFromHistory(selected)} onResume={(selected) => void resumeFromHistory(selected)} />
        {error && <ErrorToast message={error} onClose={() => setError(null)} />}
      </div>
    );
  }

  if (comparison && video) {
    return (
      <div className="app-shell">
        <ComparisonViewer job={comparison} video={video} onBack={() => setComparison(null)} onAnother={reset} onOpenPro={() => { setComparison(null); setProOpen(true); }} onPlaylists={() => { setPlaylistsOpen(true); void refreshPlaylists(); }} />
        <PlaylistDrawer playlists={playlists} open={playlistsOpen} onClose={() => setPlaylistsOpen(false)} onCancel={(selected) => void cancelPlaylist(selected)} onDelete={(selected) => void deletePlaylist(selected)} onOpenResult={(id) => void openPlaylistResult(id)} />
        {error && <ErrorToast message={error} onClose={() => setError(null)} />}
      </div>
    );
  }

  if (previewLab && video) {
    return (
      <div className="app-shell">
        <MultiPreviewViewer comparison={previewLab} video={video} onBack={() => setPreviewLab(null)} onCancel={() => void api.cancelComparison(previewLab.id).then(setPreviewLab)} />
        {error && <ErrorToast message={error} onClose={() => setError(null)} />}
      </div>
    );
  }

  return (
    <div className="app-shell">
      <nav className="topbar">
        <button className="brand" onClick={reset} aria-label="OhIc home"><span className="brand-mark">O</span><span>OhIc</span></button>
        <div className="top-actions">
          {health && <span className={`hardware-pill ${health.status}`}><i /> {health.status === "ok" ? "Engine ready" : "Setup required"}</span>}
          <button className={proOpen ? "nav-pro active" : "nav-pro"} onClick={() => { setProOpen(true); setPlaylistsOpen(false); setStorageOpen(false); setHistoryOpen(false); }}><SparkIcon size={16} /> Pro <span>Optional</span></button>
          <button onClick={() => { setPlaylistsOpen(true); setStorageOpen(false); setHistoryOpen(false); void refreshPlaylists(); }}><PlaylistIcon size={17} /> Playlists{hasActivePlaylist && <i className="nav-live" />}</button>
          <button onClick={() => { setBatchesOpen(true); setPlaylistsOpen(false); setStorageOpen(false); setHistoryOpen(false); void refreshBatches(); }}><PlaylistIcon size={17} /> Batch queue{hasActiveBatch && <i className="nav-live" />}</button>
          <button onClick={() => { setStorageOpen(true); setPlaylistsOpen(false); setHistoryOpen(false); void refreshStorage(); }}><HardDriveIcon size={17} /> Storage</button>
          <button onClick={() => { setHistoryOpen(true); setPlaylistsOpen(false); setStorageOpen(false); void refreshHistory(); }}><HistoryIcon size={17} /> History</button>
        </div>
      </nav>

      {proOpen ? (
        <ProIntelligenceWorkspace
          key={video?.id ?? "pro-library"}
          video={video}
          onClose={() => setProOpen(false)}
          onChooseSource={chooseProSource}
          onEnhance={() => setProOpen(false)}
          onSelectAnalysis={(analysis) => void openProAnalysis(analysis)}
          onError={setError}
        />
      ) : !video ? (
        <main className="landing">
          <div className="ambient ambient-one" />
          <div className="ambient ambient-two" />
          <section className="hero-copy">
            <span className="hero-kicker"><SparkIcon size={15} /> Private local video studio</span>
            <h1>Restore. Search.<br /><em>Understand video.</em></h1>
            <p>Enhance difficult footage, shrink oversized exports, track subjects, search speech and frames, or capture a nearby phone camera—all on your computer.</p>
            <div className="studio-capabilities"><span><strong>Restore</strong><small>Spatial + temporal AI</small></span><span><strong>Understand</strong><small>Multimodal RAG</small></span><span><strong>Capture</strong><small>Wi-Fi phone camera</small></span><span><strong>Organize</strong><small>Batch + playlists</small></span></div>
          </section>
          <SourcePicker onLoaded={sourceLoaded} onPlaylistStarted={(started) => { setPlaylists((current) => [started, ...current.filter((item) => item.id !== started.id)]); setPlaylistsOpen(true); setError(null); }} onBatchStarted={(started) => { setBatches((current) => [started, ...current.filter((item) => item.id !== started.id)]); setBatchesOpen(true); setError(null); }} onError={setError} />
          <div className="trust-row">
            <span>Restoration + downsize</span>
            <span>Multilingual intelligence</span>
            <span>Local-first · no account</span>
          </div>
        </main>
      ) : (
        <div className="workspace-wrap">
          <div className="workspace-topline">
            <button onClick={reset}>← New video</button>
            <span>{video.source_type === "youtube" ? "YouTube source" : video.source_type === "camera" ? "Phone camera source" : "Uploaded source"}</span>
          </div>
          {job && !["complete", "failed", "cancelled"].includes(job.status) && <ProgressPanel job={job} onCancel={() => void cancel()} onPause={() => void pause()} onResume={() => void resume()} />}
          <EnhancementWorkspace key={`${video.id}:${job?.id ?? "new"}`} video={video} models={models} initialJob={job} busy={busy} onOpenPro={() => setProOpen(true)} onRun={(...args) => void runJob(...args)} onMultiPreview={(...args) => void runMultiPreview(...args)} />
        </div>
      )}

      <HistoryDrawer entries={history} open={historyOpen} onClose={() => setHistoryOpen(false)} onSelect={(selected) => void selectHistory(selected)} onCancel={(selected) => void cancelFromHistory(selected)} onPause={(selected) => void pauseFromHistory(selected)} onResume={(selected) => void resumeFromHistory(selected)} />
      <StorageDrawer items={storage} open={storageOpen} busy={storageBusy} onClose={() => setStorageOpen(false)} onCleanup={(ids) => void cleanupStorage(ids)} />
      <PlaylistDrawer playlists={playlists} open={playlistsOpen} onClose={() => setPlaylistsOpen(false)} onCancel={(selected) => void cancelPlaylist(selected)} onDelete={(selected) => void deletePlaylist(selected)} onOpenResult={(id) => void openPlaylistResult(id)} />
      <BatchDrawer batches={batches} open={batchesOpen} onClose={() => setBatchesOpen(false)} onPause={(selected) => void updateBatch("pause", selected)} onResume={(selected) => void updateBatch("resume", selected)} onCancel={(selected) => void updateBatch("cancel", selected)} onOpenResult={(id) => void openPlaylistResult(id)} />
      {error && <ErrorToast message={error} onClose={() => setError(null)} />}
    </div>
  );
}

function ErrorToast({ message, onClose }: { message: string; onClose: () => void }) {
  return (
    <div className="error-toast" role="alert">
      <span>!</span><p><strong>OhIc needs attention</strong>{message}</p>
      <button aria-label="Dismiss error" onClick={onClose}><XIcon size={16} /></button>
    </div>
  );
}
