export type ResolutionTarget = {
  width: number;
  height: number;
  label: string;
  recommended: boolean;
  note?: string;
};

export type VideoMetadata = {
  width: number;
  height: number;
  resolution_label: string;
  aspect_ratio: string;
  fps: number;
  frame_count?: number;
  duration: number;
  video_codec: string;
  audio_codec?: string;
  bitrate?: number;
  file_size: number;
  pixel_format?: string;
  dynamic_range: string;
};

export type VideoRecord = {
  id: string;
  source_type: "upload" | "youtube";
  original_name: string;
  metadata: VideoMetadata;
  targets: ResolutionTarget[];
  created_at: string;
  playback_url: string;
  title?: string;
  thumbnail?: string;
  uploader?: string;
};

export type HardwareInfo = {
  device: string;
  display_name: string;
  acceleration: string;
};

export type Health = {
  status: "ok" | "degraded";
  ffmpeg: { available: boolean; message?: string };
  ffprobe: { available: boolean; message?: string };
  hardware: HardwareInfo;
};

export type QualityPreset = "fast" | "balanced" | "maximum";
export type JobKind = "preview" | "full" | "stream";
export type JobStatus =
  | "queued"
  | "preparing"
  | "processing"
  | "encoding"
  | "complete"
  | "failed"
  | "cancelled";

export type JobProgress = {
  stage: string;
  percent: number;
  frames_done: number;
  frames_total?: number;
  processing_fps?: number;
  elapsed_seconds: number;
  eta_seconds?: number;
  detail?: string;
};

export type StreamChunk = {
  index: number;
  start: number;
  end: number;
  status: "queued" | "processing" | "ready" | "failed" | "cancelled";
  progress: number;
  playback_url?: string;
};

export type StreamState = {
  chunk_duration: number;
  total_chunks: number;
  ready_chunks: number;
  buffered_seconds: number;
  chunks: StreamChunk[];
};

export type JobRecord = {
  id: string;
  video_id: string;
  kind: JobKind;
  status: JobStatus;
  model_id: string;
  preset: QualityPreset;
  target_width: number;
  target_height: number;
  preview_timestamp: number;
  trim_start: number;
  trim_end?: number;
  playlist_id?: string;
  stream?: StreamState;
  progress: JobProgress;
  created_at: string;
  started_at?: string;
  completed_at?: string;
  output_url?: string;
  original_preview_url?: string;
  error?: string;
  processing_seconds?: number;
};

export type YouTubeMetadata = {
  url: string;
  title: string;
  thumbnail?: string;
  duration?: number;
  uploader?: string;
  width?: number;
  height?: number;
  fps?: number;
  notice: string;
};

export type YouTubeDownloadRecord = {
  id: string;
  url: string;
  status: "queued" | "downloading" | "processing" | "complete" | "failed" | "cancelled";
  progress: {
    stage: string;
    percent: number;
    downloaded_bytes: number;
    total_bytes?: number;
    speed?: number;
    eta?: number;
    attempt: number;
  };
  created_at: string;
  video?: VideoRecord;
  error?: string;
};

export type StorageItem = {
  id: string;
  kind: "upload" | "download" | "output";
  name: string;
  size: number;
  created_at: string;
  detail: string;
  active: boolean;
};

export type StorageCleanupResult = {
  removed_ids: string[];
  bytes_freed: number;
};

export type PlaylistInspectItem = {
  youtube_id: string;
  url: string;
  title: string;
  thumbnail?: string;
  duration?: number;
  uploader?: string;
  position: number;
};

export type PlaylistMetadata = {
  url: string;
  title: string;
  thumbnail?: string;
  uploader?: string;
  item_count: number;
  items: PlaylistInspectItem[];
  notice: string;
};

export type PlaylistItemStatus =
  | "queued"
  | "downloading"
  | "enhancing"
  | "complete"
  | "failed"
  | "cancelled"
  | "removed";

export type PlaylistRecord = {
  id: string;
  url: string;
  title: string;
  thumbnail?: string;
  uploader?: string;
  preset: QualityPreset;
  status: "queued" | "running" | "complete" | "partial" | "failed" | "cancelled";
  progress: number;
  items: Array<PlaylistInspectItem & {
    id: string;
    status: PlaylistItemStatus;
    stage: string;
    progress: number;
    video_id?: string;
    job_id?: string;
    error?: string;
  }>;
  created_at: string;
  updated_at: string;
};
