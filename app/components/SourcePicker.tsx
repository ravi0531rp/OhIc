"use client";
/* yt-dlp provides third-party thumbnail URLs that bypass the local image optimizer. */
/* eslint-disable @next/next/no-img-element */

import { useEffect, useRef, useState } from "react";
import QRCode from "qrcode";
import { api, API_URL } from "../lib/api";
import type {
  PlaylistMetadata,
  PlaylistRecord,
  BatchRecord,
  CameraSession,
  PresetRecord,
  QualityPreset,
  VideoRecord,
  YouTubeDownloadRecord,
  YouTubeMetadata,
  YouTubeReliabilityReport,
} from "../lib/types";
import { FilmIcon, LinkIcon, ShieldIcon, UploadIcon } from "./Icons";

type Props = {
  onLoaded: (video: VideoRecord) => void;
  onCameraCheckpoint: (video: VideoRecord, destination: "enhancement" | "pro") => void;
  onPlaylistStarted: (playlist: PlaylistRecord) => void;
  onBatchStarted: (batch: BatchRecord) => void;
  onError: (message: string) => void;
};

export function SourcePicker({ onLoaded, onCameraCheckpoint, onPlaylistStarted, onBatchStarted, onError }: Props) {
  const [tab, setTab] = useState<"upload" | "youtube" | "camera">("upload");
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [url, setUrl] = useState("");
  const [youtubeMode, setYoutubeMode] = useState<"video" | "playlist">("video");
  const [youtube, setYoutube] = useState<YouTubeMetadata | null>(null);
  const [playlist, setPlaylist] = useState<PlaylistMetadata | null>(null);
  const [selectedPlaylistIds, setSelectedPlaylistIds] = useState<Set<string>>(new Set());
  const [playlistPreset, setPlaylistPreset] = useState<QualityPreset>("balanced");
  const [download, setDownload] = useState<YouTubeDownloadRecord | null>(null);
  const [reliability, setReliability] = useState<YouTubeReliabilityReport | null>(null);
  const [reliabilityOpen, setReliabilityOpen] = useState(false);
  const [presets, setPresets] = useState<PresetRecord[]>([]);
  const [batchPreset, setBatchPreset] = useState("balanced");
  const [camera, setCamera] = useState<CameraSession | null>(null);
  const [cameraQr, setCameraQr] = useState("");
  const [frameTick, setFrameTick] = useState(0);
  const [cameraCheckpointing, setCameraCheckpointing] = useState<"enhancement" | "pro" | null>(null);
  const [cameraRelayStarting, setCameraRelayStarting] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const eventsRef = useRef<EventSource | null>(null);

  useEffect(() => () => eventsRef.current?.close(), []);
  useEffect(() => { void api.presets().then(setPresets).catch(() => undefined); }, []);
  useEffect(() => {
    if (tab !== "youtube" || reliability) return;
    void api.youtubeReliability().then(setReliability).catch(() => undefined);
  }, [reliability, tab]);
  useEffect(() => {
    if (!camera || ["complete", "cancelled", "failed"].includes(camera.status)) return;
    const timer = window.setInterval(() => {
      void api.cameraSession(camera.id).then((next) => {
        setCamera(next);
        if (next.status === "streaming") setFrameTick(Date.now());
        if (next.status === "complete" && next.video) onLoaded(next.video);
        if (next.status === "failed") onError(next.error ?? "Phone camera capture failed.");
      }).catch(() => undefined);
    }, 500);
    return () => window.clearInterval(timer);
  }, [camera, onError, onLoaded]);

  const startCamera = async () => {
    setBusy(true);
    try {
      const session = await api.createCameraSession();
      setCamera(session);
      setCameraQr(await cameraQrCode(session.pairing_url));
    } catch (error) {
      onError(error instanceof Error ? error.message : "Phone camera pairing failed.");
    } finally {
      setBusy(false);
    }
  };

  const enableCameraRelay = async () => {
    if (!camera) return;
    const approved = window.confirm(
      "Enable secure phone streaming?\n\nOhIc will create a temporary Cloudflare HTTPS relay. The camera page becomes reachable from the internet, protected by its one-time random pairing token. The relay closes when OhIc stops.",
    );
    if (!approved) return;
    setCameraRelayStarting(true);
    try {
      const next = await api.enableCameraSecureRelay(camera.id);
      const qr = await cameraQrCode(next.pairing_url);
      setCamera(next);
      setCameraQr(qr);
    } catch (error) {
      onError(error instanceof Error ? error.message : "Secure phone streaming could not start.");
    } finally {
      setCameraRelayStarting(false);
    }
  };

  const cancelCamera = async () => {
    if (!camera) return;
    try {
      setCamera(await api.cancelCameraSession(camera.id));
    } catch (error) {
      onError(error instanceof Error ? error.message : "Phone camera pairing could not be cancelled.");
    }
  };

  const openCameraCheckpoint = async (destination: "enhancement" | "pro") => {
    if (!camera) return;
    setCameraCheckpointing(destination);
    try {
      onCameraCheckpoint(await api.checkpointCameraSession(camera.id), destination);
    } catch (error) {
      onError(error instanceof Error ? error.message : "The live camera buffer is not ready yet.");
    } finally {
      setCameraCheckpointing(null);
    }
  };

  const upload = async (selection?: FileList | File[]) => {
    const files = Array.from(selection ?? []);
    if (!files.length) return;
    setBusy(true);
    try {
      if (files.length === 1) {
        onLoaded(await api.upload(files[0]));
      } else {
        const videos = await api.uploadBatch(files);
        const savedPreset = presets.find((preset) => preset.id === batchPreset);
        onBatchStarted(await api.createBatch({
          video_ids: videos.map((item) => item.id),
          preset_id: savedPreset?.id,
          preset: savedPreset ? savedPreset.quality : batchPreset as QualityPreset,
        }));
      }
    } catch (error) {
      onError(error instanceof Error ? error.message : "Video upload failed.");
    } finally {
      setBusy(false);
    }
  };

  const inspect = async () => {
    setBusy(true);
    setYoutube(null);
    setPlaylist(null);
    setDownload(null);
    try {
      if (youtubeMode === "playlist") {
        const metadata = await api.inspectPlaylist(url);
        setPlaylist(metadata);
        setSelectedPlaylistIds(new Set(metadata.items.map((item) => item.youtube_id)));
      } else {
        setYoutube(await api.inspectYouTube(url));
      }
    } catch (error) {
      onError(error instanceof Error ? error.message : "YouTube inspection failed.");
    } finally {
      setBusy(false);
    }
  };

  const confirmPlaylist = async () => {
    if (!selectedPlaylistIds.size) return;
    setBusy(true);
    try {
      const started = await api.createPlaylist({
        url,
        selected_video_ids: [...selectedPlaylistIds],
        preset: playlistPreset,
      });
      onPlaylistStarted(started);
    } catch (error) {
      onError(error instanceof Error ? error.message : "Playlist processing could not start.");
    } finally {
      setBusy(false);
    }
  };

  const confirmYouTube = async () => {
    setBusy(true);
    try {
      const started = await api.downloadYouTube(url);
      setDownload(started);
      const events = new EventSource(`${API_URL}/api/videos/youtube/downloads/${started.id}/events`);
      eventsRef.current = events;
      events.addEventListener("progress", (event) => {
        const next = JSON.parse((event as MessageEvent).data) as YouTubeDownloadRecord;
        setDownload(next);
        if (next.status === "complete" && next.video) {
          events.close();
          eventsRef.current = null;
          setBusy(false);
          onLoaded(next.video);
        } else if (next.status === "failed") {
          events.close();
          eventsRef.current = null;
          setBusy(false);
          onError(next.error ?? "YouTube download failed.");
        } else if (next.status === "cancelled") {
          events.close();
          eventsRef.current = null;
          setBusy(false);
        }
      });
      events.onerror = async () => {
        events.close();
        eventsRef.current = null;
        try {
          const latest = await api.youtubeDownload(started.id);
          setDownload(latest);
          if (["queued", "downloading", "processing"].includes(latest.status)) {
            setBusy(false);
            onError("The progress connection was interrupted. Press Use this video to reconnect.");
          }
        } catch {
          setBusy(false);
          onError("Download progress was interrupted. Please try the import again.");
        }
      };
    } catch (error) {
      setBusy(false);
      onError(error instanceof Error ? error.message : "YouTube download failed.");
    }
  };

  const cancelYouTubeDownload = async () => {
    if (!download) return;
    try {
      const cancelled = await api.cancelYouTubeDownload(download.id);
      eventsRef.current?.close();
      eventsRef.current = null;
      setDownload(cancelled);
      setBusy(false);
    } catch (error) {
      onError(error instanceof Error ? error.message : "YouTube download could not be stopped.");
    }
  };

  return (
    <section className="source-card" aria-label="Choose video source">
      <div className="source-tabs" role="tablist">
        <button className={tab === "upload" ? "active" : ""} onClick={() => setTab("upload")} role="tab">
          <UploadIcon size={17} /> Upload video
        </button>
        <button className={tab === "youtube" ? "active" : ""} onClick={() => setTab("youtube")} role="tab">
          <LinkIcon size={17} /> YouTube
        </button>
        <button className={tab === "camera" ? "active" : ""} onClick={() => setTab("camera")} role="tab">
          <FilmIcon size={17} /> Phone camera
        </button>
      </div>

      {tab === "upload" ? (
        <>
          <button
            className={`dropzone ${dragging ? "dragging" : ""}`}
            disabled={busy}
            onClick={() => inputRef.current?.click()}
            onDragEnter={() => setDragging(true)}
            onDragLeave={() => setDragging(false)}
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => {
              event.preventDefault();
              setDragging(false);
              void upload(event.dataTransfer.files);
            }}
          >
            <input
              ref={inputRef}
              accept="video/mp4,video/quicktime,video/x-matroska,video/x-msvideo,video/webm,.m4v"
              hidden
              multiple
              type="file"
              onChange={(event) => void upload(event.target.files ?? undefined)}
            />
            <span className="drop-icon"><UploadIcon size={25} /></span>
            <strong>{busy ? "Preparing local queue…" : "Drop one or more videos here"}</strong>
            <span>{busy ? "Inspecting each source and creating durable jobs" : "One file opens setup; multiple files start a batch"}</span>
            <small>MP4, MOV, MKV, AVI or WebM · up to 100 files</small>
          </button>
          <label className="batch-upload-options">Batch preset<select disabled={busy} value={batchPreset} onChange={(event) => setBatchPreset(event.target.value)}><option value="balanced">Recommended targets · Balanced</option><option value="fast">Recommended targets · Fast</option><option value="maximum">Recommended targets · Maximum</option>{presets.map((preset) => <option value={preset.id} key={preset.id}>{preset.name}</option>)}</select></label>
        </>
      ) : tab === "camera" ? (
        <div className="camera-pairing-pane">
          {!camera ? <div className="camera-pairing-empty"><span className="drop-icon"><FilmIcon size={25} /></span><strong>Stream from a nearby phone</strong><p>Create a pairing, then enable the temporary secure relay for live browser capture. Native phone recording remains available over local Wi-Fi.</p><button disabled={busy} onClick={() => void startCamera()}>{busy ? "Opening pairing…" : "Create camera pairing"}</button></div> : <CameraPairingPanel camera={camera} cameraQr={cameraQr} frameTick={frameTick} checkpointing={cameraCheckpointing} relayStarting={cameraRelayStarting} onCancel={() => void cancelCamera()} onEnableRelay={() => void enableCameraRelay()} onCheckpoint={(destination) => void openCameraCheckpoint(destination)} />}
        </div>
      ) : (
        <div className="youtube-pane">
          {!youtube && !playlist ? (
            <>
              <div className="youtube-mode" role="group" aria-label="YouTube import type">
                <button className={youtubeMode === "video" ? "active" : ""} onClick={() => { setYoutubeMode("video"); setUrl(""); }}>Single video</button>
                <button className={youtubeMode === "playlist" ? "active" : ""} onClick={() => { setYoutubeMode("playlist"); setUrl(""); }}>Playlist</button>
              </div>
              <label htmlFor="youtube-url">YouTube {youtubeMode === "playlist" ? "playlist" : "video"} URL</label>
              <div className="url-row">
                <LinkIcon size={19} />
                <input
                  id="youtube-url"
                  value={url}
                  placeholder={youtubeMode === "playlist" ? "https://youtube.com/playlist?list=…" : "https://youtube.com/watch?v=…"}
                  onChange={(event) => setUrl(event.target.value)}
                  onKeyDown={(event) => event.key === "Enter" && void inspect()}
                />
                <button disabled={busy || !url.trim()} onClick={() => void inspect()}>
                  {busy ? "Checking…" : "Inspect"}
                </button>
              </div>
            </>
          ) : playlist ? (
            <div className="playlist-confirm">
              <div className="playlist-confirm-head">
                {playlist.thumbnail && <img alt="" src={playlist.thumbnail} />}
                <div><span className="eyebrow">Playlist found</span><strong>{playlist.title}</strong><p>{playlist.uploader ?? "YouTube"} · {playlist.item_count} available videos</p></div>
              </div>
              <div className="playlist-select-toolbar">
                <span>{selectedPlaylistIds.size} of {playlist.items.length} selected</span>
                <div><button onClick={() => setSelectedPlaylistIds(new Set(playlist.items.map((item) => item.youtube_id)))}>Select all</button><button onClick={() => setSelectedPlaylistIds(new Set())}>Clear</button></div>
              </div>
              <div className="playlist-pick-list">
                {playlist.items.map((item) => (
                  <label className={selectedPlaylistIds.has(item.youtube_id) ? "selected" : ""} key={item.youtube_id}>
                    <input
                      type="checkbox"
                      checked={selectedPlaylistIds.has(item.youtube_id)}
                      onChange={() => setSelectedPlaylistIds((current) => {
                        const next = new Set(current);
                        if (next.has(item.youtube_id)) next.delete(item.youtube_id);
                        else next.add(item.youtube_id);
                        return next;
                      })}
                    />
                    {item.thumbnail ? <img alt="" src={item.thumbnail} /> : <span className="playlist-thumb-fallback">{item.position}</span>}
                    <span><strong>{item.title}</strong><small>{item.duration ? formatDuration(item.duration) : "Duration unavailable"}</small></span>
                    <i>✓</i>
                  </label>
                ))}
              </div>
              <div className="playlist-launch">
                <label>Quality<select value={playlistPreset} onChange={(event) => setPlaylistPreset(event.target.value as QualityPreset)}><option value="fast">Fast</option><option value="balanced">Balanced</option><option value="maximum">Maximum</option></select></label>
                <button disabled={busy || !selectedPlaylistIds.size} onClick={() => void confirmPlaylist()}>{busy ? "Starting…" : `Enhance ${selectedPlaylistIds.size} selected`}</button>
              </div>
              <button className="playlist-back" disabled={busy} onClick={() => { setPlaylist(null); setSelectedPlaylistIds(new Set()); }}>← Choose another playlist</button>
            </div>
          ) : youtube ? (
            <div className={`youtube-confirm ${download ? "downloading" : ""}`}>
              {youtube.thumbnail && <img alt="" src={youtube.thumbnail} />}
              <div>
                <span className="eyebrow">Ready to import</span>
                <strong>{youtube.title}</strong>
                <p>
                  {youtube.uploader ?? "YouTube"}
                  {youtube.height ? ` · ${youtube.height}p` : ""}
                  {youtube.fps ? ` · ${youtube.fps} FPS` : ""}
                </p>
              </div>
              <button disabled={busy} onClick={() => void confirmYouTube()}>
                {busy ? "Downloading…" : "Use this video"}
              </button>
              {download && (
                <div className="youtube-download-progress" aria-live="polite">
                  <div><span>{download.progress.stage}</span><strong>{Math.round(download.progress.percent)}%</strong></div>
                  <div className="download-track"><i style={{ width: `${download.progress.percent}%` }} /></div>
                  <small>
                    {formatBytes(download.progress.downloaded_bytes)}
                    {download.progress.total_bytes ? ` of ${formatBytes(download.progress.total_bytes)}` : ""}
                    {download.progress.speed ? ` · ${formatBytes(download.progress.speed)}/s` : ""}
                    {download.progress.eta != null ? ` · ${formatDuration(download.progress.eta)} left` : ""}
                    {download.progress.attempt > 1 ? ` · retry ${download.progress.attempt}` : ""}
                  </small>
                  {["queued", "downloading", "processing"].includes(download.status) && (
                    <button className="download-cancel" onClick={() => void cancelYouTubeDownload()}>
                      Stop download
                    </button>
                  )}
                  {download.status === "cancelled" && <small className="download-stopped">Download stopped</small>}
                  {download.status === "failed" && (
                    <div className="youtube-recovery">
                      <strong>{download.error ?? "YouTube import failed."}</strong>
                      {download.recovery_steps.map((step) => <small key={step}>• {step}</small>)}
                      <button onClick={() => void confirmYouTube()}>Retry all recovery routes</button>
                    </div>
                  )}
                </div>
              )}
            </div>
          ) : null}
          {reliability && (
            <div className={`reliability-center ${reliabilityOpen ? "open" : ""}`}>
              <button className="reliability-summary" onClick={() => setReliabilityOpen((value) => !value)}>
                <span><i className={reliability.status} /> YouTube Reliability Center</span>
                <small>yt-dlp {reliability.yt_dlp_version} · {reliability.status === "ready" ? "core checks ready" : "action needed"}</small>
              </button>
              {reliabilityOpen && (
                <div className="reliability-details">
                  {reliability.checks.map((check) => (
                    <div key={check.id}><i className={check.status} /><span><strong>{check.label}</strong><small>{check.detail}</small></span></div>
                  ))}
                  {reliability.recommendations.map((item) => <p key={item}>{item}</p>)}
                  <button onClick={() => { setReliability(null); setReliabilityOpen(true); }}>Run checks again</button>
                </div>
              )}
            </div>
          )}
          <p className="legal-note"><ShieldIcon size={15} /> Only process videos you own or are permitted to use.</p>
        </div>
      )}
    </section>
  );
}

function CameraPairingPanel({
  camera,
  cameraQr,
  frameTick,
  checkpointing,
  relayStarting,
  onCancel,
  onEnableRelay,
  onCheckpoint,
}: {
  camera: CameraSession;
  cameraQr: string;
  frameTick: number;
  checkpointing: "enhancement" | "pro" | null;
  relayStarting: boolean;
  onCancel: () => void;
  onEnableRelay: () => void;
  onCheckpoint: (destination: "enhancement" | "pro") => void;
}) {
  const streaming = camera.status === "streaming";
  const secure = camera.relay_status === "ready" && camera.pairing_url.startsWith("https://");
  const hasBuffer = camera.segment_count > 0 || camera.frame_count >= 2;
  const statusLabel = camera.status === "waiting"
    ? "Waiting for phone"
    : streaming
      ? camera.stream_mode === "media" ? "Video + audio live" : "Camera preview live"
      : camera.status === "processing" ? "Creating video" : camera.status;
  const streamDetail = camera.segment_count > 0
    ? `${camera.segment_count} durable chunks · ${Math.round(camera.ready_seconds)}s · ${formatBytes(camera.stream_bytes)}`
    : `${camera.frame_count} preview frames received`;
  return (
    <div className="camera-pairing-live">
      <div className="camera-qr">{cameraQr && <img src={cameraQr} alt="QR code for phone camera pairing" />}</div>
      <div className="camera-pairing-copy" aria-live="polite">
        <span className="eyebrow">{statusLabel}</span>
        <h3>{camera.status === "waiting" ? "Scan with your phone" : streaming ? streamDetail : "Finishing the capture…"}</h3>
        <div className={`camera-relay-state ${secure ? "secure" : "local"}`}>
          <strong>{secure ? "Secure live streaming enabled" : "Local recording mode"}</strong>
          <span>{secure ? "This temporary HTTPS relay closes when OhIc stops." : "Live camera access is blocked on a plain HTTP QR. Enable the secure relay before scanning for direct streaming."}</span>
          {!secure && !["complete", "cancelled"].includes(camera.status) && <button disabled={relayStarting} onClick={onEnableRelay}>{relayStarting ? "Starting secure relay…" : camera.relay_status === "failed" ? "Retry secure relay" : "Enable secure live streaming"}</button>}
        </div>
        <p>Each ordered chunk is stored before it is acknowledged. Create an immutable checkpoint at any time, then enhance it or analyze it in Pro while the phone keeps streaming.</p>
        <code>{camera.pairing_url}</code>
        {streaming && camera.frame_count > 0 && <img className="camera-live-preview" src={`${API_URL}/api/camera/sessions/${camera.id}/frame?t=${frameTick}`} alt="Live phone camera preview" />}
        {streaming && hasBuffer && (
          <div className="camera-live-actions">
            <button disabled={checkpointing !== null} onClick={() => onCheckpoint("enhancement")}>{checkpointing === "enhancement" ? "Freezing buffer…" : "Enhance current buffer"}</button>
            <button disabled={checkpointing !== null} onClick={() => onCheckpoint("pro")}>{checkpointing === "pro" ? "Freezing buffer…" : "Analyze current buffer"}</button>
          </div>
        )}
        {!['complete', 'cancelled', 'failed'].includes(camera.status) && <button className="camera-cancel" onClick={onCancel}>Cancel pairing</button>}
      </div>
    </div>
  );
}

function cameraQrCode(pairingUrl: string): Promise<string> {
  return QRCode.toDataURL(pairingUrl, {
    width: 240,
    margin: 1,
    color: { dark: "#111510", light: "#efffc4" },
  });
}

function formatDuration(value: number): string {
  const minutes = Math.floor(value / 60);
  const seconds = Math.floor(value % 60);
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function formatBytes(value: number): string {
  if (!value) return "Starting…";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  return `${(value / 1024 ** index).toFixed(index > 1 ? 1 : 0)} ${units[index]}`;
}
