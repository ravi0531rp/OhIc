import type {
  EnhancementModel,
  BatchRecord,
  ComparisonRecord,
  Health,
  JobKind,
  JobRecord,
  PlaylistMetadata,
  PlaylistRecord,
  PresetRecord,
  QualityPreset,
  VideoRecord,
  StorageCleanupResult,
  StorageItem,
  YouTubeDownloadRecord,
  YouTubeMetadata,
  YouTubeReliabilityReport,
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
  models: () => request<EnhancementModel[]>("/api/models"),
  history: () => request<JobRecord[]>("/api/jobs"),
  job: (id: string) => request<JobRecord>(`/api/jobs/${id}`),
  video: (id: string) => request<VideoRecord>(`/api/videos/${id}`),
  upload: (file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<VideoRecord>("/api/videos/upload", { method: "POST", body });
  },
  uploadBatch: (files: File[]) => {
    const body = new FormData();
    files.forEach((file) => body.append("files", file));
    return request<VideoRecord[]>("/api/videos/upload/batch", { method: "POST", body });
  },
  batches: () => request<BatchRecord[]>("/api/batches"),
  createBatch: (input: { video_ids: string[]; preset_id?: string; preset: QualityPreset }) =>
    request<BatchRecord>("/api/batches", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }),
  pauseBatch: (id: string) => request<BatchRecord>(`/api/batches/${id}/pause`, { method: "POST" }),
  resumeBatch: (id: string) => request<BatchRecord>(`/api/batches/${id}/resume`, { method: "POST" }),
  cancelBatch: (id: string) => request<BatchRecord>(`/api/batches/${id}/cancel`, { method: "POST" }),
  createComparison: (input: {
    video_id: string;
    timestamp: number;
    variants: Array<{
      label: string;
      target_width: number;
      target_height: number;
      preset: QualityPreset;
      model_id: string;
      scan_treatment: "auto" | "off" | "deinterlace" | "ivtc";
    }>;
  }) => request<ComparisonRecord>("/api/comparisons", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  }),
  comparison: (id: string) => request<ComparisonRecord>(`/api/comparisons/${id}`),
  cancelComparison: (id: string) => request<ComparisonRecord>(`/api/comparisons/${id}/cancel`, { method: "POST" }),
  presets: () => request<PresetRecord[]>("/api/presets"),
  createPreset: (input: Omit<PresetRecord, "id" | "created_at">) =>
    request<PresetRecord>("/api/presets", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }),
  inspectYouTube: (url: string) =>
    request<YouTubeMetadata>("/api/videos/youtube/inspect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    }),
  youtubeReliability: () =>
    request<YouTubeReliabilityReport>("/api/videos/youtube/reliability"),
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
    model_id: string;
    preview_timestamp: number;
    trim_start?: number;
    trim_end?: number;
    output_container?: "mp4" | "mkv";
    track_policy?: "compatible" | "preserve";
    preserve_metadata?: boolean;
    preserve_chapters?: boolean;
    scan_treatment?: "auto" | "off" | "deinterlace" | "ivtc";
    resource_policy?: "auto" | "conservative" | "performance";
    memory_limit_mb?: number;
    scene_aware?: boolean;
    scene_threshold?: number;
  }) =>
    request<JobRecord>("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }),
  cancelJob: (id: string) =>
    request<JobRecord>(`/api/jobs/${id}/cancel`, { method: "POST" }),
  pauseJob: (id: string) =>
    request<JobRecord>(`/api/jobs/${id}/pause`, { method: "POST" }),
  resumeJob: (id: string) =>
    request<JobRecord>(`/api/jobs/${id}/resume`, { method: "POST" }),
};

export function mediaUrl(path?: string): string {
  return path ? `${API_URL}${path}` : "";
}
