"use client";
/* yt-dlp provides third-party thumbnail URLs that bypass the local image optimizer. */
/* eslint-disable @next/next/no-img-element */

import { useEffect, useRef, useState } from "react";
import { api, API_URL } from "../lib/api";
import type {
  PlaylistMetadata,
  PlaylistRecord,
  QualityPreset,
  VideoRecord,
  YouTubeDownloadRecord,
  YouTubeMetadata,
} from "../lib/types";
import { LinkIcon, ShieldIcon, UploadIcon } from "./Icons";

type Props = {
  onLoaded: (video: VideoRecord) => void;
  onPlaylistStarted: (playlist: PlaylistRecord) => void;
  onError: (message: string) => void;
};

export function SourcePicker({ onLoaded, onPlaylistStarted, onError }: Props) {
  const [tab, setTab] = useState<"upload" | "youtube">("upload");
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [url, setUrl] = useState("");
  const [youtubeMode, setYoutubeMode] = useState<"video" | "playlist">("video");
  const [youtube, setYoutube] = useState<YouTubeMetadata | null>(null);
  const [playlist, setPlaylist] = useState<PlaylistMetadata | null>(null);
  const [selectedPlaylistIds, setSelectedPlaylistIds] = useState<Set<string>>(new Set());
  const [playlistPreset, setPlaylistPreset] = useState<QualityPreset>("balanced");
  const [download, setDownload] = useState<YouTubeDownloadRecord | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const eventsRef = useRef<EventSource | null>(null);

  useEffect(() => () => eventsRef.current?.close(), []);

  const upload = async (file?: File) => {
    if (!file) return;
    setBusy(true);
    try {
      onLoaded(await api.upload(file));
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
      </div>

      {tab === "upload" ? (
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
            void upload(event.dataTransfer.files[0]);
          }}
        >
          <input
            ref={inputRef}
            accept="video/mp4,video/quicktime,video/x-matroska,video/x-msvideo,video/webm,.m4v"
            hidden
            type="file"
            onChange={(event) => void upload(event.target.files?.[0])}
          />
          <span className="drop-icon"><UploadIcon size={25} /></span>
          <strong>{busy ? "Inspecting video…" : "Drop your video here"}</strong>
          <span>{busy ? "Reading resolution, frame rate and codec" : "or click to browse your Mac"}</span>
          <small>MP4, MOV, MKV, AVI or WebM · up to 20 GB</small>
        </button>
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
                </div>
              )}
            </div>
          ) : null}
          <p className="legal-note"><ShieldIcon size={15} /> Only process videos you own or are permitted to use.</p>
        </div>
      )}
      <div className="local-proof"><ShieldIcon size={16} /> Processed locally on your computer <span>No uploads. No tracking.</span></div>
    </section>
  );
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
