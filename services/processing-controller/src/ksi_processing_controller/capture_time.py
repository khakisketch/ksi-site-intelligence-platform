"""사진 촬영시각 계보 추출(AOL-1, INV-020·040·051·052).

우선순위는 EXIF GPS UTC → DateTimeOriginal+OffsetTimeOriginal → 명시적
UTC/offset DJI XMP다. timezone 없는 값은 사용하지 않고, 둘 이상의 명시적
후보가 1초를 **초과해** 어긋나면 우선순위로 덮지 않고 CONFLICT로 닫는다.
"""

from __future__ import annotations

import re
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from enum import StrEnum
from fractions import Fraction
from pathlib import Path
from typing import Any

from PIL import ExifTags, Image


class CaptureTimeSource(StrEnum):
    EXIF_GPS_UTC = "EXIF_GPS_UTC"
    EXIF_DATETIME_OFFSET = "EXIF_DATETIME_OFFSET"
    DJI_XMP_EXPLICIT = "DJI_XMP_EXPLICIT"
    NONE = "NONE"


class CaptureTimeStatus(StrEnum):
    VERIFIED = "VERIFIED"
    UNAVAILABLE = "UNAVAILABLE"
    CONFLICT = "CONFLICT"


@dataclass(frozen=True, slots=True)
class ImageCaptureTime:
    captured_at: datetime | None
    source: CaptureTimeSource
    status: CaptureTimeStatus

    @classmethod
    def unavailable(cls) -> ImageCaptureTime:
        return cls(None, CaptureTimeSource.NONE, CaptureTimeStatus.UNAVAILABLE)

    @classmethod
    def conflict(cls) -> ImageCaptureTime:
        return cls(None, CaptureTimeSource.NONE, CaptureTimeStatus.CONFLICT)


_OFFSET_RE = re.compile(r"^(?P<sign>[+-])(?P<hour>\d{2}):(?P<minute>\d{2})$")
_XMP_CAPTURE_RE = re.compile(
    rb"(?:xmp:CreateDate|exif:DateTimeOriginal|drone-dji:(?:CaptureUtcTime|CreateDate|DateTimeOriginal))"
    rb"\s*=\s*[\"']([^\"']+)[\"']|"
    rb"<(?:xmp:CreateDate|exif:DateTimeOriginal|drone-dji:(?:CaptureUtcTime|CreateDate|DateTimeOriginal))>"
    rb"\s*([^<]+?)\s*</",
    re.IGNORECASE,
)


def _text(value: Any) -> str | None:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="strict").strip("\x00 ")
    if isinstance(value, str):
        return value.strip("\x00 ")
    return None


def _rational(value: Any) -> float:
    if hasattr(value, "numerator") and hasattr(value, "denominator"):
        return float(Fraction(int(value.numerator), int(value.denominator)))
    if isinstance(value, tuple) and len(value) == 2:
        return float(Fraction(int(value[0]), int(value[1])))
    return float(value)


def parse_exif_gps_utc(date_stamp: Any, time_stamp: Any) -> datetime | None:
    """GPSDateStamp+GPSTimeStamp를 UTC로 읽는다. 둘 중 하나라도 없으면 사용하지 않는다."""
    date_text = _text(date_stamp)
    if date_text is None or not isinstance(time_stamp, (tuple, list)) or len(time_stamp) != 3:
        return None
    try:
        date = datetime.strptime(date_text, "%Y:%m:%d").date()
        hour, minute, second = (_rational(value) for value in time_stamp)
        if (
            hour != int(hour)
            or minute != int(minute)
            or not 0 <= hour < 24
            or not 0 <= minute < 60
            or not 0 <= second < 60
        ):
            return None
        whole_second = int(second)
        microsecond = round((second - whole_second) * 1_000_000)
        return datetime(
            date.year,
            date.month,
            date.day,
            int(hour),
            int(minute),
            whole_second,
            microsecond,
            tzinfo=UTC,
        )
    except (ValueError, TypeError, ZeroDivisionError, OverflowError):
        return None


def parse_exif_datetime_offset(value: Any, offset: Any) -> datetime | None:
    """DateTimeOriginal은 OffsetTimeOriginal이 함께 있을 때만 사용한다."""
    value_text = _text(value)
    offset_text = _text(offset)
    if value_text is None or offset_text is None:
        return None
    match = _OFFSET_RE.fullmatch(offset_text)
    if match is None:
        return None
    hours = int(match.group("hour"))
    minutes = int(match.group("minute"))
    if hours > 23 or minutes > 59:
        return None
    delta = timedelta(hours=hours, minutes=minutes)
    if match.group("sign") == "-":
        delta = -delta
    try:
        local = datetime.strptime(value_text, "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None
    return local.replace(tzinfo=timezone(delta)).astimezone(UTC)


def parse_explicit_xmp_time(value: str) -> datetime | None:
    """XMP 시각 중 Z 또는 숫자 offset이 명시된 값만 UTC로 정규화한다."""
    stripped = value.strip()
    if not (stripped.endswith(("Z", "z")) or re.search(r"[+-]\d{2}:\d{2}$", stripped)):
        return None
    # 일부 DJI XMP는 ISO 8601 대신 EXIF식 날짜 구분자를 쓴다.
    if re.match(r"^\d{4}:\d{2}:\d{2}[ T]", stripped):
        stripped = f"{stripped[:4]}-{stripped[5:7]}-{stripped[8:]}"
    if stripped.endswith(("Z", "z")):
        stripped = stripped[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(stripped)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def resolve_capture_time(
    *,
    gps_utc: datetime | None,
    exif_offset: datetime | None,
    dji_xmp_explicit: tuple[datetime, ...] = (),
) -> ImageCaptureTime:
    """명시적 후보를 대조한 뒤 고정 우선순위로 하나를 선택한다."""
    candidates: list[tuple[CaptureTimeSource, datetime]] = []
    if gps_utc is not None:
        candidates.append((CaptureTimeSource.EXIF_GPS_UTC, gps_utc.astimezone(UTC)))
    if exif_offset is not None:
        candidates.append(
            (CaptureTimeSource.EXIF_DATETIME_OFFSET, exif_offset.astimezone(UTC))
        )
    candidates.extend(
        (CaptureTimeSource.DJI_XMP_EXPLICIT, value.astimezone(UTC))
        for value in dji_xmp_explicit
    )
    if not candidates:
        return ImageCaptureTime.unavailable()
    instants = [value for _, value in candidates]
    if max(instants) - min(instants) > timedelta(seconds=1):
        return ImageCaptureTime.conflict()
    source, captured_at = candidates[0]
    return ImageCaptureTime(captured_at, source, CaptureTimeStatus.VERIFIED)


def _exif_ifds(image: Image.Image) -> tuple[Any, Any]:
    exif = image.getexif()
    exif_ifd: dict[Any, Any] = dict(exif)
    gps_ifd: Any = {}
    with suppress(AttributeError, KeyError, TypeError):
        exif_ifd.update(exif.get_ifd(ExifTags.IFD.Exif))
    try:
        gps_ifd = exif.get_ifd(ExifTags.IFD.GPSInfo)
    except (AttributeError, KeyError, TypeError):
        raw_gps = exif.get(34853, {})
        if isinstance(raw_gps, dict):
            gps_ifd = raw_gps
    return exif_ifd, gps_ifd


def _dji_xmp_times(image: Image.Image) -> tuple[datetime, ...]:
    packets: list[bytes] = []
    for _marker, payload in getattr(image, "applist", ()):  # JPEG APP1 packets
        if isinstance(payload, bytes) and (
            b"drone-dji" in payload.lower() or b"dji.com" in payload.lower()
        ):
            packets.append(payload)
    raw_xmp = image.info.get("xmp")
    if isinstance(raw_xmp, bytes) and (
        b"drone-dji" in raw_xmp.lower() or b"dji.com" in raw_xmp.lower()
    ):
        packets.append(raw_xmp)
    parsed: list[datetime] = []
    for packet in packets:
        for match in _XMP_CAPTURE_RE.finditer(packet):
            raw = match.group(1) or match.group(2)
            try:
                text = raw.decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                continue
            value = parse_explicit_xmp_time(text)
            if value is not None:
                parsed.append(value)
    return tuple(parsed)


def extract_capture_time(path: Path) -> ImageCaptureTime:
    """사진 하나에서 세 근거를 모두 읽고 충돌까지 판정한다."""
    try:
        with Image.open(path) as image:
            exif_ifd, gps_ifd = _exif_ifds(image)
            gps_utc = parse_exif_gps_utc(gps_ifd.get(29), gps_ifd.get(7))
            exif_offset = parse_exif_datetime_offset(
                exif_ifd.get(36867), exif_ifd.get(36881)
            )
            xmp = _dji_xmp_times(image)
    except Exception:  # noqa: BLE001 -- metadata 손상은 이미지 실측 실패가 아니라 UNAVAILABLE다
        return ImageCaptureTime.unavailable()
    return resolve_capture_time(
        gps_utc=gps_utc,
        exif_offset=exif_offset,
        dji_xmp_explicit=xmp,
    )


__all__ = [
    "CaptureTimeSource",
    "CaptureTimeStatus",
    "ImageCaptureTime",
    "extract_capture_time",
    "parse_exif_datetime_offset",
    "parse_exif_gps_utc",
    "parse_explicit_xmp_time",
    "resolve_capture_time",
]
