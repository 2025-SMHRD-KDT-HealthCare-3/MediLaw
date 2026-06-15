from pathlib import Path

from app.core.config import settings


def build_file_reference(filename: str) -> str:
    # TODO: add upload validation and storage provider integration.
    return str(Path(settings.UPLOAD_DIR) / filename)
