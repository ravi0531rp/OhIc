from __future__ import annotations

import json
import math
import re
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import numpy as np

from app.core.config import Settings
from app.models.database import Database
from app.schemas.intelligence import (
    AnalysisCreateRequest,
    AnalysisStatus,
    BoundingBox,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ChatSession,
    EvidenceCitation,
    IdentityCreateRequest,
    IdentityRecord,
    KeyframeRecord,
    SubjectAppearance,
    SubjectIdentityRequest,
    SubjectRecord,
    ToolExecution,
    TranscriptSegment,
    TranscriptWord,
    VideoAnalysis,
)
from app.schemas.video import VideoRecord
from app.services.pro import ProSetupService

SUBJECT_COLORS = ("#c7ff47", "#52d9ff", "#ff8bc7", "#ffd166", "#b68cff", "#65f2ad")
TERMINAL_ANALYSIS_STATES = {
    AnalysisStatus.READY,
    AnalysisStatus.FAILED,
    AnalysisStatus.CANCELLED,
}


class QwenVideoRuntime:
    """Lazy, single-copy VLM runtime. No model is imported before Pro is installed."""

    def __init__(self, setup: ProSetupService):
        self.setup = setup
        self._lock = threading.RLock()
        self._model = None
        self._processor = None
        self._config = None

    def answer(self, prompt: str, images: list[Path]) -> str:
        if self.setup.settings.pro_test_mode:
            return (
                "The local evidence shows the relevant moment described in the cited "
                "transcript and frames."
            )
        with self._lock:
            return (
                self._answer_mlx(prompt, images)
                if self.setup.is_apple_silicon
                else self._answer_transformers(prompt, images)
            )

    def unload(self) -> None:
        with self._lock:
            self._model = None
            self._processor = None
            self._config = None
            if self.setup.is_apple_silicon:
                try:
                    import mlx.core as mx

                    mx.clear_cache()
                except ImportError:
                    pass

    def _answer_mlx(self, prompt: str, images: list[Path]) -> str:
        from mlx_vlm import generate, load
        from mlx_vlm.prompt_utils import apply_chat_template
        from mlx_vlm.utils import load_config

        if self._model is None:
            self._model, self._processor = load(str(self.setup.qwen_path))
            self._config = load_config(str(self.setup.qwen_path))
        formatted = apply_chat_template(
            self._processor,
            self._config,
            prompt,
            num_images=len(images),
        )
        image_input: str | list[str] | None = [str(path) for path in images]
        if len(image_input) == 1:
            image_input = image_input[0]
        result = generate(
            self._model,
            self._processor,
            formatted,
            image_input,
            max_tokens=600,
            temperature=0.1,
            verbose=False,
        )
        text = getattr(result, "text", result)
        return str(text).strip()

    def _answer_transformers(self, prompt: str, images: list[Path]) -> str:
        import torch
        from PIL import Image
        from transformers import AutoModelForImageTextToText, AutoProcessor

        if self._model is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
            dtype = torch.float16 if device == "cuda" else torch.float32
            self._model = AutoModelForImageTextToText.from_pretrained(
                str(self.setup.qwen_path), torch_dtype=dtype, device_map=device
            )
            self._processor = AutoProcessor.from_pretrained(str(self.setup.qwen_path))
        content = [{"type": "image", "image": Image.open(path)} for path in images]
        content.append({"type": "text", "text": prompt})
        messages = [{"role": "user", "content": content}]
        text = self._processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self._processor(
            text=[text], images=[item["image"] for item in content[:-1]], return_tensors="pt"
        )
        inputs = {key: value.to(self._model.device) for key, value in inputs.items()}
        generated = self._model.generate(**inputs, max_new_tokens=600, do_sample=False)
        trimmed = generated[:, inputs["input_ids"].shape[1] :]
        return self._processor.batch_decode(trimmed, skip_special_tokens=True)[0].strip()


class IntelligenceManager:
    def __init__(self, settings: Settings, database: Database, setup: ProSetupService):
        self.settings = settings
        self.database = database
        self.setup = setup
        self.root = settings.data_dir / "intelligence"
        self.root.mkdir(parents=True, exist_ok=True)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ohic-intelligence")
        self._cancel: dict[str, threading.Event] = {}
        self._runtime = QwenVideoRuntime(setup)
        self._transcript_embedder = None
        self._visual_embedder = None

    def recover_interrupted(self) -> int:
        recovered = 0
        for analysis in self.database.list_analyses(500):
            if analysis.status not in TERMINAL_ANALYSIS_STATES:
                analysis.status = AnalysisStatus.FAILED
                analysis.stage = "Analysis was interrupted"
                analysis.error = (
                    "OhIc closed during analysis. Start it again; existing files are reusable."
                )
                analysis.updated_at = datetime.now(UTC)
                self.database.save_analysis(analysis)
                recovered += 1
        return recovered

    def create(self, request: AnalysisCreateRequest) -> VideoAnalysis:
        self.setup.require_ready()
        video = self.database.get_video(request.video_id)
        if not video:
            raise ValueError("Video not found.")
        for previous in self.database.analyses_for_video(video.id):
            if previous.status not in {AnalysisStatus.FAILED, AnalysisStatus.CANCELLED}:
                return previous
        analysis = VideoAnalysis(
            video_id=video.id,
            video_name=video.title or video.original_name,
            transcription_engine=request.transcription_engine,
        )
        self.database.save_analysis(analysis)
        event = threading.Event()
        self._cancel[analysis.id] = event
        self._executor.submit(self._run, analysis.id, request, video, event)
        return analysis

    def get(self, analysis_id: str) -> VideoAnalysis | None:
        return self.database.get_analysis(analysis_id)

    def for_video(self, video_id: str) -> VideoAnalysis | None:
        records = self.database.analyses_for_video(video_id)
        return records[0] if records else None

    def list(self, limit: int = 50) -> list[VideoAnalysis]:
        return self.database.list_analyses(limit)

    def cancel(self, analysis_id: str) -> VideoAnalysis:
        analysis = self.database.get_analysis(analysis_id)
        if not analysis:
            raise ValueError("Analysis not found.")
        if analysis.status in TERMINAL_ANALYSIS_STATES:
            return analysis
        self._cancel.setdefault(analysis_id, threading.Event()).set()
        analysis.status = AnalysisStatus.CANCELLED
        analysis.stage = "Cancelled"
        analysis.updated_at = datetime.now(UTC)
        self.database.save_analysis(analysis)
        return analysis

    def create_identity(self, request: IdentityCreateRequest) -> IdentityRecord:
        identity = IdentityRecord(name=request.name.strip(), notes=request.notes.strip())
        self.database.save_identity(identity)
        return identity

    def tag_subject(
        self, analysis_id: str, subject_id: str, request: SubjectIdentityRequest
    ) -> VideoAnalysis:
        analysis = self.database.get_analysis(analysis_id)
        if not analysis:
            raise ValueError("Analysis not found.")
        subject = next((item for item in analysis.subjects if item.id == subject_id), None)
        if not subject:
            raise ValueError("Subject not found.")
        identity = self.database.get_identity(request.identity_id) if request.identity_id else None
        if request.identity_id and not identity:
            raise ValueError("Identity not found.")
        if not identity and request.name:
            identity = self.create_identity(
                IdentityCreateRequest(
                    name=request.name, notes="Identified from a tracked video subject"
                )
            )
        if not identity:
            subject.identity_id = None
            subject.label = f"Person {analysis.subjects.index(subject) + 1}"
        else:
            subject.identity_id = identity.id
            subject.label = identity.name
            if not identity.reference_thumbnail_url and subject.thumbnail_url:
                identity.reference_thumbnail_url = subject.thumbnail_url
                identity.updated_at = datetime.now(UTC)
                self.database.save_identity(identity)
        analysis.updated_at = datetime.now(UTC)
        self.database.save_analysis(analysis)
        return analysis

    def chat(self, analysis_id: str, request: ChatRequest) -> ChatResponse:
        self.setup.require_ready()
        analysis = self.database.get_analysis(analysis_id)
        if not analysis or analysis.status != AnalysisStatus.READY:
            raise ValueError("Finish analyzing this video before asking questions.")
        session = (
            self.database.get_chat_session(request.session_id)
            if request.session_id
            else self.database.latest_chat_for_analysis(analysis_id)
        )
        if session and session.analysis_id != analysis_id:
            raise ValueError("This chat belongs to another video.")
        session = session or ChatSession(analysis_id=analysis_id)
        history = session.messages[-8:]
        user_message = ChatMessage(role="user", content=request.question.strip())
        retrieval_query = self._contextual_query(request.question, history)
        tools, citations, image_paths, evidence = self._collect_evidence(
            analysis, request, retrieval_query
        )
        prompt = self._answer_prompt(analysis, request.question, evidence, history)
        answer = self._runtime.answer(prompt, image_paths)
        if not answer:
            answer = "I could not find enough local evidence to answer that confidently."
        assistant = ChatMessage(
            role="assistant", content=answer, citations=citations, tool_calls=tools
        )
        session.messages.extend([user_message, assistant])
        session.updated_at = datetime.now(UTC)
        self.database.save_chat_session(session)
        return ChatResponse(session=session, message=assistant)

    def unload_chat_model(self) -> None:
        self._runtime.unload()

    def _run(
        self,
        analysis_id: str,
        request: AnalysisCreateRequest,
        video: VideoRecord,
        cancel: threading.Event,
    ) -> None:
        try:
            analysis = self._set_progress(
                analysis_id, AnalysisStatus.TRANSCRIBING, 4, "Preparing audio and captions"
            )
            if request.transcribe:
                try:
                    language, segments = self._transcribe(Path(video.path), request)
                    analysis.transcript_language = language
                    analysis.transcript_segments = segments
                    analysis.subtitle_url = f"/api/pro/analyses/{analysis.id}/subtitles.vtt"
                    self._save(analysis)
                    self._write_vtt(analysis)
                except CancelledError:
                    raise
                except Exception as exc:
                    detail = str(exc) or type(exc).__name__
                    analysis.warnings.append(f"Transcription was skipped: {detail}")
                    analysis.subtitle_url = f"/api/pro/analyses/{analysis.id}/subtitles.vtt"
                    self._save(analysis)
                    self._write_vtt(analysis)
            self._raise_if_cancelled(cancel)
            analysis = self._set_progress(
                analysis_id, AnalysisStatus.TRACKING, 45, "Detecting and tracking subjects"
            )
            if request.track_people or request.track_objects:
                try:
                    subjects = self._track_people(
                        analysis,
                        video,
                        cancel,
                        include_people=request.track_people,
                        include_objects=request.track_objects,
                    )
                    analysis = self.database.get_analysis(analysis_id) or analysis
                    analysis.subjects = subjects
                    self._save(analysis)
                except CancelledError:
                    raise
                except Exception as exc:
                    analysis = self.database.get_analysis(analysis_id) or analysis
                    detail = str(exc) or type(exc).__name__
                    analysis.warnings.append(f"Subject tracking was skipped: {detail}")
                    self._save(analysis)
            self._raise_if_cancelled(cancel)
            analysis = self._set_progress(
                analysis_id, AnalysisStatus.INDEXING, 82, "Building timestamp evidence"
            )
            analysis.keyframes = self._extract_keyframes(analysis, video, cancel)
            self._build_embedding_index(analysis)
            self._raise_if_cancelled(cancel)
            analysis.status = AnalysisStatus.READY
            analysis.progress = 100
            analysis.stage = "Ready to explore"
            analysis.error = None
            self._save(analysis)
        except CancelledError:
            pass
        except Exception as exc:
            analysis = self.database.get_analysis(analysis_id)
            if analysis and analysis.status != AnalysisStatus.CANCELLED:
                analysis.status = AnalysisStatus.FAILED
                analysis.stage = "Analysis needs attention"
                analysis.error = str(exc)
                self._save(analysis)
        finally:
            self._cancel.pop(analysis_id, None)

    def _transcribe(
        self, video_path: Path, request: AnalysisCreateRequest
    ) -> tuple[str | None, list[TranscriptSegment]]:
        if self.settings.pro_test_mode:
            language = (
                "hi-en"
                if request.transcription_engine == "tara_hinglish"
                else (request.transcript_language or "en")
            )
            text = (
                "यह local Hinglish test transcript video ke liye hai."
                if request.transcription_engine == "tara_hinglish"
                else "A local test transcript for this video."
            )
            return language, [TranscriptSegment(start=0, end=2.5, text=text)]
        if request.transcription_engine == "tara_hinglish":
            return self._transcribe_hinglish(video_path)
        if self.setup.is_apple_silicon:
            import mlx_whisper

            result = mlx_whisper.transcribe(
                str(video_path),
                path_or_hf_repo=str(self.setup.whisper_path),
                word_timestamps=True,
                condition_on_previous_text=False,
                language=request.transcript_language,
                verbose=False,
            )
            return result.get("language"), self._parse_segments(result.get("segments", []))
        from faster_whisper import WhisperModel

        model = WhisperModel(str(self.setup.whisper_path), device="auto", compute_type="auto")
        iterable, info = model.transcribe(
            str(video_path),
            word_timestamps=True,
            vad_filter=True,
            condition_on_previous_text=False,
            language=request.transcript_language,
        )
        segments = []
        for item in iterable:
            words = [
                TranscriptWord(
                    text=word.word.strip(),
                    start=float(word.start),
                    end=float(word.end),
                    confidence=float(word.probability),
                )
                for word in (item.words or [])
            ]
            segments.append(
                TranscriptSegment(
                    start=float(item.start),
                    end=float(item.end),
                    text=item.text.strip(),
                    words=words,
                )
            )
        return info.language, segments

    def _transcribe_hinglish(self, video_path: Path) -> tuple[str, list[TranscriptSegment]]:
        import torch
        from transformers import WhisperForConditionalGeneration, WhisperProcessor

        completed = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(video_path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-f",
                "f32le",
                "pipe:1",
            ],
            capture_output=True,
            timeout=max(120, math.ceil(video_path.stat().st_size / 100_000)),
            check=False,
        )
        if completed.returncode:
            raise RuntimeError("audio could not be prepared for Hinglish transcription")
        audio = np.frombuffer(completed.stdout, dtype=np.float32)
        processor = WhisperProcessor.from_pretrained(str(self.setup.hinglish_path))
        device = (
            "cuda"
            if torch.cuda.is_available()
            else ("mps" if torch.backends.mps.is_available() else "cpu")
        )
        dtype = torch.float16 if device != "cpu" else torch.float32
        model = WhisperForConditionalGeneration.from_pretrained(
            str(self.setup.hinglish_path), torch_dtype=dtype
        ).to(device)
        tokenizer = processor.tokenizer
        prefix = [
            (1, tokenizer.convert_tokens_to_ids("<|hi|>")),
            (2, tokenizer.convert_tokens_to_ids("<|mixedcode|>")),
            (3, tokenizer.convert_tokens_to_ids("<|transcribe|>")),
            (4, tokenizer.convert_tokens_to_ids("<|notimestamps|>")),
        ]
        generation_config = self._hinglish_generation_config(model, prefix)
        window_samples = 30 * 16_000
        segments: list[TranscriptSegment] = []
        for offset in range(0, len(audio), window_samples):
            chunk = audio[offset : offset + window_samples]
            if not len(chunk):
                continue
            features = processor(
                chunk, sampling_rate=16_000, return_tensors="pt"
            ).input_features.to(device, dtype)
            with torch.inference_mode():
                output = model.generate(
                    input_features=features,
                    generation_config=generation_config,
                )
            text = tokenizer.decode(output[0], skip_special_tokens=True).strip()
            if text:
                start = offset / 16_000
                end = min(len(audio), offset + len(chunk)) / 16_000
                segments.append(TranscriptSegment(start=start, end=end, text=text))
        del model
        return "hi-en", segments

    @staticmethod
    def _hinglish_generation_config(model, prefix: list[tuple[int, int]]):
        generation_config = deepcopy(model.generation_config)
        generation_config.language = None
        generation_config.task = None
        generation_config.forced_decoder_ids = prefix
        return generation_config

    def _parse_segments(self, values: list[dict]) -> list[TranscriptSegment]:
        segments: list[TranscriptSegment] = []
        for value in values:
            if (
                not str(value.get("text", "")).strip()
                or float(value.get("no_speech_prob", 0)) > 0.75
            ):
                continue
            words = [
                TranscriptWord(
                    text=str(word.get("word", "")).strip(),
                    start=float(word.get("start", value.get("start", 0))),
                    end=float(word.get("end", value.get("end", 0))),
                    confidence=word.get("probability"),
                )
                for word in value.get("words", [])
                if str(word.get("word", "")).strip()
            ]
            segments.append(
                TranscriptSegment(
                    start=float(value.get("start", 0)),
                    end=float(value.get("end", 0)),
                    text=str(value["text"]).strip(),
                    words=words,
                )
            )
        return segments

    def _track_people(
        self,
        analysis: VideoAnalysis,
        video: VideoRecord,
        cancel: threading.Event,
        include_people: bool = True,
        include_objects: bool = True,
    ) -> list[SubjectRecord]:
        if self.settings.pro_test_mode:
            subjects = [
                SubjectRecord(
                    label="Person 1",
                    appearances=[
                        SubjectAppearance(
                            start=0,
                            end=min(2.5, video.metadata.duration),
                            box=BoundingBox(x=0.32, y=0.12, width=0.28, height=0.78),
                            confidence=0.9,
                        )
                    ],
                )
            ]
            if include_objects:
                subjects.append(
                    SubjectRecord(
                        label="Backpack 1",
                        kind="object",
                        color=SUBJECT_COLORS[1],
                        appearances=[
                            SubjectAppearance(
                                start=0,
                                end=min(2.5, video.metadata.duration),
                                box=BoundingBox(x=0.08, y=0.42, width=0.2, height=0.35),
                                confidence=0.84,
                            )
                        ],
                    )
                )
            return (
                subjects if include_people else [item for item in subjects if item.kind == "object"]
            )

        import cv2
        import supervision as sv
        from rfdetr import RFDETRSmall
        from rfdetr.assets.coco_classes import COCO_CLASSES

        detection_root = self.setup.models_dir / "rfdetr"
        weights = detection_root / "rf-detr-small.pth"
        if not weights.exists():
            raise RuntimeError("RF-DETR weights are missing; repair Pro setup")
        model = RFDETRSmall(pretrain_weights=str(weights))
        tracker = sv.ByteTrack(frame_rate=max(1, round(min(10, max(video.metadata.fps, 1)))))
        capture = cv2.VideoCapture(str(video.path))
        fps = capture.get(cv2.CAP_PROP_FPS) or max(video.metadata.fps, 1)
        duration = max(video.metadata.duration, 0.1)
        reported_frames = capture.get(cv2.CAP_PROP_FRAME_COUNT)
        frame_count = max(
            1,
            round(reported_frames)
            if math.isfinite(reported_frames) and reported_frames > 0
            else (video.metadata.frame_count or math.ceil(duration * fps)),
        )
        sample_seconds = max(0.25, duration / 900)
        step = max(1, round(sample_seconds * fps))
        tracks: dict[tuple[int, int], dict] = {}
        frame_index = 0
        sample_index = 0
        analysis_dir = self._analysis_dir(analysis.id)
        (analysis_dir / "subjects").mkdir(parents=True, exist_ok=True)
        try:
            while capture.isOpened() and frame_index < frame_count:
                self._raise_if_cancelled(cancel)
                capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
                ok, frame = capture.read()
                if not ok:
                    break
                timestamp = min(duration, frame_index / fps)
                detections = model.predict(frame, threshold=0.3)
                detections = tracker.update_with_detections(detections)
                for index, xyxy in enumerate(detections.xyxy):
                    class_id = int(detections.class_id[index])
                    try:
                        label = str(COCO_CLASSES[class_id])
                    except (IndexError, KeyError, TypeError):
                        label = f"Object {class_id}"
                    is_person = label.lower() == "person"
                    if (is_person and not include_people) or (
                        not is_person and not include_objects
                    ):
                        continue
                    tracker_id = int(detections.tracker_id[index])
                    key = (class_id, tracker_id)
                    x1, y1, x2, y2 = (float(value) for value in xyxy)
                    width = max(1.0, capture.get(cv2.CAP_PROP_FRAME_WIDTH))
                    height = max(1.0, capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    confidence = (
                        float(detections.confidence[index])
                        if detections.confidence is not None
                        else 0.5
                    )
                    if key not in tracks:
                        subject_id = uuid4().hex
                        tracks[key] = {
                            "id": subject_id,
                            "label": label,
                            "kind": "person" if is_person else "object",
                            "appearances": [],
                        }
                        self._write_subject_thumbnail(
                            frame,
                            (
                                x1 / width,
                                y1 / height,
                                (x2 - x1) / width,
                                (y2 - y1) / height,
                            ),
                            analysis_dir / "subjects" / f"{subject_id}.jpg",
                        )
                    tracks[key]["appearances"].append(
                        SubjectAppearance(
                            start=timestamp,
                            end=min(duration, timestamp + sample_seconds),
                            box=BoundingBox(
                                x=max(0, min(1, x1 / width)),
                                y=max(0, min(1, y1 / height)),
                                width=max(0.0001, min(1, (x2 - x1) / width)),
                                height=max(0.0001, min(1, (y2 - y1) / height)),
                            ),
                            confidence=max(0, min(1, confidence)),
                        )
                    )
                sample_index += 1
                if sample_index % 12 == 0:
                    scanned = min(1.0, (frame_index + 1) / frame_count)
                    current = self.database.get_analysis(analysis.id)
                    if current:
                        current.progress = 45 + scanned * 35
                        current.stage = f"RF-DETR + ByteTrack · {scanned:.0%} scanned"
                        self._save(current)
                frame_index += step
        finally:
            capture.release()
        counters: dict[str, int] = {}
        subjects = []
        for track in tracks.values():
            if len(track["appearances"]) < 2:
                continue
            counters[track["label"]] = counters.get(track["label"], 0) + 1
            subjects.append(
                SubjectRecord(
                    id=track["id"],
                    label=f"{track['label'].title()} {counters[track['label']]}",
                    kind=track["kind"],
                    color=SUBJECT_COLORS[len(subjects) % len(SUBJECT_COLORS)],
                    appearances=track["appearances"],
                    thumbnail_url=(
                        f"/api/pro/analyses/{analysis.id}/subjects/{track['id']}/thumbnail"
                    ),
                )
            )
        return subjects

    def _associate_detections(
        self,
        tracks: list[dict],
        detections: list[tuple[float, float, float, float, float]],
        timestamp: float,
        sample_seconds: float,
        frame,
        analysis_dir: Path,
    ) -> None:
        assigned: set[int] = set()
        for detection in detections:
            box = detection[:4]
            candidates = [
                (self._iou(box, track["last_box"]), index)
                for index, track in enumerate(tracks)
                if timestamp - track["last_time"] <= sample_seconds * 3
            ]
            score, match = max(candidates, default=(0.0, -1))
            if score < 0.18 or match in assigned:
                track_id = uuid4().hex
                track = {
                    "id": track_id,
                    "last_box": box,
                    "last_time": timestamp,
                    "appearances": [],
                }
                tracks.append(track)
                match = len(tracks) - 1
                self._write_subject_thumbnail(
                    frame, box, analysis_dir / "subjects" / f"{track_id}.jpg"
                )
            track = tracks[match]
            track["last_box"] = box
            track["last_time"] = timestamp
            track["appearances"].append(
                SubjectAppearance(
                    start=timestamp,
                    end=timestamp + sample_seconds,
                    box=BoundingBox(x=box[0], y=box[1], width=box[2], height=box[3]),
                    confidence=min(1, max(0, detection[4])),
                )
            )
            assigned.add(match)

    def _write_subject_thumbnail(self, frame, box: tuple[float, ...], path: Path) -> None:
        import cv2

        height, width = frame.shape[:2]
        x, y, w, h = box
        left, top = max(0, int(x * width)), max(0, int(y * height))
        right, bottom = min(width, int((x + w) * width)), min(height, int((y + h) * height))
        if right > left and bottom > top:
            cv2.imwrite(str(path), frame[top:bottom, left:right])

    def _extract_keyframes(
        self, analysis: VideoAnalysis, video: VideoRecord, cancel: threading.Event
    ) -> list[KeyframeRecord]:
        duration = max(video.metadata.duration, 0.1)
        count = min(18, max(3, math.ceil(duration / 120)))
        directory = self._analysis_dir(analysis.id) / "frames"
        directory.mkdir(parents=True, exist_ok=True)
        records = []
        for index in range(count):
            self._raise_if_cancelled(cancel)
            timestamp = min(duration - 0.01, duration * (index + 0.5) / count)
            destination = directory / f"{index:04d}.jpg"
            completed = subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-ss",
                    f"{timestamp:.3f}",
                    "-i",
                    str(video.path),
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale='min(960,iw)':-2",
                    "-y",
                    str(destination),
                ],
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )
            if completed.returncode == 0 and destination.exists():
                records.append(
                    KeyframeRecord(
                        timestamp=timestamp,
                        image_url=f"/api/pro/analyses/{analysis.id}/frames/{index}",
                    )
                )
        return records

    def _build_embedding_index(self, analysis: VideoAnalysis) -> None:
        """Persist compact transcript and visual vectors for source-selectable local RAG."""
        if self.settings.pro_test_mode:
            transcript_vectors = [
                self._hashed_embedding(item.text) for item in analysis.transcript_segments
            ]
            visual_vectors = [
                self._hashed_embedding(f"video frame {item.timestamp:.1f}")
                for item in analysis.keyframes
            ]
        else:
            from PIL import Image
            from sentence_transformers import SentenceTransformer

            if self._transcript_embedder is None:
                self._transcript_embedder = SentenceTransformer(
                    str(self.setup.transcript_embedding_path)
                )
            if self._visual_embedder is None:
                self._visual_embedder = SentenceTransformer(str(self.setup.visual_embedding_path))
            transcript_vectors = (
                self._transcript_embedder.encode(
                    [item.text for item in analysis.transcript_segments],
                    normalize_embeddings=True,
                ).tolist()
                if analysis.transcript_segments
                else []
            )
            images = [
                Image.open(self._frame_path(analysis, item)).convert("RGB")
                for item in analysis.keyframes
                if self._frame_path(analysis, item).exists()
            ]
            visual_vectors = (
                self._visual_embedder.encode(images, normalize_embeddings=True).tolist()
                if images
                else []
            )
        payload = {
            "version": 1,
            "transcript": [
                {"id": item.id, "vector": vector}
                for item, vector in zip(
                    analysis.transcript_segments, transcript_vectors, strict=False
                )
            ],
            "visual": [
                {"id": item.id, "vector": vector}
                for item, vector in zip(analysis.keyframes, visual_vectors, strict=False)
            ],
        }
        path = self._embedding_index_path(analysis.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")

    def _embedding_scores(
        self, analysis: VideoAnalysis, query: str, source: str
    ) -> dict[str, float]:
        path = self._embedding_index_path(analysis.id)
        if not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        if self.settings.pro_test_mode:
            query_vector = self._hashed_embedding(query)
        else:
            from sentence_transformers import SentenceTransformer

            if source == "transcript":
                if self._transcript_embedder is None:
                    self._transcript_embedder = SentenceTransformer(
                        str(self.setup.transcript_embedding_path)
                    )
                query_vector = self._transcript_embedder.encode(
                    query, normalize_embeddings=True
                ).tolist()
            else:
                if self._visual_embedder is None:
                    self._visual_embedder = SentenceTransformer(
                        str(self.setup.visual_embedding_path)
                    )
                query_vector = self._visual_embedder.encode(
                    query, normalize_embeddings=True
                ).tolist()
        return {
            item["id"]: self._cosine(query_vector, item["vector"])
            for item in payload.get(source, [])
        }

    def _embedding_index_path(self, analysis_id: str) -> Path:
        return self._analysis_dir(analysis_id) / "embeddings.json"

    def _collect_evidence(
        self, analysis: VideoAnalysis, request: ChatRequest, retrieval_query: str | None = None
    ) -> tuple[list[ToolExecution], list[EvidenceCitation], list[Path], list[str]]:
        tools = [ToolExecution(name="video_metadata", result_count=1)]
        video = self.database.get_video(analysis.video_id)
        evidence = []
        citations: list[EvidenceCitation] = []
        if video:
            evidence.append(
                f"[metadata] duration={video.metadata.duration:.1f}s, "
                f"size={video.metadata.width}x{video.metadata.height}, "
                f"title={video.title or video.original_name}"
            )
        query = retrieval_query or request.question
        query_terms = self._query_terms(query)
        ranked = []
        transcript_scores = self._embedding_scores(analysis, query, "transcript")
        for segment in analysis.transcript_segments:
            text_terms = self._query_terms(segment.text)
            overlap = len(query_terms & text_terms)
            proximity = 0.0
            if request.current_time is not None:
                proximity = 1 / (1 + abs(segment.start - request.current_time))
            ranked.append(
                (overlap * 10 + transcript_scores.get(segment.id, 0) * 4 + proximity, segment)
            )
        selected_segments = [
            item
            for score, item in sorted(ranked, key=lambda item: item[0], reverse=True)[:6]
            if score > 0
        ]
        if not selected_segments and analysis.transcript_segments:
            selected_segments = analysis.transcript_segments[:4]
        tools.append(
            ToolExecution(
                name="search_transcript_embeddings",
                arguments={"query": query, "limit": 6},
                result_count=len(selected_segments),
            )
        )
        for segment in selected_segments:
            label = f"{self._clock(segment.start)}–{self._clock(segment.end)}"
            evidence.append(f"[transcript {label}] {segment.text}")
            matching_word_indexes = [
                index
                for index, word in enumerate(segment.words)
                if self._query_terms(word.text) & query_terms
            ]
            if matching_word_indexes:
                center = matching_word_indexes[0]
                timed_words = segment.words[max(0, center - 4) : center + 6]
                evidence.append(
                    "[word timing] "
                    + " ".join(f"{word.text}@{self._clock(word.start)}" for word in timed_words)
                )
            citations.append(
                EvidenceCitation(
                    start=segment.start, end=segment.end, label=label, kind="transcript"
                )
            )
        subject_matches = []
        lower = query.lower()
        for subject in analysis.subjects:
            if any(
                word in lower
                for word in ("person", "people", "who", "subject", subject.label.lower())
            ):
                subject_matches.append(subject)
        if subject_matches or any(
            word in lower for word in ("person", "people", "who", "subject")
        ):
            tools.append(ToolExecution(name="list_subjects", result_count=len(analysis.subjects)))
            for subject in (subject_matches or analysis.subjects)[:8]:
                windows = ", ".join(
                    f"{self._clock(item.start)}–{self._clock(item.end)}"
                    for item in subject.appearances[:8]
                )
                evidence.append(
                    f"[subject] {subject.label} appears at {windows or 'no confident window'}"
                )
                for appearance in subject.appearances[:2]:
                    citations.append(
                        EvidenceCitation(
                            start=appearance.start,
                            end=appearance.end,
                            label=f"{subject.label} · {self._clock(appearance.start)}",
                            kind="subject",
                            image_url=subject.thumbnail_url,
                        )
                    )
        target_times = self._question_times(request.question)
        target_times.extend(segment.start for segment in selected_segments[:3])
        if request.current_time is not None:
            target_times.insert(0, request.current_time)
        visual_scores = self._embedding_scores(analysis, query, "visual")
        semantic_frames = sorted(
            analysis.keyframes,
            key=lambda item: visual_scores.get(item.id, -1),
            reverse=True,
        )[:4]
        selected_frames: list[KeyframeRecord] = []
        for target in target_times:
            if analysis.keyframes:
                frame = min(analysis.keyframes, key=lambda item: abs(item.timestamp - target))
                if frame.id not in {item.id for item in selected_frames}:
                    selected_frames.append(frame)
        for frame in semantic_frames:
            if frame.id not in {item.id for item in selected_frames}:
                selected_frames.append(frame)
        selected_frames = selected_frames[:4]
        tools.append(
            ToolExecution(
                name="search_video_embeddings",
                arguments={
                    "query": query,
                    "timestamps": [round(item.timestamp, 2) for item in selected_frames],
                },
                result_count=len(selected_frames),
            )
        )
        image_paths = []
        for frame in selected_frames:
            path = self._frame_path(analysis, frame)
            if path.exists():
                image_paths.append(path)
                label = self._clock(frame.timestamp)
                evidence.append(f"[frame {label}] attached local keyframe")
                citations.append(
                    EvidenceCitation(
                        start=frame.timestamp,
                        end=min(
                            frame.timestamp + 1,
                            video.metadata.duration if video else frame.timestamp + 1,
                        ),
                        label=label,
                        kind="frame",
                        image_url=frame.image_url,
                    )
                )
        unique = {(item.kind, round(item.start, 2), item.label): item for item in citations}
        return tools, list(unique.values())[:10], image_paths, evidence

    @staticmethod
    def _contextual_query(question: str, history: list[ChatMessage]) -> str:
        if not history:
            return question.strip()
        context = "\n".join(
            f"{message.role}: {message.content}" for message in history[-4:]
        )
        return f"{context}\nuser follow-up: {question.strip()}"[-4000:]

    def _answer_prompt(
        self,
        analysis: VideoAnalysis,
        question: str,
        evidence: list[str],
        history: list[ChatMessage] | None = None,
    ) -> str:
        conversation = "\n".join(
            f"{message.role.title()}: {message.content}" for message in (history or [])[-8:]
        )
        return (
            "You are OhIc's private, local video analyst. Answer only from the supplied "
            "local evidence. Never invent a person identity, dialogue, or off-screen event. "
            "Resolve follow-up references from the conversation history. "
            "If evidence is insufficient, say so. "
            "Use concise prose and mention relevant timestamps exactly as written.\n\n"
            f"Conversation history:\n{conversation or '(new conversation)'}\n\n"
            f"Current question: {question}\n\nEvidence for analysis {analysis.id}:\n"
            + "\n".join(evidence)
        )

    def _write_vtt(self, analysis: VideoAnalysis) -> None:
        lines = ["WEBVTT", ""]
        for segment in analysis.transcript_segments:
            lines.extend(
                [
                    f"{self._vtt_time(segment.start)} --> {self._vtt_time(segment.end)}",
                    segment.text.replace("-->", "→"),
                    "",
                ]
            )
        path = self._analysis_dir(analysis.id) / "subtitles.vtt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines), encoding="utf-8")

    def _analysis_dir(self, analysis_id: str) -> Path:
        return self.root / "analyses" / analysis_id

    def subtitle_path(self, analysis_id: str) -> Path:
        return self._analysis_dir(analysis_id) / "subtitles.vtt"

    def subject_thumbnail_path(self, analysis_id: str, subject_id: str) -> Path:
        return self._analysis_dir(analysis_id) / "subjects" / f"{subject_id}.jpg"

    def frame_path_by_index(self, analysis_id: str, index: int) -> Path:
        return self._analysis_dir(analysis_id) / "frames" / f"{index:04d}.jpg"

    def _frame_path(self, analysis: VideoAnalysis, frame: KeyframeRecord) -> Path:
        index = analysis.keyframes.index(frame)
        return self.frame_path_by_index(analysis.id, index)

    def _set_progress(
        self, analysis_id: str, status: AnalysisStatus, progress: float, stage: str
    ) -> VideoAnalysis:
        analysis = self.database.get_analysis(analysis_id)
        if not analysis:
            raise ValueError("Analysis was removed.")
        analysis.status = status
        analysis.progress = progress
        analysis.stage = stage
        self._save(analysis)
        return analysis

    def _save(self, analysis: VideoAnalysis) -> None:
        analysis.updated_at = datetime.now(UTC)
        self.database.save_analysis(analysis)

    @staticmethod
    def _raise_if_cancelled(event: threading.Event) -> None:
        if event.is_set():
            raise CancelledError

    @staticmethod
    def _iou(left: tuple[float, ...], right: tuple[float, ...]) -> float:
        left_x, left_y, left_w, left_h = left
        right_x, right_y, right_w, right_h = right
        x1, y1 = max(left_x, right_x), max(left_y, right_y)
        x2, y2 = min(left_x + left_w, right_x + right_w), min(left_y + left_h, right_y + right_h)
        intersection = max(0, x2 - x1) * max(0, y2 - y1)
        union = left_w * left_h + right_w * right_h - intersection
        return intersection / union if union else 0

    @staticmethod
    def _query_terms(value: str) -> set[str]:
        stop = {"the", "a", "an", "is", "are", "at", "in", "on", "of", "to", "what", "when", "who"}
        return {
            word
            for word in re.findall(r"[a-z0-9']+", value.lower())
            if len(word) > 2 and word not in stop
        }

    @staticmethod
    def _hashed_embedding(value: str, dimensions: int = 64) -> list[float]:
        vector = np.zeros(dimensions, dtype=np.float32)
        for word in re.findall(r"\w+", value.lower(), flags=re.UNICODE):
            vector[sum(ord(character) for character in word) % dimensions] += 1
        norm = float(np.linalg.norm(vector))
        return (vector / norm).tolist() if norm else vector.tolist()

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        left_value = np.asarray(left, dtype=np.float32)
        right_value = np.asarray(right, dtype=np.float32)
        denominator = float(np.linalg.norm(left_value) * np.linalg.norm(right_value))
        return float(np.dot(left_value, right_value) / denominator) if denominator else 0.0

    @staticmethod
    def _question_times(value: str) -> list[float]:
        times = []
        for hours, minutes, seconds in re.findall(r"(?:(\d+):)?(\d{1,2}):(\d{2})", value):
            times.append(int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds))
        return times

    @staticmethod
    def _clock(seconds: float) -> str:
        seconds = max(0, int(seconds))
        hours, rest = divmod(seconds, 3600)
        minutes, value = divmod(rest, 60)
        return f"{hours}:{minutes:02d}:{value:02d}" if hours else f"{minutes}:{value:02d}"

    @staticmethod
    def _vtt_time(seconds: float) -> str:
        milliseconds = max(0, round(seconds * 1000))
        hours, rest = divmod(milliseconds, 3_600_000)
        minutes, rest = divmod(rest, 60_000)
        value, millis = divmod(rest, 1000)
        return f"{hours:02d}:{minutes:02d}:{value:02d}.{millis:03d}"


class CancelledError(Exception):
    pass
