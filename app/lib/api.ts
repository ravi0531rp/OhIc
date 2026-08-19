import type {
  Health,
  JobKind,
  JobRecord,
  PlaylistMetadata,
  PlaylistRecord,
  QualityPreset,
  VideoRecord,
  StorageCleanupResult,
  StorageItem,
  YouTubeDownloadRecord,
  YouTubeMetadata,
} from "./types";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, init);
  if (!response.ok) {
    let message = "Something went wrong.";
    try {
      const payload = (await response.json()) as { detail?: string };
      message = payload.detail ?? message;
    } catch {
      message = response.statusText || message;
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<Health>("/api/health"),
  history: () => request<JobRecord[]>("/api/jobs"),
  job: (id: string) => request<JobRecord>(`/api/jobs/${id}`),
  video: (id: string) => request<VideoRecord>(`/api/videos/${id}`),
  upload: (file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<VideoRecord>("/api/videos/upload", { method: "POST", body });
  },
  inspectYouTube: (url: string) =>
    request<YouTubeMetadata>("/api/videos/youtube/inspect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    }),
  inspectPlaylist: (url: string) =>
    request<PlaylistMetadata>("/api/playlists/inspect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    }),
  playlists: () => request<PlaylistRecord[]>("/api/playlists"),
  createPlaylist: (input: {
    url: string;
    selected_video_ids: string[];
    preset: QualityPreset;
  }) =>
    request<PlaylistRecord>("/api/playlists", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }),
  cancelPlaylist: (id: string) =>
    request<PlaylistRecord>(`/api/playlists/${id}/cancel`, { method: "POST" }),
  deletePlaylist: async (id: string) => {
    const response = await fetch(`${API_URL}/api/playlists/${id}`, { method: "DELETE" });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({ detail: "Playlist removal failed." })) as { detail?: string };
      throw new Error(payload.detail ?? "Playlist removal failed.");
    }
  },
  downloadYouTube: (url: string) =>
    request<YouTubeDownloadRecord>("/api/videos/youtube/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    }),
  youtubeDownload: (id: string) =>
    request<YouTubeDownloadRecord>(`/api/videos/youtube/downloads/${id}`),
  cancelYouTubeDownload: (id: string) =>
    request<YouTubeDownloadRecord>(`/api/videos/youtube/downloads/${id}/cancel`, {
      method: "POST",
    }),
  storage: () => request<StorageItem[]>("/api/storage/items"),
  cleanupStorage: (ids: string[]) =>
    request<StorageCleanupResult>("/api/storage/cleanup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids }),
    }),
  createJob: (input: {
    video_id: string;
    kind: JobKind;
    target_width: number;
    target_height: number;
    preset: QualityPreset;
    preview_timestamp: number;
    trim_start?: number;
    trim_end?: number;
  }) =>
    request<JobRecord>("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...input, model_id: "realesrgan-x2plus" }),
    }),
  cancelJob: (id: string) =>
    request<JobRecord>(`/api/jobs/${id}/cancel`, { method: "POST" }),
};

export function mediaUrl(path?: string): string {
  return path ? `${API_URL}${path}` : "";
}
