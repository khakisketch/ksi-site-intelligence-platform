"""Private canonical helpers shared by the quantitative authority records."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from datetime import UTC, datetime

from ksi_domain.canonical_json import canonical_json_bytes

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_PROFILE = "external-geotiff-profile.v1"


def _digest(payload: Mapping[str, object]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(dict(payload))).hexdigest()


def _event_digest(event: Mapping[str, object]) -> str:
    return _digest({key: value for key, value in event.items() if key != "eventDigest"})


def _utc(value: datetime, *, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError(f"{name} must be UTC-aware")


def _wire_time(value: datetime) -> str:
    _utc(value, name="authority time")
    return value.isoformat().replace("+00:00", "Z")


def _parse_time(value: object, *, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a UTC timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    _utc(parsed, name=name)
    return parsed


def _required_digest(value: object, *, name: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ValueError(f"{name} must be a sha256 digest")
    return value


def _strict_mapping(raw: object, keys: frozenset[str], *, name: str) -> dict[str, object]:
    if type(raw) is not dict or set(raw) != keys or any(type(key) is not str for key in raw):
        raise ValueError(f"{name} has an invalid object shape")
    return raw
