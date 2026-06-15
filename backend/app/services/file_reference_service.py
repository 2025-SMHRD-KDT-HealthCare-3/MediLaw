from pathlib import Path

from app.core.config import settings
from app.utils.validators import validate_file_reference


def build_file_reference(filename: str) -> str:
    """Build a safe relative upload reference for metadata storage."""
    safe_filename = validate_file_reference(filename)
    # TODO: replace local upload references with object storage keys if needed.
    return str(Path(settings.UPLOAD_DIR) / safe_filename).replace("\\", "/")
