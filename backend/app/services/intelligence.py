from __future__ import annotations

import math
import re
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

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
        analysis = VideoAnalysis(video_id=video.id, video_name=video.title or video.original_name)
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
        session = self.database.get_chat_session(request.session_id) if request.session_id else None
        if session and session.analysis_id != analysis_id:
            raise ValueError("This chat belongs to another video.")
        session = session or ChatSession(analysis_id=analysis_id)
        user_message = ChatMessage(role="user", content=request.question.strip())
        tools, citations, image_paths, evidence = self._collect_evidence(analysis, request)
        prompt = self._answer_prompt(analysis, request.question, evidence)
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
                    language, segments = self._transcribe(Path(video.path))
                    analysis.transcript_language = language
                    analysis.transcript_segments = segments
                    analysis.subtitle_url = f"/api/pro/analyses/{analysis.id}/subtitles.vtt"
                    self._save(analysis)
                    self._write_vtt(analysis)
                except Exception as exc:
                    analysis.warnings.append(f"Transcription was skipped: {exc}")
                    analysis.subtitle_url = (
                        f"/api/pro/analyses/{analysis.id}/subtitles.vtt"
                    )
                    self._save(analysis)
                    self._write_vtt(analysis)
            self._raise_if_cancelled(cancel)
            analysis = self._set_progress(
                analysis_id, AnalysisStatus.TRACKING, 45, "Finding and following people"
            )
            if request.track_people:
                try:
                    analysis.subjects = self._track_people(analysis, video, cancel)
                    self._save(analysis)
                except Exception as exc:
                    analysis.warnings.append(f"Person tracking was skipped: {exc}")
                    self._save(analysis)
            self._raise_if_cancelled(cancel)
            analysis = self._set_progress(
                analysis_id, AnalysisStatus.INDEXING, 82, "Building timestamp evidence"
            )
            analysis.keyframes = self._extract_keyframes(analysis, video, cancel)
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

    def _transcribe(self, video_path: Path) -> tuple[str | None, list[TranscriptSegment]]:
        if self.settings.pro_test_mode:
            return "en", [
                TranscriptSegment(start=0, end=2.5, text="A local test transcript for this video.")
            ]
        if self.setup.is_apple_silicon:
            import mlx_whisper

            result = mlx_whisper.transcribe(
                str(video_path),
                path_or_hf_repo=str(self.setup.whisper_path),
                word_timestamps=True,
                condition_on_previous_text=False,
                verbose=False,
            )
            return result.get("language"), self._parse_segments(result.get("segments", []))
        from faster_whisper import WhisperModel

        model = WhisperModel(str(self.setup.whisper_path), device="auto", compute_type="auto")
        iterable, info = model.transcribe(
            str(video_path), word_timestamps=True, vad_filter=True, condition_on_previous_text=False
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
        self, analysis: VideoAnalysis, video: VideoRecord, cancel: threading.Event
    ) -> list[SubjectRecord]:
        if self.settings.pro_test_mode:
            return [
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
        import cv2

        if not hasattr(cv2, "HOGDescriptor"):
            raise RuntimeError(
                "the installed OpenCV build does not include its person detector"
            )

        capture = cv2.VideoCapture(str(video.path))
        fps = capture.get(cv2.CAP_PROP_FPS) or max(video.metadata.fps, 1)
        duration = max(video.metadata.duration, 0.1)
        sample_seconds = max(0.6, duration / 300)
        step = max(1, round(sample_seconds * fps))
        detector = cv2.HOGDescriptor()
        detector.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        tracks: list[dict] = []
        frame_index = 0
        sample_index = 0
        analysis_dir = self._analysis_dir(analysis.id)
        (analysis_dir / "subjects").mkdir(parents=True, exist_ok=True)
        while capture.isOpened():
            self._raise_if_cancelled(cancel)
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, frame = capture.read()
            if not ok:
                break
            timestamp = frame_index / fps
            height, width = frame.shape[:2]
            scale = min(1.0, 720 / max(width, 1))
            view = cv2.resize(frame, None, fx=scale, fy=scale) if scale < 1 else frame
            boxes, weights = detector.detectMultiScale(
                view, winStride=(8, 8), padding=(8, 8), scale=1.05
            )
            detections = []
            for box, confidence in zip(boxes, weights, strict=False):
                x, y, w, h = [float(value) / scale for value in box]
                detections.append((x / width, y / height, w / width, h / height, float(confidence)))
            self._associate_detections(
                tracks, detections, timestamp, sample_seconds, frame, analysis_dir
            )
            sample_index += 1
            if sample_index % 8 == 0:
                current = self.database.get_analysis(analysis.id)
                if current:
                    current.progress = min(80, 45 + timestamp / duration * 35)
                    current.stage = f"Tracking people · {timestamp / duration:.0%} scanned"
                    self._save(current)
            frame_index += step
        capture.release()
        subjects = []
        for track in tracks:
            if len(track["appearances"]) < 2:
                continue
            subjects.append(
                SubjectRecord(
                    id=track["id"],
                    label=f"Person {len(subjects) + 1}",
                    color=SUBJECT_COLORS[len(subjects) % len(SUBJECT_COLORS)],
                    appearances=track["appearances"],
                    thumbnail_url=f"/api/pro/analyses/{analysis.id}/subjects/{track['id']}/thumbnail",
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

    def _collect_evidence(
        self, analysis: VideoAnalysis, request: ChatRequest
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
        query_terms = self._query_terms(request.question)
        ranked = []
        for segment in analysis.transcript_segments:
            text_terms = self._query_terms(segment.text)
            overlap = len(query_terms & text_terms)
            proximity = 0.0
            if request.current_time is not None:
                proximity = 1 / (1 + abs(segment.start - request.current_time))
            ranked.append((overlap * 10 + proximity, segment))
        selected_segments = [
            item
            for score, item in sorted(ranked, key=lambda item: item[0], reverse=True)[:6]
            if score > 0
        ]
        if not selected_segments and analysis.transcript_segments:
            selected_segments = analysis.transcript_segments[:4]
        tools.append(
            ToolExecution(
                name="search_transcript",
                arguments={"query": request.question, "limit": 6},
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
                    + " ".join(
                        f"{word.text}@{self._clock(word.start)}" for word in timed_words
                    )
                )
            citations.append(
                EvidenceCitation(
                    start=segment.start, end=segment.end, label=label, kind="transcript"
                )
            )
        subject_matches = []
        lower = request.question.lower()
        for subject in analysis.subjects:
            if any(
                word in lower
                for word in ("person", "people", "who", "subject", subject.label.lower())
            ):
                subject_matches.append(subject)
        if subject_matches or any(word in lower for word in ("person", "people", "who", "subject")):
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
        if not target_times and analysis.keyframes:
            target_times = [analysis.keyframes[0].timestamp]
        selected_frames: list[KeyframeRecord] = []
        for target in target_times:
            if analysis.keyframes:
                frame = min(analysis.keyframes, key=lambda item: abs(item.timestamp - target))
                if frame.id not in {item.id for item in selected_frames}:
                    selected_frames.append(frame)
        selected_frames = selected_frames[:4]
        tools.append(
            ToolExecution(
                name="inspect_frames",
                arguments={"timestamps": [round(item.timestamp, 2) for item in selected_frames]},
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

    def _answer_prompt(self, analysis: VideoAnalysis, question: str, evidence: list[str]) -> str:
        return (
            "You are OhIc's private, local video analyst. Answer only from the supplied "
            "local evidence. Never invent a person identity, dialogue, or off-screen event. "
            "If evidence is insufficient, say so. "
            "Use concise prose and mention relevant timestamps exactly as written.\n\n"
            f"Question: {question}\n\nEvidence for analysis {analysis.id}:\n" + "\n".join(evidence)
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
