"""AOL-1 사진 촬영시각 추출의 우선순위·충돌·timezone 게이트."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from ksi_processing_controller.capture_time import (
    CaptureTimeSource,
    CaptureTimeStatus,
    extract_capture_time,
    parse_exif_datetime_offset,
    parse_exif_gps_utc,
    parse_explicit_xmp_time,
    resolve_capture_time,
)
from PIL import Image


def test_exif_gps_date_and_rational_time_are_utc() -> None:
    captured = parse_exif_gps_utc("2026:08:20", ((3, 1), (4, 1), (105, 10)))

    assert captured == datetime(2026, 8, 20, 3, 4, 10, 500_000, tzinfo=UTC)


def test_datetime_original_requires_and_applies_offset() -> None:
    assert parse_exif_datetime_offset("2026:08:20 12:00:00", None) is None
    assert parse_exif_datetime_offset("2026:08:20 12:00:00", "+09:00") == datetime(
        2026, 8, 20, 3, 0, tzinfo=UTC
    )


def test_xmp_requires_explicit_timezone() -> None:
    assert parse_explicit_xmp_time("2026-08-20T03:00:00") is None
    assert parse_explicit_xmp_time("2026-08-20T03:00:00Z") == datetime(
        2026, 8, 20, 3, 0, tzinfo=UTC
    )


def test_priority_is_fixed_when_candidates_are_within_one_second() -> None:
    gps = datetime(2026, 8, 20, 3, 0, tzinfo=UTC)
    result = resolve_capture_time(
        gps_utc=gps,
        exif_offset=gps + timedelta(seconds=1),
        dji_xmp_explicit=(gps + timedelta(milliseconds=500),),
    )

    assert result.status is CaptureTimeStatus.VERIFIED
    assert result.source is CaptureTimeSource.EXIF_GPS_UTC
    assert result.captured_at == gps


def test_more_than_one_second_difference_is_conflict() -> None:
    gps = datetime(2026, 8, 20, 3, 0, tzinfo=UTC)
    result = resolve_capture_time(
        gps_utc=gps,
        exif_offset=gps + timedelta(seconds=1, microseconds=1),
    )

    assert result.status is CaptureTimeStatus.CONFLICT
    assert result.source is CaptureTimeSource.NONE
    assert result.captured_at is None


def _jpeg_with_exif(path: Path, *, include_offset: bool) -> None:
    image = Image.new("RGB", (8, 8), color="white")
    exif = Image.Exif()
    exif[36867] = "2026:08:20 12:34:56"
    if include_offset:
        exif[36881] = "+09:00"
    image.save(path, format="JPEG", exif=exif)


def test_actual_jpeg_offset_exif_is_extracted(tmp_path: Path) -> None:
    path = tmp_path / "offset.jpg"
    _jpeg_with_exif(path, include_offset=True)

    result = extract_capture_time(path)

    assert result.status is CaptureTimeStatus.VERIFIED
    assert result.source is CaptureTimeSource.EXIF_DATETIME_OFFSET
    assert result.captured_at == datetime(2026, 8, 20, 3, 34, 56, tzinfo=UTC)


def test_actual_jpeg_naive_local_time_is_unavailable(tmp_path: Path) -> None:
    path = tmp_path / "naive.jpg"
    _jpeg_with_exif(path, include_offset=False)

    result = extract_capture_time(path)

    assert result.status is CaptureTimeStatus.UNAVAILABLE
    assert result.captured_at is None


def test_actual_dji_xmp_packet_with_explicit_time_is_extracted(tmp_path: Path) -> None:
    path = tmp_path / "dji-xmp.jpg"
    Image.new("RGB", (8, 8), color="white").save(path, format="JPEG")
    xmp = (
        b"http://ns.adobe.com/xap/1.0/\x00"
        b'<x:xmpmeta xmlns:x="adobe:ns:meta/" xmlns:drone-dji="http://www.dji.com/'
        b'drone-dji/1.0/" xmlns:xmp="http://ns.adobe.com/xap/1.0/">'
        b'<rdf:Description xmp:CreateDate="2026-08-20T03:34:56Z"/>'
        b"</x:xmpmeta>"
    )
    segment = b"\xff\xe1" + (len(xmp) + 2).to_bytes(2, "big") + xmp
    original = path.read_bytes()
    path.write_bytes(original[:2] + segment + original[2:])

    result = extract_capture_time(path)

    assert result.status is CaptureTimeStatus.VERIFIED
    assert result.source is CaptureTimeSource.DJI_XMP_EXPLICIT
    assert result.captured_at == datetime(2026, 8, 20, 3, 34, 56, tzinfo=UTC)
