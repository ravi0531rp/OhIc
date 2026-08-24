import math
import subprocess
import sys
import threading
import time
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace

import numpy as np

from app.core.config import Settings
from app.models.database import Database
from app.schemas.intelligence import (
    AnalysisCreateRequest,
    AnalysisStatus,
    BoundingBox,
    ChatRequest,
    ProSetupState,
    SubjectAppearance,
    SubjectIdentityRequest,
    VideoAnalysis,
)
from app.schemas.video import SourceType, VideoRecord
from app.services.intelligence import CancelledError, IntelligenceManager
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
    for path in (setup.qwen_path, setup.whisper_path, setup.hinglish_path):
        path.mkdir(parents=True, exist_ok=True)
        (path / "config.json").write_text("{}")
    for path in (setup.transcript_embedding_path, setup.visual_embedding_path):
        path.mkdir(parents=True, exist_ok=True)
        (path / "modules.json").write_text("[]")
    clip_model = setup.visual_embedding_path / "0_CLIPModel"
    clip_model.mkdir(parents=True, exist_ok=True)
    (clip_model / "config.json").write_text("{}")
    setup.person_reid_path.mkdir(parents=True, exist_ok=True)
    (setup.person_reid_path / "osnet_x0_25_msmt17.onnx").write_bytes(b"test")
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


def test_completed_install_self_heals_a_stale_incomplete_status(tmp_path: Path):
    settings = Settings(data_dir=tmp_path)
    database = Database(tmp_path / "ohic.sqlite3")
    setup = ProSetupService(settings, database)
    write_pro_model_markers(setup)
    database.save_pro_status(
        setup._new_status().model_copy(
            update={
                "state": ProSetupState.ERROR,
                "progress": 0,
                "installed_at": datetime.now(UTC),
                "error": "The Pro installation is incomplete.",
            }
        )
    )
    setup.runtime_available = lambda: True  # type: ignore[method-assign]

    status = setup.status()

    assert status.state == ProSetupState.READY
    assert status.progress == 100
    assert status.error is None


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

    follow_up = manager.chat(
        analysis.id,
        ChatRequest(question="Search again and find another example."),
    )
    assert follow_up.session.id == response.session.id
    assert len(follow_up.session.messages) == 4
    follow_up_tools = {call.name for call in follow_up.message.tool_calls}
    assert "search_transcript_embeddings" in follow_up_tools
    assert "search_video_embeddings" in follow_up_tools
    transcript_search = next(
        call
        for call in follow_up.message.tool_calls
        if call.name == "search_transcript_embeddings"
    )
    assert "Who is the person" in transcript_search.arguments["query"]
    assert "Search again" in transcript_search.arguments["query"]


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


def test_hinglish_transcription_passes_custom_prompt_in_generation_config(
    tmp_path: Path, monkeypatch
):
    settings = Settings(data_dir=tmp_path)
    database = Database(tmp_path / "ohic.sqlite3")
    setup = ProSetupService(settings, database)
    setup.hinglish_path.mkdir(parents=True, exist_ok=True)
    manager = IntelligenceManager(settings, database, setup)
    source = tmp_path / "speech.mp4"
    source.write_bytes(b"test")

    tokenizer = SimpleNamespace(
        convert_tokens_to_ids=lambda token: {
            "<|hi|>": 1,
            "<|mixedcode|>": 2,
            "<|transcribe|>": 3,
            "<|notimestamps|>": 4,
        }[token],
        decode=lambda *_args, **_kwargs: "namaste hello",
    )

    class Features:
        def to(self, *_args):
            return self

    class FakeProcessor:
        def __init__(self):
            self.tokenizer = tokenizer

        def __call__(self, *_args, **_kwargs):
            return SimpleNamespace(input_features=Features())

    processor = FakeProcessor()
    original_config = SimpleNamespace(language="hi", task="transcribe")
    generated_with = {}

    class FakeModel:
        generation_config = original_config

        def to(self, *_args):
            return self

        def generate(self, **kwargs):
            generated_with.update(kwargs)
            return [[10, 11]]

    fake_model = FakeModel()
    transformers = ModuleType("transformers")
    transformers.WhisperProcessor = SimpleNamespace(from_pretrained=lambda *_args: processor)
    transformers.WhisperForConditionalGeneration = SimpleNamespace(
        from_pretrained=lambda *_args, **_kwargs: fake_model
    )
    torch = ModuleType("torch")
    torch.cuda = SimpleNamespace(is_available=lambda: False)
    torch.backends = SimpleNamespace(mps=SimpleNamespace(is_available=lambda: False))
    torch.float16 = "float16"
    torch.float32 = "float32"
    torch.inference_mode = nullcontext
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "transformers", transformers)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0, stdout=np.zeros(16_000, dtype=np.float32).tobytes()
        ),
    )

    language, segments = manager._transcribe_hinglish(source)

    assert language == "hi-en"
    assert segments[0].text == "namaste hello"
    assert "forced_decoder_ids" not in generated_with
    assert "max_new_tokens" not in generated_with
    prompt_config = generated_with["generation_config"]
    assert prompt_config.forced_decoder_ids == [(1, 1), (2, 2), (3, 3), (4, 4)]
    assert prompt_config.language is None
    assert prompt_config.task is None
    assert original_config.language == "hi"
    assert original_config.task == "transcribe"


def test_tracker_stops_at_frame_count_even_if_decoder_keeps_returning_frames(
    tmp_path: Path, monkeypatch
):
    settings = Settings(data_dir=tmp_path)
    database = Database(tmp_path / "ohic.sqlite3")
    setup = ProSetupService(settings, database)
    detector_dir = setup.models_dir / "rfdetr"
    detector_dir.mkdir(parents=True, exist_ok=True)
    (detector_dir / "rf-detr-small.pth").write_bytes(b"test")
    manager = IntelligenceManager(settings, database, setup)
    video = make_video(tmp_path)
    analysis = manager.database.get_analysis("bounded-tracker")
    if analysis is None:
        analysis = VideoAnalysis(id="bounded-tracker", video_id=video.id)
        database.save_analysis(analysis)

    empty_detections = SimpleNamespace(
        xyxy=np.empty((0, 4)),
        class_id=np.empty(0),
        tracker_id=np.empty(0),
        confidence=np.empty(0),
    )

    class Capture:
        read_count = 0
        released = False

        def isOpened(self):
            return True

        def set(self, *_args):
            return True

        def read(self):
            self.read_count += 1
            return True, np.zeros((90, 160, 3), dtype=np.uint8)

        def get(self, prop):
            return {1: 24, 2: 247, 3: 160, 4: 90}.get(prop, 0)

        def release(self):
            self.released = True

    capture = Capture()
    cv2 = ModuleType("cv2")
    cv2.CAP_PROP_FPS = 1
    cv2.CAP_PROP_FRAME_COUNT = 2
    cv2.CAP_PROP_FRAME_WIDTH = 3
    cv2.CAP_PROP_FRAME_HEIGHT = 4
    cv2.CAP_PROP_POS_FRAMES = 5
    cv2.VideoCapture = lambda *_args: capture
    supervision = ModuleType("supervision")
    supervision.ByteTrack = lambda **_kwargs: SimpleNamespace(
        update_with_detections=lambda detections: detections
    )
    rfdetr = ModuleType("rfdetr")
    rfdetr.RFDETRSmall = lambda **_kwargs: SimpleNamespace(
        predict=lambda *_args, **_kwargs: empty_detections
    )
    assets = ModuleType("rfdetr.assets")
    coco = ModuleType("rfdetr.assets.coco_classes")
    coco.COCO_CLASSES = []
    monkeypatch.setitem(sys.modules, "cv2", cv2)
    monkeypatch.setitem(sys.modules, "supervision", supervision)
    monkeypatch.setitem(sys.modules, "rfdetr", rfdetr)
    monkeypatch.setitem(sys.modules, "rfdetr.assets", assets)
    monkeypatch.setitem(sys.modules, "rfdetr.assets.coco_classes", coco)

    subjects = manager._track_people(
        analysis, video, threading.Event(), include_people=False, include_objects=True
    )

    assert subjects == []
    assert capture.read_count == 42
    assert capture.released
    saved = database.get_analysis(analysis.id)
    assert saved
    assert saved.progress <= 80
    assert int(saved.stage.split("· ")[1].split("%")[0]) <= 100


def test_person_reid_survives_motion_and_keeps_simultaneous_people_separate(
    tmp_path: Path
):
    settings = Settings(data_dir=tmp_path)
    database = Database(tmp_path / "ohic.sqlite3")
    setup = ProSetupService(settings, database)
    manager = IntelligenceManager(settings, database, setup)
    manager._write_subject_thumbnail = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    tracks = []
    subjects_dir = tmp_path / "subjects"

    manager._associate_people(
        tracks,
        [{"box": (0.05, 0.05, 0.25, 0.75), "confidence": 0.9}],
        np.asarray([[1.0, 0.0]], dtype=np.float32),
        0,
        1,
        frame,
        subjects_dir,
    )
    manager._associate_people(
        tracks,
        [{"box": (0.65, 0.1, 0.25, 0.75), "confidence": 0.88}],
        np.asarray([[0.75, math.sqrt(1 - 0.75**2)]], dtype=np.float32),
        30,
        1,
        frame,
        subjects_dir,
    )
    assert len(tracks) == 1
    assert len(tracks[0]["appearances"]) == 2

    heads = [
        {"box": (0.1, 0.82, 0.08, 0.1), "confidence": 0.8},
        {"box": (0.72, 0.82, 0.08, 0.1), "confidence": 0.8},
    ]
    head_embeddings = np.asarray([[0.0, 1.0], [0.0, 1.0]], dtype=np.float32)
    manager._associate_people(
        tracks, heads, head_embeddings, 31, 1, frame, subjects_dir
    )
    manager._associate_people(
        tracks, list(reversed(heads)), head_embeddings, 32, 1, frame, subjects_dir
    )

    assert len(tracks) == 3
    assert sorted(len(track["appearances"]) for track in tracks) == [2, 2, 2]


def test_person_tracklet_consolidation_merges_pose_modes_but_not_concurrent_people(
    tmp_path: Path
):
    settings = Settings(data_dir=tmp_path)
    database = Database(tmp_path / "ohic.sqlite3")
    setup = ProSetupService(settings, database)
    manager = IntelligenceManager(settings, database, setup)

    def track(identifier: str, start: float, descriptor: list[float], x: float):
        appearance = SubjectAppearance(
            start=start,
            end=start + 1,
            box=BoundingBox(x=x, y=0.1, width=0.2, height=0.7),
            confidence=0.9,
        )
        return {
            "id": identifier,
            "label": "Person",
            "kind": "person",
            "appearances": [appearance],
            "descriptor": np.asarray(descriptor, dtype=np.float32),
            "descriptor_samples": 5,
            "last_box": (x, 0.1, 0.2, 0.7),
            "last_time": start,
            "best_area": 0.14,
        }

    consolidated = manager._consolidate_person_tracks(
        [
            track("front", 0, [1.0, 0.0], 0.1),
            track("side", 10, [0.7, math.sqrt(1 - 0.7**2)], 0.7),
            track("other", 0, [0.8, 0.6], 0.7),
        ]
    )

    assert len(consolidated) == 2
    merged = next(item for item in consolidated if len(item["appearances"]) == 2)
    assert {item.start for item in merged["appearances"]} == {0, 10}


def test_cancel_during_tracking_stays_cancelled(tmp_path: Path):
    settings = Settings(data_dir=tmp_path, pro_test_mode=True)
    database = Database(tmp_path / "ohic.sqlite3")
    setup = ProSetupService(settings, database)
    video = make_video(tmp_path)
    database.save_video(video)
    manager = IntelligenceManager(settings, database, setup)

    analysis = VideoAnalysis(video_id=video.id)
    database.save_analysis(analysis)

    def cancel_tracker(*_args, **_kwargs):
        manager.cancel(analysis.id)
        raise CancelledError

    manager._track_people = cancel_tracker  # type: ignore[method-assign]
    manager._run(analysis.id, AnalysisCreateRequest(video_id=video.id), video, threading.Event())

    saved = database.get_analysis(analysis.id)
    assert saved
    assert saved.status == AnalysisStatus.CANCELLED
    assert saved.stage == "Cancelled"
