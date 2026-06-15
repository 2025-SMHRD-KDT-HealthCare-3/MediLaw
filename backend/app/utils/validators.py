from __future__ import annotations

import re
from pathlib import PurePosixPath, PureWindowsPath


VALID_ROLES = {"USER", "ADMIN"}
VALID_ROOM_STATUSES = {"ACTIVE", "CLOSED"}
VALID_SPEAKER_TYPES = {"USER", "AI", "ADMIN"}
VALID_VERIFICATION_STATUSES = {"CONFIRMED", "WARNING", "ERROR"}
VALID_INPUT_LANGUAGES = {"ko", "en"}

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_PATTERN = re.compile(r"^[0-9+\-\s()]{7,20}$")


def is_valid_speaker_type(value: str) -> bool:
    return value in VALID_SPEAKER_TYPES


def is_valid_confidence_score(value: float) -> bool:
    return 0 <= value <= 100


def validate_email_format(value: str) -> str:
    email = value.strip().lower()
    if not _EMAIL_PATTERN.match(email):
        raise ValueError("invalid email format")
    return email


def validate_phone_number(value: str) -> str:
    phone_number = value.strip()
    if not _PHONE_PATTERN.match(phone_number):
        raise ValueError("invalid phone number format")
    return phone_number


def validate_file_reference(value: str) -> str:
    """Allow only a filename or relative reference path, never raw file bytes."""
    cleaned = value.strip().replace("\\", "/")
    posix_path = PurePosixPath(cleaned)
    windows_path = PureWindowsPath(value)
    if (
        not cleaned
        or posix_path.is_absolute()
        or windows_path.is_absolute()
        or ".." in posix_path.parts
    ):
        raise ValueError("invalid file reference path")
    return cleaned
