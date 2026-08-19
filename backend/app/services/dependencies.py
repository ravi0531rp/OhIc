import shutil

from app.schemas.system import DependencyStatus


def dependency_status(command: str) -> DependencyStatus:
    path = shutil.which(command)
    if path:
        return DependencyStatus(available=True, path=path)
    return DependencyStatus(
        available=False,
        message=f"{command} is not installed. On macOS, run: brew install ffmpeg",
    )
