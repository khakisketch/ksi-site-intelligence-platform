"""Bounded TIFF structure reader used before the synthetic decoder conformance core.

It intentionally reads only a sealed local byte stream.  It never opens a
sidecar, URI, archive member, or GDAL virtual path.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

from ksi_event_contracts.external_artifact_validation import ResourceEnvelopeV1


class TiffStructureError(ValueError):
    """The bytes are not a bounded, self-contained TIFF structure."""


class TiffResourceLimitError(TiffStructureError):
    """A finite policy resource envelope was exceeded before decoding."""


_TYPE_SIZES = {
    1: 1,  # BYTE
    2: 1,  # ASCII
    3: 2,  # SHORT
    4: 4,  # LONG
    5: 8,  # RATIONAL
    6: 1,  # SBYTE
    7: 1,  # UNDEFINED
    8: 2,  # SSHORT
    9: 4,  # SLONG
    10: 8,  # SRATIONAL
    11: 4,  # FLOAT
    12: 8,  # DOUBLE
    13: 4,  # IFD
    16: 8,  # LONG8
    17: 8,  # SLONG8
    18: 8,  # IFD8
}
_INTEGER_FORMATS = {
    1: "B",
    3: "H",
    4: "I",
    6: "b",
    8: "h",
    9: "i",
    13: "I",
    16: "Q",
    17: "q",
    18: "Q",
}


@dataclass(frozen=True, slots=True)
class TiffEntryV1:
    tag: int
    field_type: int
    count: int
    raw: bytes

    def integers(self, byte_order: str) -> tuple[int, ...]:
        """Decode an integer-valued TIFF field without coercing other field types."""
        format_code = _INTEGER_FORMATS.get(self.field_type)
        if format_code is None:
            raise TiffStructureError(f"tag {self.tag} must use an integer TIFF type")
        return struct.unpack(byte_order + format_code * self.count, self.raw)

    def ascii(self) -> str:
        if self.field_type != 2:
            raise TiffStructureError(f"tag {self.tag} must use ASCII TIFF type")
        try:
            return self.raw.rstrip(b"\\x00").decode("ascii", "strict")
        except UnicodeDecodeError as exc:
            raise TiffStructureError(f"tag {self.tag} contains non-ASCII text") from exc


@dataclass(frozen=True, slots=True)
class TiffDirectoryV1:
    offset: int
    entries: dict[int, TiffEntryV1]
    next_offset: int
    # IFD table, next-pointer, and every out-of-line tag value.  Inline values
    # live inside the table and are therefore intentionally not added twice.
    storage_ranges: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class TiffStructureV1:
    payload_size: int
    container: str
    byte_order: str
    directories: tuple[TiffDirectoryV1, ...]
    allocated_block_count: int
    allocated_block_bytes: int
    estimated_decompressed_bytes: int
    estimated_sample_bytes: int
    # Exclusive end of every IFD and tag/index allocation.  COG payload data
    # must start at or after this point.
    index_end: int


def _tag_values(directory: TiffDirectoryV1, tag: int, byte_order: str) -> tuple[int, ...] | None:
    entry = directory.entries.get(tag)
    return None if entry is None else entry.integers(byte_order)


def _one(
    directory: TiffDirectoryV1, tag: int, byte_order: str, *, required: bool = True
) -> int | None:
    values = _tag_values(directory, tag, byte_order)
    if values is None:
        if required:
            raise TiffStructureError(f"required TIFF tag {tag} is absent")
        return None
    if len(values) != 1:
        raise TiffStructureError(f"TIFF tag {tag} must contain exactly one value")
    return values[0]


def _bounded_slice(payload: bytes, offset: int, length: int) -> bytes:
    if offset < 0 or length < 0 or offset > len(payload) or length > len(payload) - offset:
        raise TiffStructureError("TIFF offset/count pair escapes the sealed byte stream")
    return payload[offset : offset + length]


def _parse_directory(
    payload: bytes,
    offset: int,
    *,
    byte_order: str,
    big_tiff: bool,
    max_entries: int,
) -> TiffDirectoryV1:
    count_width = 8 if big_tiff else 2
    entry_width = 20 if big_tiff else 12
    tail_width = 8 if big_tiff else 4
    count_format = "Q" if big_tiff else "H"
    count_raw = _bounded_slice(payload, offset, count_width)
    entry_count = struct.unpack(byte_order + count_format, count_raw)[0]
    if entry_count > max_entries:
        raise TiffResourceLimitError("TIFF directory entry cap exceeded")
    table_start = offset + count_width
    table_size = entry_count * entry_width
    _bounded_slice(payload, table_start, table_size + tail_width)
    entries: dict[int, TiffEntryV1] = {}
    storage_ranges: list[tuple[int, int]] = [(offset, table_start + table_size + tail_width)]
    inline_width = 8 if big_tiff else 4
    for index in range(entry_count):
        raw = _bounded_slice(payload, table_start + index * entry_width, entry_width)
        if big_tiff:
            tag, field_type, count, value_offset = struct.unpack(byte_order + "HHQQ", raw)
        else:
            tag, field_type, count, value_offset = struct.unpack(byte_order + "HHII", raw)
        if tag in entries:
            raise TiffStructureError("TIFF directory contains a duplicate tag")
        unit_size = _TYPE_SIZES.get(field_type)
        if unit_size is None:
            raise TiffStructureError("TIFF directory contains an unsupported field type")
        if count <= 0 or count > (len(payload) // unit_size):
            raise TiffStructureError("TIFF directory contains an invalid value count")
        byte_count = count * unit_size
        if byte_count <= inline_width:
            value = raw[-inline_width:]
        else:
            value = _bounded_slice(payload, value_offset, byte_count)
            storage_ranges.append((value_offset, value_offset + byte_count))
        entries[tag] = TiffEntryV1(
            tag=tag, field_type=field_type, count=count, raw=value[:byte_count]
        )
    next_offset = struct.unpack(
        byte_order + ("Q" if big_tiff else "I"),
        _bounded_slice(payload, table_start + table_size, tail_width),
    )[0]
    return TiffDirectoryV1(
        offset=offset,
        entries=entries,
        next_offset=next_offset,
        storage_ranges=tuple(storage_ranges),
    )


def _block_stats(
    directory: TiffDirectoryV1,
    *,
    byte_order: str,
    payload_size: int,
) -> tuple[int, int, int, int, tuple[tuple[int, int], ...]]:
    """Validate every allocated strip/tile and return blocks, bytes, samples, raw estimate."""
    tile_offsets = _tag_values(directory, 324, byte_order)
    tile_counts = _tag_values(directory, 325, byte_order)
    strip_offsets = _tag_values(directory, 273, byte_order)
    strip_counts = _tag_values(directory, 279, byte_order)
    tile_tags_present = any(tag in directory.entries for tag in (322, 323, 324, 325))
    strip_tags_present = any(tag in directory.entries for tag in (273, 278, 279))
    if tile_tags_present == strip_tags_present:
        raise TiffStructureError("TIFF image must use exactly one strip or tile layout")
    width = _one(directory, 256, byte_order)
    height = _one(directory, 257, byte_order)
    samples = _one(directory, 277, byte_order)
    bits = _tag_values(directory, 258, byte_order)
    if width is None or height is None or samples is None or bits is None:
        raise TiffStructureError("TIFF image dimensions or sample model are invalid")
    if width <= 0 or height <= 0 or samples <= 0 or any(value <= 0 for value in bits):
        raise TiffStructureError("TIFF image dimensions or bit depth are invalid")
    _require_exact_raw_sample_model(directory, byte_order, samples, bits)
    planar_configuration = _one(directory, 284, byte_order, required=False) or 1
    if planar_configuration not in {1, 2}:
        raise TiffStructureError("TIFF planar configuration is invalid")
    planes = samples if planar_configuration == 2 else 1
    if tile_tags_present:
        tile_width = _one(directory, 322, byte_order)
        tile_height = _one(directory, 323, byte_order)
        if tile_width is None or tile_height is None or tile_width <= 0 or tile_height <= 0:
            raise TiffStructureError("TIFF tile geometry is invalid")
        if 278 in directory.entries:
            raise TiffStructureError("TIFF tiled image cannot carry RowsPerStrip")
        offsets, counts = tile_offsets, tile_counts
        expected_blocks = ((width + tile_width - 1) // tile_width) * (
            (height + tile_height - 1) // tile_height
        ) * planes
    else:
        rows_per_strip = _one(directory, 278, byte_order)
        if rows_per_strip is None or rows_per_strip <= 0:
            raise TiffStructureError("TIFF RowsPerStrip is invalid")
        if 322 in directory.entries or 323 in directory.entries:
            raise TiffStructureError("TIFF stripped image cannot carry tile geometry")
        offsets, counts = strip_offsets, strip_counts
        expected_blocks = ((height + rows_per_strip - 1) // rows_per_strip) * planes
    if counts is None or offsets is None or len(offsets) != len(counts) or not offsets:
        raise TiffStructureError("TIFF block offsets/counts are absent or mismatched")
    if len(offsets) != expected_blocks:
        raise TiffStructureError("TIFF block count does not match image geometry")
    ranges: list[tuple[int, int]] = []
    for offset, count in zip(offsets, counts, strict=True):
        if offset <= 0 or count <= 0 or offset > payload_size or count > payload_size - offset:
            raise TiffStructureError("TIFF block has an invalid offset/count pair")
        ranges.append((offset, offset + count))
    ordered_ranges = sorted(ranges)
    for (_, previous_end), (next_start, _) in zip(
        ordered_ranges,
        ordered_ranges[1:],
        strict=False,
    ):
        if next_start < previous_end:
            raise TiffStructureError("TIFF allocated blocks overlap")
    decompressed = width * height * sum(bits) // 8
    if width * height * sum(bits) % 8:
        decompressed += 1
    return len(offsets), sum(counts), decompressed, decompressed, tuple(ranges)


def _require_exact_raw_sample_model(
    directory: TiffDirectoryV1,
    byte_order: str,
    samples: int,
    bits: tuple[int, ...],
) -> None:
    """Validate the profile's raw sample model before a permissive decoder normalizes it."""
    if len(bits) != samples:
        raise TiffStructureError("BitsPerSample cardinality must equal SamplesPerPixel")
    sample_format = _tag_values(directory, 339, byte_order)
    if sample_format is None:
        sample_format = (1,) * samples
    if len(sample_format) != samples:
        raise TiffStructureError("SampleFormat cardinality must equal SamplesPerPixel")
    subtype = _one(directory, 254, byte_order, required=False) or 0
    if subtype & 4:
        if samples != 1 or bits != (1,) or sample_format != (1,):
            raise TiffStructureError("internal mask sample model is outside the profile")
        return
    if samples in {3, 4}:
        if bits != (8,) * samples or sample_format != (1,) * samples:
            raise TiffStructureError("RGB/RGBA raw sample model is outside the profile")
        return
    if samples == 1 and bits in {(32,), (64,)} and sample_format == (3,):
        return
    raise TiffStructureError("raw TIFF sample model is outside the profile")


def _reject_ambiguous_raw_georeference(directory: TiffDirectoryV1) -> None:
    """The profile never lets decoder precedence choose between two affine models."""
    if 34264 in directory.entries and (33550 in directory.entries or 33922 in directory.entries):
        raise TiffStructureError(
            "TIFF contains simultaneous transformation and scale/tiepoint models"
        )


def _require_globally_disjoint_ranges(ranges: list[tuple[int, int]]) -> None:
    """Reject cross-IFD image, index, and metadata allocation overlap before decode."""
    ordered = sorted(ranges)
    for (_, previous_end), (next_start, _) in zip(ordered, ordered[1:], strict=False):
        if next_start < previous_end:
            raise TiffStructureError("TIFF metadata, index, or block allocations overlap")


def parse_sealed_tiff_structure(path: Path, envelope: ResourceEnvelopeV1) -> TiffStructureV1:
    """Parse all IFDs and allocation pairs before Rasterio/GDAL can decode bytes."""
    if path.stat().st_size > min(envelope.max_input_bytes, envelope.max_streamed_bytes):
        raise TiffResourceLimitError("sealed input exceeds the finite policy byte cap")
    payload = path.read_bytes()
    if len(payload) > min(envelope.max_input_bytes, envelope.max_streamed_bytes):
        raise TiffResourceLimitError("sealed input exceeds the finite policy byte cap")
    if len(payload) < 8:
        raise TiffStructureError("sealed input is shorter than a TIFF header")
    marker = payload[:2]
    if marker == b"II":
        byte_order = "<"
    elif marker == b"MM":
        byte_order = ">"
    else:
        raise TiffStructureError("sealed input has no TIFF byte-order marker")
    magic = struct.unpack(byte_order + "H", payload[2:4])[0]
    if magic == 42:
        container = "CLASSIC_TIFF"
        first_offset = struct.unpack(byte_order + "I", payload[4:8])[0]
        big_tiff = False
    elif magic == 43:
        if len(payload) < 16:
            raise TiffStructureError("BigTIFF header is truncated")
        offset_size, reserved = struct.unpack(byte_order + "HH", payload[4:8])
        if offset_size != 8 or reserved != 0:
            raise TiffStructureError("BigTIFF header has unsupported offset fields")
        container = "BIGTIFF"
        first_offset = struct.unpack(byte_order + "Q", payload[8:16])[0]
        big_tiff = True
    else:
        raise TiffStructureError("sealed input has an unsupported TIFF magic")
    if first_offset == 0:
        raise TiffStructureError("TIFF has no image directory")
    directories: list[TiffDirectoryV1] = []
    total_entries = 0
    seen: set[int] = set()
    next_offset = first_offset
    while next_offset:
        if next_offset in seen:
            raise TiffStructureError("TIFF directory chain contains a cycle")
        if len(directories) >= envelope.max_tiff_directories:
            raise TiffResourceLimitError("TIFF directory cap exceeded")
        seen.add(next_offset)
        directory = _parse_directory(
            payload,
            next_offset,
            byte_order=byte_order,
            big_tiff=big_tiff,
            max_entries=envelope.max_tiff_entries,
        )
        total_entries += len(directory.entries)
        if total_entries > envelope.max_tiff_entries:
            raise TiffResourceLimitError("global TIFF directory entry cap exceeded")
        _reject_ambiguous_raw_georeference(directory)
        _reject_external_metadata(directory)
        directories.append(directory)
        next_offset = directory.next_offset
    total_blocks = allocated_bytes = decompressed = samples = 0
    index_ranges: list[tuple[int, int]] = [(0, 16 if big_tiff else 8)]
    all_ranges: list[tuple[int, int]] = list(index_ranges)
    for directory in directories:
        (
            current_blocks,
            current_allocated,
            current_decompressed,
            current_samples,
            block_ranges,
        ) = _block_stats(
            directory, byte_order=byte_order, payload_size=len(payload)
        )
        total_blocks += current_blocks
        allocated_bytes += current_allocated
        decompressed += current_decompressed
        samples += current_samples
        index_ranges.extend(directory.storage_ranges)
        all_ranges.extend(directory.storage_ranges)
        all_ranges.extend(block_ranges)
    _require_globally_disjoint_ranges(all_ranges)
    if total_blocks > envelope.max_blocks:
        raise TiffResourceLimitError("TIFF block cap exceeded")
    if decompressed > envelope.max_decompressed_bytes:
        raise TiffResourceLimitError("TIFF decompressed-byte cap exceeded")
    if samples > envelope.max_sample_bytes:
        raise TiffResourceLimitError("TIFF sample-byte cap exceeded")
    return TiffStructureV1(
        payload_size=len(payload),
        container=container,
        byte_order="II" if byte_order == "<" else "MM",
        directories=tuple(directories),
        allocated_block_count=total_blocks,
        allocated_block_bytes=allocated_bytes,
        estimated_decompressed_bytes=decompressed,
        estimated_sample_bytes=samples,
        index_end=max(end for _, end in index_ranges),
    )


def _reject_external_metadata(directory: TiffDirectoryV1) -> None:
    """Reject known metadata channels that can redirect a permissive decoder."""
    if 50844 in directory.entries:  # RPCCoefficientTag
        raise TiffStructureError("TIFF RPC metadata is outside the accepted georeference model")
    metadata = directory.entries.get(42112)  # GDAL_METADATA
    if metadata is None:
        return
    text = metadata.ascii().upper()
    if any(token in text for token in ("/VSI", "VRT", "HTTP:", "HTTPS:", "FILE:")):
        raise TiffStructureError("TIFF metadata requests an external reference")


__all__ = [
    "TiffDirectoryV1",
    "TiffResourceLimitError",
    "TiffStructureError",
    "TiffStructureV1",
    "parse_sealed_tiff_structure",
]
