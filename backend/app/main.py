import shutil
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.dependencies import (
    get_batch_manager,
    get_comparison_manager,
    get_database,
    get_job_manager,
    get_playlist_manager,
)
from app.api.routes import router
from app.core.config import get_settings
from app.core.logging import configure_logging


def clean_stale_temp(root: Path, older_than_hours: int) -> None:
    cutoff = time.time() - older_than_hours * 3600
    if not root.exists():
        return
    for item in root.iterdir():
        try:
            if item.stat().st_mtime < cutoff:
                shutil.rmtree(item, ignore_errors=True) if item.is_dir() else item.unlink(
                    missing_ok=True
                )
        except OSError:
            continue


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    get_database()
    recovered = get_job_manager().recover_interrupted()
    if recovered:
        __import__("structlog").get_logger().info("jobs_recovered", count=recovered)
    get_playlist_manager()
    get_batch_manager()
    get_comparison_manager()
    clean_stale_temp(settings.data_dir / "temp", settings.stale_temp_hours)
    yield


app = FastAPI(
    title="OhIc Local API",
    description="Private, local-first video restoration and upscaling",
    version="0.1.0",
    lifespan=lifespan,
)
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://127.0.0.1:3000"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.get("/")
def root() -> dict[str, str]:
    return {"name": "OhIc", "status": "local", "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=False)
