from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import Settings
from app.models.database import Database
from app.schemas.intelligence import ProSetupState, ProStatus


class ProSetupService:
    """Installs the optional intelligence runtime only after explicit user consent."""

    MAC_QWEN = "mlx-community/Qwen3-VL-4B-Instruct-4bit"
    MAC_WHISPER = "mlx-community/whisper-large-v3-turbo"
    PORTABLE_QWEN = "Qwen/Qwen3-VL-2B-Instruct"
    PORTABLE_WHISPER = "Systran/faster-whisper-large-v3-turbo"
    HINGLISH_MODEL = "Trelis/tara"
    TRANSCRIPT_EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    VISUAL_EMBEDDING_MODEL = "sentence-transformers/clip-ViT-B-32"

    def __init__(self, settings: Settings, database: Database):
        self.settings = settings
        self.database = database
        self.root = settings.data_dir / "intelligence"
        self.models_dir = self.root / "models"
        self.runtime_dir = self.root / "runtime-packages"
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        runtime_path = str(self.runtime_dir)
        if runtime_path not in sys.path:
            sys.path.insert(0, runtime_path)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ohic-pro-setup")
        self._lock = threading.RLock()
        persisted = self.database.get_pro_status()
        if persisted and persisted.state == ProSetupState.INSTALLING:
            persisted.state = ProSetupState.ERROR
            persisted.stage = "Setup was interrupted"
            persisted.detail = "Choose Try again to safely resume the local download."
            persisted.error = "OhIc closed before Pro setup completed."
            self.database.save_pro_status(persisted)

    @property
    def is_apple_silicon(self) -> bool:
        return sys.platform == "darwin" and platform.machine().lower() in {"arm64", "aarch64"}

    @property
    def qwen_model(self) -> str:
        return self.settings.pro_qwen_model or (
            self.MAC_QWEN if self.is_apple_silicon else self.PORTABLE_QWEN
        )

    @property
    def whisper_model(self) -> str:
        return self.settings.pro_whisper_model or (
            self.MAC_WHISPER if self.is_apple_silicon else self.PORTABLE_WHISPER
        )

    @property
    def qwen_path(self) -> Path:
        return self.models_dir / "qwen"

    @property
    def whisper_path(self) -> Path:
        return self.models_dir / "whisper"

    @property
    def hinglish_path(self) -> Path:
        return self.models_dir / "tara-hinglish"

    @property
    def transcript_embedding_path(self) -> Path:
        return self.models_dir / "transcript-embeddings"

    @property
    def visual_embedding_path(self) -> Path:
        return self.models_dir / "visual-embeddings"

    def status(self) -> ProStatus:
        status = self.database.get_pro_status() or self._new_status()
        status.platform = self._platform_label()
        status.qwen_model = self.qwen_model
        status.whisper_model = self.whisper_model
        status.hinglish_model = self.HINGLISH_MODEL
        if status.state == ProSetupState.READY and not self.runtime_available():
            status.state = ProSetupState.ERROR
            status.progress = 0
            status.stage = "Pro runtime needs repair"
            if self.model_files_available():
                status.detail = (
                    "Your downloaded models are still on this computer. "
                    "Only the missing runtime components need to be restored."
                )
                status.error = "Required Pro runtime components are missing."
            else:
                status.detail = "Some local model files are missing and need to be restored."
                status.error = "The Pro installation is incomplete."
            self.database.save_pro_status(status)
        return status

    def start_install(self) -> ProStatus:
        with self._lock:
            current = self.status()
            if current.state == ProSetupState.INSTALLING:
                return current
            if current.state == ProSetupState.READY and self.runtime_available():
                return current
            current.state = ProSetupState.INSTALLING
            current.progress = 1
            current.stage = "Preparing private model storage"
            current.detail = "OhIc is setting up Pro locally. You can keep using the app."
            current.error = None
            self.database.save_pro_status(current)
            self._executor.submit(self._install)
            return current

    def runtime_available(self) -> bool:
        if self.settings.pro_test_mode:
            return (self.models_dir / ".test-ready").exists()
        required = ["cv2", "huggingface_hub", "rfdetr", "sentence_transformers", "supervision"]
        required.extend(
            ["mlx_vlm", "mlx_whisper"]
            if self.is_apple_silicon
            else ["transformers", "faster_whisper"]
        )
        return (
            all(importlib.util.find_spec(name) is not None for name in required)
            and self.model_files_available()
        )

    def model_files_available(self) -> bool:
        if self.settings.pro_test_mode:
            return (self.models_dir / ".test-ready").exists()
        return (
            all(
                (path / "config.json").exists()
                for path in (
                    self.qwen_path,
                    self.whisper_path,
                    self.hinglish_path,
                    self.transcript_embedding_path,
                    self.visual_embedding_path,
                )
            )
            and (self.models_dir / "rfdetr" / "rf-detr-small.pth").exists()
        )

    def require_ready(self) -> None:
        status = self.status()
        if status.state != ProSetupState.READY or not self.runtime_available():
            raise ValueError(
                status.error or "Pro Intelligence needs repair. Open Pro and retry setup."
            )

    def _new_status(self) -> ProStatus:
        return ProStatus(
            platform=self._platform_label(),
            qwen_model=self.qwen_model,
            whisper_model=self.whisper_model,
            hinglish_model=self.HINGLISH_MODEL,
            estimated_download_bytes=10_500_000_000 if self.is_apple_silicon else 12_500_000_000,
        )

    def _platform_label(self) -> str:
        if self.is_apple_silicon:
            return "Apple silicon · MLX acceleration"
        return f"{platform.system()} {platform.machine()} · portable runtime"

    def _update(self, progress: float, stage: str, detail: str) -> ProStatus:
        status = self.status()
        status.state = ProSetupState.INSTALLING
        status.progress = progress
        status.stage = stage
        status.detail = detail
        status.error = None
        self.database.save_pro_status(status)
        return status

    def _install(self) -> None:
        try:
            if self.settings.pro_test_mode:
                self._update(
                    45, "Testing optional setup", "No production model is downloaded in test mode."
                )
                (self.models_dir / ".test-ready").touch()
            else:
                self._install_packages()
                self._download_models()
            status = self.status()
            status.state = ProSetupState.READY
            status.progress = 100
            status.stage = "Pro is ready"
            status.detail = "Subtitles, subject tracking, and local video chat are available."
            status.installed_at = datetime.now(UTC)
            status.error = None
            self.database.save_pro_status(status)
        except Exception as exc:  # setup failures are surfaced verbatim in the local UI
            status = self.status()
            status.state = ProSetupState.ERROR
            status.stage = "Setup needs attention"
            status.detail = "No source video was changed. Check the error and try again."
            status.error = str(exc)[-1200:]
            self.database.save_pro_status(status)

    def _install_packages(self) -> None:
        self._update(
            8,
            "Installing the optional runtime",
            "This is isolated inside OhIc's Python environment.",
        )
        packages = [
            "huggingface-hub>=0.34",
            "rfdetr>=1.4,<2",
            "sentence-transformers>=5,<6",
            "supervision>=0.27,<1",
        ]
        if self.is_apple_silicon:
            packages.extend(["mlx-vlm>=0.3", "mlx-whisper>=0.4", "opencv-python>=4.10,<5"])
        else:
            packages.extend(
                [
                    "transformers>=4.57",
                    "accelerate>=1.10",
                    "qwen-vl-utils>=0.0.14",
                    "faster-whisper>=1.2",
                    "opencv-python-headless>=4.10,<5",
                ]
            )
        uv = shutil.which("uv")
        command = (
            [uv, "pip", "install", "--target", str(self.runtime_dir), "--upgrade", *packages]
            if uv
            else [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--target",
                str(self.runtime_dir),
                "--upgrade",
                *packages,
            ]
        )
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=1800, check=False
        )
        if completed.returncode:
            message = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(f"Optional Python packages could not be installed: {message[-900:]}")

    def _download_models(self) -> None:
        current = self.status()
        if current.installed_at and self.model_files_available():
            self._update(
                92,
                "Using existing local models",
                "The Qwen and Whisper downloads are already complete; no model download is needed.",
            )
            return
        self._download_snapshot(
            self.whisper_model,
            self.whisper_path,
            35,
            "Downloading the transcription model",
        )
        self._download_snapshot(
            self.qwen_model,
            self.qwen_path,
            65,
            "Downloading the local video-language model",
        )
        self._download_snapshot(
            self.HINGLISH_MODEL,
            self.hinglish_path,
            78,
            "Downloading Hindi and Hinglish transcription",
        )
        self._download_snapshot(
            self.TRANSCRIPT_EMBEDDING_MODEL,
            self.transcript_embedding_path,
            86,
            "Downloading multilingual transcript retrieval",
        )
        self._download_snapshot(
            self.VISUAL_EMBEDDING_MODEL,
            self.visual_embedding_path,
            91,
            "Downloading visual retrieval",
        )
        self._download_detection_model()
        self._update(
            96, "Verifying local models", "Checking that every required model file is present."
        )

    def _download_snapshot(
        self, repo_id: str, destination: Path, progress: float, stage: str
    ) -> None:
        self._update(
            progress, stage, f"Fetching {repo_id}. Existing partial downloads are resumed."
        )
        destination.mkdir(parents=True, exist_ok=True)
        script = (
            "from huggingface_hub import snapshot_download; "
            f"snapshot_download(repo_id={repo_id!r}, local_dir={str(destination)!r})"
        )
        environment = os.environ.copy()
        environment["HF_HOME"] = str(self.models_dir / ".cache")
        environment["PYTHONPATH"] = self._runtime_pythonpath(environment)
        completed = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=7200,
            check=False,
            env=environment,
        )
        if completed.returncode:
            message = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(f"Model download failed: {message[-900:]}")

    def _download_detection_model(self) -> None:
        self._update(
            94,
            "Downloading object detection and tracking",
            "Fetching Apache-licensed RF-DETR Small weights.",
        )
        environment = os.environ.copy()
        environment["RF_HOME"] = str(self.models_dir / "rfdetr")
        environment["PYTHONPATH"] = self._runtime_pythonpath(environment)
        completed = subprocess.run(
            [sys.executable, "-c", "from rfdetr import RFDETRSmall; RFDETRSmall()"],
            capture_output=True,
            text=True,
            timeout=3600,
            check=False,
            env=environment,
        )
        if completed.returncode:
            message = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(f"Detection model download failed: {message[-900:]}")

    def _runtime_pythonpath(self, environment: dict[str, str]) -> str:
        existing = environment.get("PYTHONPATH")
        return os.pathsep.join(part for part in (str(self.runtime_dir), existing) if part)
