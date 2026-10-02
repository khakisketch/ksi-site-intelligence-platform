"""Private immutable output observations/owned targets; no SDK or byte I/O dependency."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_JOB_ID = re.compile(r"sdj-v1-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _text(value: object, *, limit: int) -> str:
    if (
        type(value) is not str
        or not value
        or len(value.encode("utf-8")) > limit
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError("private storage field must be bounded control-free text")
    return value


def _digest(value: object) -> str:
    text = _text(value, limit=71)
    if _DIGEST.fullmatch(text) is None:
        raise ValueError("private storage binding requires a full prefixed SHA-256")
    return text


def _immutable_version(value: object) -> str:
    version = _text(value, limit=1024)
    if version != version.strip() or version.lower() == "null":
        raise ValueError("an immutable non-null object version is required")
    return version


def _positive_size(value: object) -> int:
    if type(value) is not int or not 0 < value <= 2**63 - 1:
        raise ValueError("observed size must be a strict positive bounded integer")
    return value


@dataclass(frozen=True, slots=True)
class SpatialDataObjectObservation:
    object_key: str
    version_id: str
    size_bytes: int
    sha256: str
    content_type: Literal["image/tiff"]

    def __post_init__(self) -> None:
        _text(self.object_key, limit=1024)
        _immutable_version(self.version_id)
        _positive_size(self.size_bytes)
        _digest(self.sha256)
        if self.content_type != "image/tiff":
            raise ValueError("output content type must be exactly image/tiff")


@dataclass(frozen=True, slots=True)
class SpatialDataOutputTarget:
    object_key: str
    job_id: str
    attempt_digest: str
    receipt_digest: str
    expires_at: datetime

    def __post_init__(self) -> None:
        _text(self.object_key, limit=1024)
        if _JOB_ID.fullmatch(_text(self.job_id, limit=43)) is None:
            raise ValueError("owned output must bind an exact data job ID")
        _digest(self.attempt_digest)
        _digest(self.receipt_digest)
        if (
            type(self.expires_at) is not datetime
            or self.expires_at.tzinfo is None
            or self.expires_at.utcoffset() != UTC.utcoffset(self.expires_at)
        ):
            raise ValueError("owned target expiry must be UTC-aware")
