import subprocess
import sys
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


def write_pro_model_markers(setup: ProSetupService) -> None:
    for path in (
        setup.qwen_path,
        setup.whisper_path,
        setup.hinglish_path,
        setup.transcript_embedding_path,
        setup.visual_embedding_path,
    ):
        path.mkdir(parents=True, exist_ok=True)
        (path / "config.json").write_text("{}")
    detection = setup.models_dir / "rfdetr"
    detection.mkdir(parents=True, exist_ok=True)
    (detection / "rf-detr-small.pth").write_bytes(b"test")


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


def test_optional_runtime_uses_writable_application_data(tmp_path: Path):
    settings = Settings(data_dir=tmp_path, pro_test_mode=True)
    database = Database(tmp_path / "ohic.sqlite3")
    setup = ProSetupService(settings, database)

    assert setup.runtime_dir == tmp_path / "intelligence" / "runtime-packages"
    assert setup.runtime_dir.is_dir()
    assert str(setup.runtime_dir) in sys.path
    assert setup._runtime_pythonpath({"PYTHONPATH": "/bundled/base"}).split(":") == [
        str(setup.runtime_dir),
        "/bundled/base",
    ]


def test_ready_status_reports_repair_without_losing_existing_models(tmp_path: Path):
    settings = Settings(data_dir=tmp_path)
    database = Database(tmp_path / "ohic.sqlite3")
    setup = ProSetupService(settings, database)
    write_pro_model_markers(setup)
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
    write_pro_model_markers(setup)
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
    assert {subject.kind for subject in analysis.subjects} == {"person", "object"}

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
        "search_transcript_embeddings",
        "list_subjects",
        "search_video_embeddings",
    }
    assert response.message.citations
    assert database.get_chat_session(response.session.id)

    transcript_only = manager.chat(
        analysis.id,
        ChatRequest(
            question="What was said?",
            retrieval_sources={"transcript"},
        ),
    )
    transcript_tools = {call.name for call in transcript_only.message.tool_calls}
    assert "search_transcript_embeddings" in transcript_tools
    assert "search_video_embeddings" not in transcript_tools

    visual_only = manager.chat(
        analysis.id,
        ChatRequest(
            question="What is visible?",
            retrieval_sources={"visual"},
        ),
    )
    visual_tools = {call.name for call in visual_only.message.tool_calls}
    assert "search_video_embeddings" in visual_tools
    assert "search_transcript_embeddings" not in visual_tools


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
    assert analysis.warnings == ["Subject tracking was skipped: test detector unavailable"]


def test_hinglish_recipe_uses_code_switch_model_and_can_skip_objects(tmp_path: Path):
    settings = Settings(data_dir=tmp_path, pro_test_mode=True)
    database = Database(tmp_path / "ohic.sqlite3")
    setup = ProSetupService(settings, database)
    setup.start_install()
    wait_until_ready(setup)
    video = make_video(tmp_path)
    database.save_video(video)
    manager = IntelligenceManager(settings, database, setup)

    started = manager.create(
        AnalysisCreateRequest(
            video_id=video.id,
            transcription_engine="tara_hinglish",
            track_objects=False,
        )
    )
    analysis = wait_for_analysis(manager, started.id)

    assert analysis.status == AnalysisStatus.READY
    assert analysis.transcript_language == "hi-en"
    assert analysis.transcription_engine == "tara_hinglish"
    assert "Hinglish" in analysis.transcript_segments[0].text
    assert analysis.subjects and {item.kind for item in analysis.subjects} == {"person"}
