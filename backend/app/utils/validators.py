VALID_SPEAKER_TYPES = {"USER", "AI", "ADMIN"}
VALID_VERIFICATION_STATUSES = {"CONFIRMED", "WARNING", "ERROR"}


def is_valid_speaker_type(value: str) -> bool:
    return value in VALID_SPEAKER_TYPES


def is_valid_confidence_score(value: float) -> bool:
    return 0 <= value <= 100
