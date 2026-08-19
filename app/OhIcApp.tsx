"use client";

import { useCallback, useEffect, useState } from "react";
import { api, API_URL } from "./lib/api";
import type {
  Health,
  JobKind,
  JobRecord,
  PlaylistRecord,
  QualityPreset,
  ResolutionTarget,
  StorageItem,
  VideoRecord,
} from "./lib/types";
import { ComparisonViewer } from "./components/ComparisonViewer";
import { AsyncEnhancementViewer } from "./components/AsyncEnhancementViewer";
import { EnhancementWorkspace } from "./components/EnhancementWorkspace";
import { HistoryDrawer } from "./components/HistoryDrawer";
import { HardDriveIcon, HistoryIcon, ShieldIcon, SparkIcon, XIcon } from "./components/Icons";
import { PlaylistIcon } from "./components/Icons";
import { ProgressPanel } from "./components/ProgressPanel";
import { SourcePicker } from "./components/SourcePicker";
import { StorageDrawer } from "./components/StorageDrawer";
import { PlaylistDrawer } from "./components/PlaylistDrawer";

export function OhIcApp() {
  const [health, setHealth] = useState<Health | null>(null);
  const [video, setVideo] = useState<VideoRecord | null>(null);
  const [job, setJob] = useState<JobRecord | null>(null);
  const [comparison, setComparison] = useState<JobRecord | null>(null);
  const [history, setHistory] = useState<JobRecord[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [storage, setStorage] = useState<StorageItem[]>([]);
  const [storageOpen, setStorageOpen] = useState(false);
  const [storageBusy, setStorageBusy] = useState(false);
  const [playlists, setPlaylists] = useState<PlaylistRecord[]>([]);
  const [playlistsOpen, setPlaylistsOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refreshHistory = useCallback(async () => {
    try { setHistory(await api.history()); } catch { /* backend state is shown separately */ }
  }, []);

  const refreshStorage = useCallback(async () => {
    try { setStorage(await api.storage()); } catch { /* surfaced when the user performs cleanup */ }
  }, []);

  const refreshPlaylists = useCallback(async () => {
    try { setPlaylists(await api.playlists()); } catch { /* local engine status is surfaced separately */ }
  }, []);

  useEffect(() => {
    void api.health().then(setHealth).catch(() => setError("OhIc's local engine is not running. Start the backend, then refresh this page."));
    void api.history().then(setHistory).catch(() => undefined);
    void api.playlists().then(setPlaylists).catch(() => undefined);
  }, [refreshHistory]);

  const hasActivePlaylist = playlists.some((playlist) => ["queued", "running"].includes(playlist.status));
  useEffect(() => {
    if (!hasActivePlaylist && !playlistsOpen) return;
    const timer = window.setInterval(() => void refreshPlaylists(), 900);
    return () => window.clearInterval(timer);
  }, [hasActivePlaylist, playlistsOpen, refreshPlaylists]);

  useEffect(() => {
    if (!historyOpen) return;
    const timer = window.setInterval(() => void refreshHistory(), 900);
    return () => window.clearInterval(timer);
  }, [historyOpen, refreshHistory]);

  const activeJobId = job && !["complete", "failed", "cancelled"].includes(job.status) ? job.id : null;
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
      } else if (next.status === "failed" || next.status === "cancelled") {
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
        if (["complete", "failed", "cancelled"].includes(next.status)) events?.close();
      });
      events.onerror = () => {
        events?.close();
        if (disposed) return;
        void api.job(activeJobId).then((latest) => {
          applyUpdate(latest);
          if (!["complete", "failed", "cancelled"].includes(latest.status)) {
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
    timestamp: number,
    trimStart: number,
    trimEnd?: number,
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
        preview_timestamp: timestamp,
        trim_start: trimStart,
        trim_end: trimEnd,
      }));
    } catch (requestError) {
      setBusy(false);
      setError(requestError instanceof Error ? requestError.message : "Enhancement could not start.");
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

  const cancelFromHistory = async (selected: JobRecord) => {
    try {
      const cancelled = await api.cancelJob(selected.id);
      if (job?.id === cancelled.id) {
        setJob(cancelled);
        setBusy(false);
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

  const selectHistory = async (selected: JobRecord) => {
    try {
      const latest = await api.job(selected.id);
      const source = await api.video(latest.video_id);
      const active = !["complete", "failed", "cancelled"].includes(latest.status);
      setVideo(source);
      setJob(latest);
      setComparison(latest.status === "complete" && latest.kind !== "stream" ? latest : null);
      setBusy(active);
      setError(null);
      setHistoryOpen(false);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "This enhancement session is unavailable.");
    }
  };

  const reset = () => {
    setVideo(null);
    setJob(null);
    setComparison(null);
    setBusy(false);
  };

  if (job?.kind === "stream" && video) {
    return (
      <div className="app-shell">
        <AsyncEnhancementViewer
          job={job}
          video={video}
          onLeave={reset}
          onCancel={() => void cancel()}
          onHistory={() => { setHistoryOpen(true); void refreshHistory(); }}
        />
        <HistoryDrawer jobs={history} open={historyOpen} onClose={() => setHistoryOpen(false)} onSelect={(selected) => void selectHistory(selected)} onCancel={(selected) => void cancelFromHistory(selected)} />
        {error && <ErrorToast message={error} onClose={() => setError(null)} />}
      </div>
    );
  }

  if (comparison && video) {
    return (
      <div className="app-shell">
        <ComparisonViewer job={comparison} video={video} onBack={() => setComparison(null)} onAnother={reset} onPlaylists={() => { setPlaylistsOpen(true); void refreshPlaylists(); }} />
        <PlaylistDrawer playlists={playlists} open={playlistsOpen} onClose={() => setPlaylistsOpen(false)} onCancel={(selected) => void cancelPlaylist(selected)} onDelete={(selected) => void deletePlaylist(selected)} onOpenResult={(id) => void openPlaylistResult(id)} />
        {error && <ErrorToast message={error} onClose={() => setError(null)} />}
      </div>
    );
  }

  return (
    <div className="app-shell">
      <nav className="topbar">
        <button className="brand" onClick={reset} aria-label="OhIc home"><span className="brand-mark">O</span><span>OhIc</span></button>
        <div className="top-actions">
          {health && <span className={`hardware-pill ${health.status}`}><i /> {health.hardware.display_name}<small>{health.hardware.acceleration}</small></span>}
          <button onClick={() => { setPlaylistsOpen(true); setStorageOpen(false); setHistoryOpen(false); void refreshPlaylists(); }}><PlaylistIcon size={17} /> Playlists{hasActivePlaylist && <i className="nav-live" />}</button>
          <button onClick={() => { setStorageOpen(true); setPlaylistsOpen(false); setHistoryOpen(false); void refreshStorage(); }}><HardDriveIcon size={17} /> Storage</button>
          <button onClick={() => { setHistoryOpen(true); setPlaylistsOpen(false); setStorageOpen(false); void refreshHistory(); }}><HistoryIcon size={17} /> History</button>
        </div>
      </nav>

      {!video ? (
        <main className="landing">
          <div className="ambient ambient-one" />
          <div className="ambient ambient-two" />
          <section className="hero-copy">
            <span className="hero-kicker"><SparkIcon size={15} /> Local AI video restoration</span>
            <h1>Make old video<br /><em>look new again.</em></h1>
            <p>Restore clarity, lift resolution, and inspect every detail — privately, with the AI hardware already in your Mac.</p>
          </section>
          <SourcePicker onLoaded={(source) => { setVideo(source); setError(null); }} onPlaylistStarted={(started) => { setPlaylists((current) => [started, ...current.filter((item) => item.id !== started.id)]); setPlaylistsOpen(true); setError(null); }} onError={setError} />
          <div className="trust-row">
            <span><ShieldIcon size={16} /> Stays on your Mac</span>
            <span>Real-ESRGAN</span>
            <span>No account required</span>
          </div>
        </main>
      ) : (
        <div className="workspace-wrap">
          <div className="workspace-topline">
            <button onClick={reset}>← New video</button>
            <span><ShieldIcon size={14} /> Local session</span>
          </div>
          {job && !["complete", "failed", "cancelled"].includes(job.status) && <ProgressPanel job={job} onCancel={() => void cancel()} />}
          <EnhancementWorkspace key={`${video.id}:${job?.id ?? "new"}`} video={video} initialJob={job} busy={busy} onRun={(...args) => void runJob(...args)} />
        </div>
      )}

      <HistoryDrawer jobs={history} open={historyOpen} onClose={() => setHistoryOpen(false)} onSelect={(selected) => void selectHistory(selected)} onCancel={(selected) => void cancelFromHistory(selected)} />
      <StorageDrawer items={storage} open={storageOpen} busy={storageBusy} onClose={() => setStorageOpen(false)} onCleanup={(ids) => void cleanupStorage(ids)} />
      <PlaylistDrawer playlists={playlists} open={playlistsOpen} onClose={() => setPlaylistsOpen(false)} onCancel={(selected) => void cancelPlaylist(selected)} onDelete={(selected) => void deletePlaylist(selected)} onOpenResult={(id) => void openPlaylistResult(id)} />
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
