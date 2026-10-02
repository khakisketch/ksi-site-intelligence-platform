"""Closed finite value types shared only by the additive spatial-data family."""

from __future__ import annotations

import hashlib
import re
import sys
from datetime import UTC, datetime
from typing import Annotated, Any, ClassVar, Self
from urllib.parse import urlsplit

from ksi_domain.canonical_json import canonical_json_bytes
from pydantic import (
    AfterValidator,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    StringConstraints,
    model_validator,
)

from ksi_event_contracts._base import _CamelModel


def _utf8(value: str) -> str:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("text must be valid UTF-8") from exc
    return value


Text = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=255), AfterValidator(_utf8)
]
Attribution = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=4096), AfterValidator(_utf8)
]
Digest = Annotated[
    str,
    StringConstraints(strict=True, min_length=71, max_length=71, pattern=r"^sha256:[0-9a-f]{64}$"),
]
AssetRef = Annotated[
    str,
    StringConstraints(strict=True, min_length=71, max_length=71, pattern=r"^ksa-v1-[0-9a-f]{64}$"),
]
# Representation ceiling, not an operational budget or production default.
MAX_COUNTER = 2**63 - 1
PositiveInt = Annotated[StrictInt, Field(gt=0, le=MAX_COUNTER)]
PositiveSeconds = Annotated[StrictFloat, Field(gt=0, le=sys.float_info.max)]
Coordinate = Annotated[StrictFloat, Field(ge=-sys.float_info.max, le=sys.float_info.max)]


def _bounds(value: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    if value[0] >= value[2] or value[1] >= value[3]:
        raise ValueError("bounds must be ordered with positive extent")
    return value


Bounds = Annotated[tuple[Coordinate, Coordinate, Coordinate, Coordinate], AfterValidator(_bounds)]
_UTC_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)$"


def _timestamp_wire(value: object) -> object:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or re.fullmatch(_UTC_PATTERN, value) is None:
        raise ValueError("timestamp must be a UTC RFC3339 string or datetime")
    return value


def require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("timestamp must be timezone-aware UTC")
    return value


UtcTimestamp = Annotated[
    datetime,
    BeforeValidator(_timestamp_wire),
    AfterValidator(require_utc),
    Field(json_schema_extra={"pattern": _UTC_PATTERN}),
]


def _origin(value: str) -> str:
    if any(ord(char) <= 32 or ord(char) == 127 for char in value):
        raise ValueError("origin must not contain whitespace or control characters")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("origin is invalid") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or "?" in value
        or "#" in value
        or "\\" in value
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise ValueError("origin must be credential-free HTTP(S) without path, query or fragment")
    return value


Origin = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=512), AfterValidator(_origin)
]


class SpatialDataModel(_CamelModel):
    model_config = ConfigDict(frozen=True, revalidate_instances="always", validate_default=True)


class SpatialDataDigestModel(SpatialDataModel):
    """Hash content, not authority; a declared digest must bind the entire snapshot."""

    _digest_field: ClassVar[str]

    def _canonical_payload_unchecked(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json", exclude={self._digest_field})

    def _canonical_digest_unchecked(self) -> str:
        return (
            "sha256:"
            + hashlib.sha256(canonical_json_bytes(self._canonical_payload_unchecked())).hexdigest()
        )

    @model_validator(mode="after")
    def _declared_digest_matches(self) -> Self:
        digest = getattr(self, self._digest_field)
        if digest is not None and digest != self._canonical_digest_unchecked():
            raise ValueError(f"{self._digest_field} does not bind canonical content")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        return type(self).model_validate(self.__dict__)._canonical_payload_unchecked()

    def canonical_digest(self) -> str:
        return type(self).model_validate(self.__dict__)._canonical_digest_unchecked()

    def sealed(self) -> Self:
        validated = type(self).model_validate(self.__dict__)
        return type(self).model_validate(
            {**validated.__dict__, self._digest_field: validated._canonical_digest_unchecked()}
        )
