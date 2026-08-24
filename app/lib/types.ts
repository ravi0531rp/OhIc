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
  field_order: string;
  tracks: Array<{
    index: number;
    kind: string;
    codec: string;
    language?: string;
    title?: string;
    channels?: number;
  }>;
  chapters: number;
  title?: string;
};

export type VideoRecord = {
  id: string;
  source_type: "upload" | "youtube" | "camera";
  original_name: string;
  metadata: VideoMetadata;
  targets: ResolutionTarget[];
  created_at: string;
  playback_url: string;
  title?: string;
  thumbnail?: string;
  uploader?: string;
  diagnosis?: {
    verdict: string;
    confidence: string;
    issues: Array<{ code: string; severity: string; title: string; detail: string }>;
    recipe: {
      name: string;
      summary: string;
      target_height: number;
      preset: QualityPreset;
      model_id: string;
      deinterlace: "off" | "auto";
      reasons: string[];
    };
  };
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

export type EnhancementModel = {
  identifier: string;
  display_name: string;
  scale_factors: number[];
  supported_devices: string[];
  weights: string[];
  license: string;
  source_url: string;
  description: string;
  experimental: boolean;
  temporal: boolean;
  supports_stream: boolean;
  max_input_pixels?: number;
};

export type QualityPreset = "fast" | "balanced" | "maximum";
export type JobKind = "preview" | "full" | "stream";
export type JobStatus =
  | "queued"
  | "preparing"
  | "processing"
  | "encoding"
  | "paused"
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
  output_container: "mp4" | "mkv";
  track_policy: "compatible" | "preserve";
  scan_treatment: "auto" | "off" | "deinterlace" | "ivtc";
  resource_policy: "auto" | "conservative" | "performance";
  memory_limit_mb?: number;
  resource_allocation?: {
    policy: string;
    tile_size: number;
    temporal_window: number;
    max_parallel_jobs: number;
    available_memory_mb: number;
    memory_pressure: string;
    rationale: string;
  };
  scene_aware: boolean;
  scene_threshold: number;
  preserve_metadata: boolean;
  preserve_chapters: boolean;
  stream?: StreamState;
  checkpoint?: {
    version: number;
    source_fingerprint: string;
    settings_signature: string;
    segment_seconds: number;
    segments: Array<{
      index: number;
      start: number;
      end: number;
      status: "queued" | "processing" | "ready";
      progress: number;
      output_name: string;
      checksum?: string;
    }>;
  };
  recovered_after_restart: boolean;
  progress: JobProgress;
  created_at: string;
  started_at?: string;
  completed_at?: string;
  output_url?: string;
  original_preview_url?: string;
  error?: string;
  processing_seconds?: number;
};

export type HistoryEntry = {
  id: string;
  kind: "enhancement" | "camera" | "pro";
  reference_id: string;
  video_id: string;
  title: string;
  detail: string;
  status: string;
  progress: number;
  stage: string;
  created_at: string;
  updated_at: string;
  can_pause: boolean;
  can_cancel: boolean;
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

export type CameraSession = {
  id: string;
  status: "waiting" | "streaming" | "processing" | "complete" | "cancelled" | "failed";
  pairing_url: string;
  frame_count: number;
  created_at: string;
  video?: VideoRecord;
  error?: string;
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
  failure_code?: string;
  recovery_steps: string[];
};

export type YouTubeReliabilityReport = {
  status: "ready" | "degraded";
  yt_dlp_version: string;
  node_version?: string;
  cookies_configured: boolean;
  po_token_provider: boolean;
  checks: Array<{
    id: string;
    label: string;
    status: "ready" | "warning" | "optional";
    detail: string;
  }>;
  recommendations: string[];
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

export type PresetRecord = {
  id: string;
  name: string;
  target_height?: number;
  quality: QualityPreset;
  model_id: string;
  output_container: "mp4" | "mkv";
  track_policy: "compatible" | "preserve";
  scan_treatment: "auto" | "off" | "deinterlace" | "ivtc";
  resource_policy: "auto" | "conservative" | "performance";
  memory_limit_mb?: number;
  scene_aware: boolean;
  scene_threshold: number;
  created_at: string;
};

export type BatchRecord = {
  id: string;
  name: string;
  status: "queued" | "running" | "paused" | "complete" | "partial" | "failed" | "cancelled";
  progress: number;
  preset_id?: string;
  items: Array<{
    id: string;
    video_id: string;
    name: string;
    job_id?: string;
    status: string;
    progress: number;
    error?: string;
  }>;
  created_at: string;
  updated_at: string;
};

export type ComparisonRecord = {
  id: string;
  video_id: string;
  timestamp: number;
  status: "queued" | "running" | "complete" | "partial" | "failed" | "cancelled";
  progress: number;
  items: Array<{
    id: string;
    label: string;
    target_width: number;
    target_height: number;
    preset: QualityPreset;
    model_id: string;
    scan_treatment: "auto" | "off" | "deinterlace" | "ivtc";
    job_id?: string;
    status: string;
    progress: number;
    output_url?: string;
    error?: string;
  }>;
  created_at: string;
  updated_at: string;
};

export type ProStatus = {
  state: "not_installed" | "installing" | "ready" | "error";
  supported: boolean;
  platform: string;
  progress: number;
  stage: string;
  detail: string;
  qwen_model: string;
  whisper_model: string;
  hinglish_model: string;
  detector_model: string;
  estimated_download_bytes: number;
  installed_at?: string;
  error?: string;
};

export type TranscriptSegment = {
  id: string;
  start: number;
  end: number;
  text: string;
  words: Array<{ text: string; start: number; end: number; confidence?: number }>;
};

export type SubjectRecord = {
  id: string;
  label: string;
  kind: "person" | "object";
  color: string;
  identity_id?: string;
  appearances: Array<{
    start: number;
    end: number;
    box: { x: number; y: number; width: number; height: number };
    confidence: number;
  }>;
  thumbnail_url?: string;
};

export type VideoAnalysis = {
  id: string;
  video_id: string;
  video_name?: string;
  status: "queued" | "transcribing" | "tracking" | "indexing" | "ready" | "failed" | "cancelled";
  progress: number;
  stage: string;
  transcript_language?: string;
  transcription_engine: "whisper_multilingual" | "tara_hinglish";
  tracking_model: string;
  transcript_segments: TranscriptSegment[];
  subjects: SubjectRecord[];
  keyframes: Array<{ id: string; timestamp: number; image_url: string }>;
  subtitle_url?: string;
  created_at: string;
  updated_at: string;
  warnings: string[];
  error?: string;
};

export type IdentityRecord = {
  id: string;
  name: string;
  notes: string;
  color: string;
  reference_thumbnail_url?: string;
  created_at: string;
  updated_at: string;
};

export type EvidenceCitation = {
  start: number;
  end: number;
  label: string;
  kind: "transcript" | "subject" | "frame" | "metadata";
  image_url?: string;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: EvidenceCitation[];
  tool_calls: Array<{ name: string; arguments: Record<string, unknown>; result_count: number }>;
  created_at: string;
};

export type ChatSession = {
  id: string;
  analysis_id: string;
  messages: ChatMessage[];
  created_at: string;
  updated_at: string;
};
