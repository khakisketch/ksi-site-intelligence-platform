"""Small validation helpers shared by Gateway domain models."""

from __future__ import annotations

import re
from datetime import UTC, datetime

IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def validate_identifiers(*values: str) -> None:
    if any(IDENTIFIER.fullmatch(value) is None for value in values):
        raise ValueError("식별자는 경로-안전 비공백 문자만 허용한다")


def validate_object_ref(value: str) -> None:
    if not value.strip() or "?" in value or "#" in value:
        raise ValueError("object ref는 query/fragment가 없는 비공백 참조여야 한다")


def aware_datetime(value: str, *, field: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"{field}는 tz-aware ISO-8601이어야 한다")
    return parsed.astimezone(UTC)


__all__ = ["IDENTIFIER", "SHA256", "aware_datetime", "validate_identifiers", "validate_object_ref"]
