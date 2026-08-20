import json
import sqlite3
import threading
from pathlib import Path

from app.schemas.batch import BatchRecord, PresetRecord
from app.schemas.comparison import ComparisonRecord
from app.schemas.job import JobRecord
from app.schemas.playlist import PlaylistRecord
from app.schemas.video import VideoRecord


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS videos (
                  id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jobs (
                  id TEXT PRIMARY KEY, video_id TEXT NOT NULL, status TEXT NOT NULL,
                  payload TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS jobs_created ON jobs(created_at DESC);
                CREATE INDEX IF NOT EXISTS jobs_video_id ON jobs(video_id);
                CREATE TABLE IF NOT EXISTS playlists (
                  id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS playlists_updated ON playlists(updated_at DESC);
                CREATE TABLE IF NOT EXISTS batches (
                  id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS batches_updated ON batches(updated_at DESC);
                CREATE TABLE IF NOT EXISTS presets (
                  id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS presets_created ON presets(created_at DESC);
                CREATE TABLE IF NOT EXISTS comparisons (
                  id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS comparisons_updated
                  ON comparisons(updated_at DESC);
                """
            )
            conn.execute("PRAGMA optimize")

    def save_video(self, video: VideoRecord) -> None:
        payload = video.model_dump(mode="json")
        payload["path"] = video.path
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO videos VALUES (?, ?, ?)",
                (video.id, json.dumps(payload), video.created_at.isoformat()),
            )

    def get_video(self, video_id: str) -> VideoRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT payload FROM videos WHERE id = ?", (video_id,)).fetchone()
        return VideoRecord.model_validate_json(row["payload"]) if row else None

    def list_videos(self) -> list[VideoRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT payload FROM videos ORDER BY created_at DESC").fetchall()
        return [VideoRecord.model_validate(json.loads(row["payload"])) for row in rows]

    def delete_video(self, video_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM videos WHERE id = ?", (video_id,))

    def save_job(self, job: JobRecord) -> None:
        payload = job.model_dump(mode="json")
        payload["output_path"] = job.output_path
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO jobs VALUES (?, ?, ?, ?, ?)",
                (
                    job.id,
                    job.video_id,
                    job.status,
                    json.dumps(payload),
                    job.created_at.isoformat(),
                ),
            )

    def get_job(self, job_id: str) -> JobRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT payload FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return JobRecord.model_validate_json(row["payload"]) if row else None

    def list_jobs(self, limit: int = 20) -> list[JobRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [JobRecord.model_validate(json.loads(row["payload"])) for row in rows]

    def jobs_for_video(self, video_id: str) -> list[JobRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM jobs WHERE video_id = ? ORDER BY created_at DESC",
                (video_id,),
            ).fetchall()
        return [JobRecord.model_validate(json.loads(row["payload"])) for row in rows]

    def delete_job(self, job_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))

    def save_playlist(self, playlist: PlaylistRecord) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO playlists VALUES (?, ?, ?, ?)",
                (
                    playlist.id,
                    playlist.model_dump_json(),
                    playlist.created_at.isoformat(),
                    playlist.updated_at.isoformat(),
                ),
            )

    def get_playlist(self, playlist_id: str) -> PlaylistRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM playlists WHERE id = ?", (playlist_id,)
            ).fetchone()
        return PlaylistRecord.model_validate_json(row["payload"]) if row else None

    def list_playlists(self, limit: int = 50) -> list[PlaylistRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM playlists ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [PlaylistRecord.model_validate_json(row["payload"]) for row in rows]

    def delete_playlist(self, playlist_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM playlists WHERE id = ?", (playlist_id,))

    def save_batch(self, batch: BatchRecord) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO batches VALUES (?, ?, ?, ?)",
                (
                    batch.id,
                    batch.model_dump_json(),
                    batch.created_at.isoformat(),
                    batch.updated_at.isoformat(),
                ),
            )

    def get_batch(self, batch_id: str) -> BatchRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM batches WHERE id = ?", (batch_id,)
            ).fetchone()
        return BatchRecord.model_validate_json(row["payload"]) if row else None

    def list_batches(self, limit: int = 50) -> list[BatchRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM batches ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [BatchRecord.model_validate_json(row["payload"]) for row in rows]

    def save_preset(self, preset: PresetRecord) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO presets VALUES (?, ?, ?)",
                (preset.id, preset.model_dump_json(), preset.created_at.isoformat()),
            )

    def get_preset(self, preset_id: str) -> PresetRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM presets WHERE id = ?", (preset_id,)
            ).fetchone()
        return PresetRecord.model_validate_json(row["payload"]) if row else None

    def list_presets(self) -> list[PresetRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT payload FROM presets ORDER BY created_at DESC").fetchall()
        return [PresetRecord.model_validate_json(row["payload"]) for row in rows]

    def delete_preset(self, preset_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM presets WHERE id = ?", (preset_id,))

    def save_comparison(self, comparison: ComparisonRecord) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO comparisons VALUES (?, ?, ?, ?)",
                (
                    comparison.id,
                    comparison.model_dump_json(),
                    comparison.created_at.isoformat(),
                    comparison.updated_at.isoformat(),
                ),
            )

    def get_comparison(self, comparison_id: str) -> ComparisonRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM comparisons WHERE id = ?", (comparison_id,)
            ).fetchone()
        return ComparisonRecord.model_validate_json(row["payload"]) if row else None

    def list_comparisons(self, limit: int = 50) -> list[ComparisonRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM comparisons ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [ComparisonRecord.model_validate_json(row["payload"]) for row in rows]
