import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import Settings
from app.models.database import Database
from app.schemas.intelligence import (
    AnalysisCreateRequest,
    AnalysisStatus,
    ChatRequest,
    ProSetupState,
    SubjectIdentityRequest,
)
from app.schemas.video import SourceType, VideoRecord
from app.services.intelligence import IntelligenceManager
from app.services.pro import ProSetupService
from app.video.probe import probe_video


def make_video(tmp_path: Path) -> VideoRecord:
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=160x90:rate=6:duration=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(source),
        ],
        check=True,
    )
    return VideoRecord(
        id="intelligence-video",
        source_type=SourceType.UPLOAD,
        original_name="source.mp4",
        path=str(source),
        metadata=probe_video(source),
        targets=[],
        created_at=datetime.now(UTC),
        playback_url="/api/videos/intelligence-video/media",
    )


def wait_until_ready(setup: ProSetupService) -> None:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if setup.status().state == ProSetupState.READY:
            return
        time.sleep(0.02)
    raise AssertionError("test Pro setup did not finish")


def wait_for_analysis(manager: IntelligenceManager, analysis_id: str):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        analysis = manager.get(analysis_id)
        if analysis and analysis.status in {
            AnalysisStatus.READY,
            AnalysisStatus.FAILED,
            AnalysisStatus.CANCELLED,
        }:
            return analysis
        time.sleep(0.03)
    raise AssertionError("test analysis did not finish")


def test_pro_remains_absent_until_the_user_starts_setup(tmp_path: Path):
    settings = Settings(data_dir=tmp_path, pro_test_mode=True)
    database = Database(tmp_path / "ohic.sqlite3")
    setup = ProSetupService(settings, database)

    assert setup.status().state == ProSetupState.NOT_INSTALLED
    assert not (tmp_path / "intelligence" / "models" / ".test-ready").exists()

    assert setup.start_install().state == ProSetupState.INSTALLING
    wait_until_ready(setup)
    assert setup.runtime_available()


def test_ready_status_reports_repair_without_losing_existing_models(tmp_path: Path):
    settings = Settings(data_dir=tmp_path)
    database = Database(tmp_path / "ohic.sqlite3")
    setup = ProSetupService(settings, database)
    setup.qwen_path.mkdir(parents=True)
    setup.whisper_path.mkdir(parents=True)
    (setup.qwen_path / "config.json").write_text("{}")
    (setup.whisper_path / "config.json").write_text("{}")
    database.save_pro_status(
        setup._new_status().model_copy(
            update={
                "state": ProSetupState.READY,
                "progress": 100,
                "installed_at": datetime.now(UTC),
            }
        )
    )
    setup.runtime_available = lambda: False  # type: ignore[method-assign]

    status = setup.status()

    assert status.state == ProSetupState.ERROR
    assert status.stage == "Pro runtime needs repair"
    assert "downloaded models are still" in status.detail
    assert setup.model_files_available()


def test_repair_reuses_verified_model_files(tmp_path: Path):
    settings = Settings(data_dir=tmp_path)
    database = Database(tmp_path / "ohic.sqlite3")
    setup = ProSetupService(settings, database)
    setup.qwen_path.mkdir(parents=True)
    setup.whisper_path.mkdir(parents=True)
    (setup.qwen_path / "config.json").write_text("{}")
    (setup.whisper_path / "config.json").write_text("{}")
    database.save_pro_status(
        setup._new_status().model_copy(update={"installed_at": datetime.now(UTC)})
    )

    def unexpected_download(*_args, **_kwargs):
        raise AssertionError("existing model files should not be downloaded again")

    setup._download_snapshot = unexpected_download  # type: ignore[method-assign]
    setup._download_models()

    status = database.get_pro_status()
    assert status
    assert status.stage == "Using existing local models"
    assert status.progress == 92


def test_analysis_identity_memory_and_grounded_chat_persist(tmp_path: Path):
    settings = Settings(data_dir=tmp_path, pro_test_mode=True)
    database = Database(tmp_path / "ohic.sqlite3")
    setup = ProSetupService(settings, database)
    setup.start_install()
    wait_until_ready(setup)
    video = make_video(tmp_path)
    database.save_video(video)
    manager = IntelligenceManager(settings, database, setup)

    started = manager.create(AnalysisCreateRequest(video_id=video.id))
    analysis = wait_for_analysis(manager, started.id)
    assert analysis.status == AnalysisStatus.READY
    assert analysis.transcript_segments[0].text.startswith("A local test transcript")
    assert analysis.subtitle_url and manager.subtitle_path(analysis.id).exists()
    assert analysis.keyframes
    assert analysis.subjects

    tagged = manager.tag_subject(
        analysis.id,
        analysis.subjects[0].id,
        SubjectIdentityRequest(name="Alex"),
    )
    assert tagged.subjects[0].label == "Alex"
    assert database.list_identities()[0].name == "Alex"

    response = manager.chat(
        analysis.id,
        ChatRequest(question="Who is the person and what happens at 0:01?"),
    )
    assert response.message.role == "assistant"
    assert {call.name for call in response.message.tool_calls} >= {
        "video_metadata",
        "search_transcript",
        "list_subjects",
        "inspect_frames",
    }
    assert response.message.citations
    assert database.get_chat_session(response.session.id)


def test_optional_tracking_failure_keeps_transcript_and_visual_analysis(tmp_path: Path):
    settings = Settings(data_dir=tmp_path, pro_test_mode=True)
    database = Database(tmp_path / "ohic.sqlite3")
    setup = ProSetupService(settings, database)
    setup.start_install()
    wait_until_ready(setup)
    video = make_video(tmp_path)
    video.id = "degraded-tracker-video"
    database.save_video(video)
    manager = IntelligenceManager(settings, database, setup)

    def unavailable_tracker(*_args, **_kwargs):
        raise RuntimeError("test detector unavailable")

    manager._track_people = unavailable_tracker  # type: ignore[method-assign]
    started = manager.create(AnalysisCreateRequest(video_id=video.id))
    analysis = wait_for_analysis(manager, started.id)

    assert analysis.status == AnalysisStatus.READY
    assert analysis.transcript_segments
    assert analysis.keyframes
    assert analysis.warnings == ["Person tracking was skipped: test detector unavailable"]
