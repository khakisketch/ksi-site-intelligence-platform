#!/usr/bin/env python3
"""Prove an OCI index/config byte link; never grant release or execution authority."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
import sys
import tarfile
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SOURCE = re.compile(r"[0-9a-f]{40}\Z")
_BLOB = re.compile(r"blobs/sha256/[0-9a-f]{64}\Z")
_MAX_BYTES = 1024**3
_JSON_BYTES = 1024**2
_MAX_MEMBERS = 4096
_MAX_NODE_DESCRIPTORS = 64
_MAX_DEPTH = 8
# One root binding check plus each unique blob's maximum outgoing descriptor set:
# manifest layers64 + config1 + optional subject1. Shared incoming edges count too.
_MAX_GRAPH_DESCRIPTORS = 1 + _MAX_MEMBERS * (_MAX_NODE_DESCRIPTORS + 2)
_INDEX = "application/vnd.oci.image.index.v1+json"
_MANIFEST = "application/vnd.oci.image.manifest.v1+json"
_CONFIG = "application/vnd.oci.image.config.v1+json"
_LAYERS = {"application/vnd.oci.image.layer.v1.tar" + suffix for suffix in ("", "+gzip", "+zstd")}
_ATTESTATION = "application/vnd.in-toto+json"
_MEDIA = {_INDEX, _MANIFEST, _CONFIG, _ATTESTATION} | _LAYERS


class OciArchiveEvidenceError(ValueError):
    """Safe codes only; paths, configuration and embedded content are not diagnostics."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__("OCI_ARCHIVE_BLOCKED: " + code)


def _fail(code: str) -> NoReturn:
    raise OciArchiveEvidenceError(code)


def _identity(node: os.stat_result) -> tuple[int, ...]:
    return (node.st_dev, node.st_ino, node.st_size, node.st_mtime_ns, node.st_ctime_ns)


def _open_parent(path: Path) -> int:
    if not isinstance(path, Path) or not path.is_absolute() or ".." in path.parts or not path.name:
        _fail("INPUT_PATH")
    if "\0" in str(path):
        _fail("INPUT_PATH")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(path.anchor, flags)
    try:
        for part in path.parent.parts[1:]:
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _read(fd: int, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = os.read(fd, min(remaining, _JSON_BYTES))
        if not chunk:
            _fail("INPUT_SHORT_READ")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _hash(fd: int, offset: int, size: int) -> str:
    os.lseek(fd, offset, os.SEEK_SET)
    remaining = size
    result = hashlib.sha256()
    while remaining:
        chunk = os.read(fd, min(remaining, _JSON_BYTES))
        if not chunk:
            _fail("INPUT_SHORT_READ")
        result.update(chunk)
        remaining -= len(chunk)
    return "sha256:" + result.hexdigest()


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            _fail("JSON_DUPLICATE")
        result[key] = value
    return result


def _float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        _fail("JSON_NONFINITE")
    return result


class _Archive:
    def __init__(self, fd: int, size: int) -> None:
        self.fd = fd
        self.size = size
        self.members = self._members()
        self.seen: dict[str, tuple[str, int]] = {}
        self.verified_heights: dict[str, int] = {}
        self.descriptor_steps = 0

    def _members(self) -> dict[str, tuple[int, int]]:
        offset = 0
        count = 0
        names: set[str] = set()
        files: dict[str, tuple[int, int]] = {}
        while offset + 512 <= self.size:
            os.lseek(self.fd, offset, os.SEEK_SET)
            raw = _read(self.fd, 512)
            if raw == b"\0" * 512:
                if offset + 1024 > self.size or _read(self.fd, 512) != b"\0" * 512:
                    _fail("TAR_END")
                remaining = self.size - offset - 1024
                while remaining:
                    chunk_size = min(remaining, _JSON_BYTES)
                    if any(_read(self.fd, chunk_size)):
                        _fail("TAR_END")
                    remaining -= chunk_size
                return files
            # Reject extension bodies before TarFile can expand/read them.
            if raw[156:157] not in {b"0", b"\0", b"5"}:
                _fail("TAR_TYPE")
            try:
                node = tarfile.TarInfo.frombuf(raw, "utf-8", "strict")
            except (tarfile.HeaderError, UnicodeError, ValueError) as error:
                raise OciArchiveEvidenceError("TAR_HEADER") from error
            raw_name = node.name
            name = str(PurePosixPath(raw_name))
            if raw_name.startswith("/") or ".." in PurePosixPath(raw_name).parts or name in names:
                _fail("TAR_NAME")
            names.add(name)
            count += 1
            if count > _MAX_MEMBERS:
                _fail("TAR_LIMIT")
            size = node.size
            end = offset + 512 + ((size + 511) // 512) * 512
            if size < 0 or end > self.size:
                _fail("TAR_SIZE")
            if node.isdir():
                if size != 0 or name not in {"blobs", "blobs/sha256"}:
                    _fail("TAR_NAME")
            else:
                if name in {"index.json", "oci-layout", "manifest.json"}:
                    if not 0 < size <= _JSON_BYTES:
                        _fail("JSON_SIZE")
                elif not _BLOB.fullmatch(name):
                    _fail("TAR_NAME")
                files[name] = (offset + 512, size)
            offset = end
        _fail("TAR_END")

    def _json(self, name: str) -> dict[str, Any]:
        if name not in self.members:
            _fail("OCI_MISSING")
        offset, size = self.members[name]
        if not 0 < size <= _JSON_BYTES:
            _fail("JSON_SIZE")
        os.lseek(self.fd, offset, os.SEEK_SET)
        try:
            value = json.loads(
                _read(self.fd, size).decode("utf-8"), object_pairs_hook=_pairs,
                parse_constant=lambda _: _fail("JSON_NONFINITE"), parse_float=_float,
            )
        except (ValueError, UnicodeError, RecursionError) as error:
            if isinstance(error, OciArchiveEvidenceError):
                raise
            raise OciArchiveEvidenceError("JSON_SYNTAX") from error
        if not isinstance(value, dict):
            _fail("JSON_ROOT")
        return value

    def _descriptor(self, value: Any) -> tuple[str, str, int]:
        self.descriptor_steps += 1
        if self.descriptor_steps > _MAX_GRAPH_DESCRIPTORS:
            _fail("OCI_WORK_LIMIT")
        if not isinstance(value, dict) or "urls" in value:
            _fail("OCI_DESCRIPTOR")
        media, sha, size = value.get("mediaType"), value.get("digest"), value.get("size")
        if (
            not isinstance(media, str) or media not in _MEDIA
            or not isinstance(sha, str) or not _DIGEST.fullmatch(sha)
            or type(size) is not int or not 0 <= size <= self.size
        ):
            _fail("OCI_DESCRIPTOR")
        name = "blobs/sha256/" + sha[7:]
        if name not in self.members or self.members[name][1] != size:
            _fail("OCI_BLOB_SIZE")
        prior = self.seen.get(sha)
        if prior is not None and prior != (media, size):
            _fail("OCI_CONFLICT")
        self.seen[sha] = (media, size)
        return media, sha, size

    @staticmethod
    def _schema(value: dict[str, Any], media: str) -> None:
        if type(value.get("schemaVersion")) is not int or value["schemaVersion"] != 2:
            _fail("OCI_SCHEMA")
        if value.get("mediaType") != media:
            _fail("OCI_MEDIA")

    @staticmethod
    def _array(value: Any) -> list[Any]:
        if not isinstance(value, list) or len(value) > _MAX_NODE_DESCRIPTORS:
            _fail("OCI_LIMIT")
        return value

    def _walk(self, descriptor: dict[str, Any], depth: int, active: set[str]) -> int:
        if depth > _MAX_DEPTH:
            _fail("OCI_DEPTH")
        media, sha, _ = self._descriptor(descriptor)
        if sha in active:
            _fail("OCI_CYCLE")
        if sha in self.verified_heights:
            height = self.verified_heights[sha]
            if depth + height - 1 > _MAX_DEPTH:
                _fail("OCI_DEPTH")
            return height
        height = 1
        if media in {_INDEX, _MANIFEST, _CONFIG}:
            value = self._json("blobs/sha256/" + sha[7:])
            if media == _INDEX:
                self._schema(value, _INDEX)
                for child in self._array(value.get("manifests")):
                    if (
                        not isinstance(child, dict)
                        or child.get("mediaType") not in {_INDEX, _MANIFEST}
                    ):
                        _fail("OCI_DESCRIPTOR")
                    height = max(height, 1 + self._walk(child, depth + 1, active | {sha}))
            elif media == _MANIFEST:
                self._schema(value, _MANIFEST)
                config = value.get("config")
                if not isinstance(config, dict) or config.get("mediaType") != _CONFIG:
                    _fail("OCI_DESCRIPTOR")
                height = max(height, 1 + self._walk(config, depth + 1, active | {sha}))
                for child in self._array(value.get("layers")):
                    if (
                        not isinstance(child, dict)
                        or child.get("mediaType") not in _LAYERS | {_ATTESTATION}
                    ):
                        _fail("OCI_DESCRIPTOR")
                    height = max(height, 1 + self._walk(child, depth + 1, active | {sha}))
                if "subject" in value:
                    height = max(
                        height, 1 + self._walk(value["subject"], depth + 1, active | {sha}),
                    )
        self.verified_heights[sha] = height
        return height

    def verify(self, index_id: str, source: str, role: str) -> str:
        for name, (offset, size) in self.members.items():
            if (
                _BLOB.fullmatch(name)
                and _hash(self.fd, offset, size) != "sha256:" + name.rsplit("/", 1)[1]
            ):
                _fail("OCI_BLOB_HASH")
        if self._json("oci-layout").get("imageLayoutVersion") != "1.0.0":
            _fail("OCI_LAYOUT")
        root = self._json("index.json")
        self._schema(root, _INDEX)
        descriptors = self._array(root.get("manifests"))
        if len(descriptors) != 1:
            _fail("OCI_ROOT")
        media, sha, _ = self._descriptor(descriptors[0])
        if media != _INDEX or sha != index_id:
            _fail("OCI_ROOT")
        self._walk(descriptors[0], 1, set())
        index = self._json("blobs/sha256/" + index_id[7:])
        candidates = []
        for descriptor in index["manifests"]:
            platform = descriptor.get("platform")
            if (
                isinstance(platform, dict) and platform.get("os") == "linux"
                and platform.get("architecture") == "arm64"
            ):
                if (
                    platform.get("variant") not in {None, "v8"}
                    or descriptor["mediaType"] != _MANIFEST
                ):
                    _fail("OCI_PLATFORM")
                candidates.append(descriptor)
        if len(candidates) != 1:
            _fail("OCI_PLATFORM")
        manifest = self._json("blobs/sha256/" + candidates[0]["digest"][7:])
        if any(layer["mediaType"] not in _LAYERS for layer in manifest["layers"]):
            _fail("OCI_PLATFORM")
        config_id = manifest["config"]["digest"]
        config = self._json("blobs/sha256/" + config_id[7:])
        settings, rootfs = config.get("config"), config.get("rootfs")
        if not isinstance(settings, dict) or not isinstance(rootfs, dict):
            _fail("RUNTIME_CONFIG")
        labels, diff_ids = settings.get("Labels"), rootfs.get("diff_ids")
        if (
            config.get("os") != "linux" or config.get("architecture") != "arm64"
            or settings.get("User") != f"ksi-{role}-image"
            or settings.get("Cmd") != [f"/app/.venv/bin/ksi-external-{role}-entrypoint"]
            or settings.get("Entrypoint") not in (None, [])
            or not isinstance(labels, dict)
            or labels.get("org.opencontainers.image.revision") != source
            or rootfs.get("type") != "layers" or not isinstance(diff_ids, list)
            or len(diff_ids) != len(manifest["layers"])
            or not all(isinstance(item, str) and _DIGEST.fullmatch(item) for item in diff_ids)
        ):
            _fail("RUNTIME_CONFIG")
        return str(config_id)


def verify_oci_archive(
    path: Path, *, expected_sha256: str, expected_bytes: int, expected_index_id: str,
    expected_source_commit: str, role: str,
) -> str:
    """Return the archive-proven config ID, not scanner truth or execution approval."""
    if (
        not isinstance(expected_sha256, str) or not _DIGEST.fullmatch(expected_sha256)
        or type(expected_bytes) is not int or not 0 < expected_bytes <= _MAX_BYTES
        or not isinstance(expected_index_id, str) or not _DIGEST.fullmatch(expected_index_id)
        or not isinstance(expected_source_commit, str)
        or not _SOURCE.fullmatch(expected_source_commit)
        or not isinstance(role, str) or role not in {"inspector", "measurement"}
    ):
        _fail("EXPECTED_BINDING")
    parent_fd: int | None = None
    fd: int | None = None
    try:
        parent_fd = _open_parent(path)
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                     dir_fd=parent_fd)
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size != expected_bytes:
            _fail("INPUT_FILE")
        if _hash(fd, 0, expected_bytes) != expected_sha256:
            _fail("INPUT_HASH")
        result = _Archive(fd, expected_bytes).verify(
            expected_index_id, expected_source_commit, role,
        )
        if _hash(fd, 0, expected_bytes) != expected_sha256:
            _fail("INPUT_CHANGED")
        after = os.fstat(fd)
        named = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(named.st_mode) or _identity(before) != _identity(after)
            or _identity(named) != _identity(after)
        ):
            _fail("INPUT_CHANGED")
        return result
    except (OSError, ValueError, RecursionError, TypeError) as error:
        if isinstance(error, OciArchiveEvidenceError):
            raise
        raise OciArchiveEvidenceError("INPUT_INVALID") from error
    finally:
        if fd is not None:
            os.close(fd)
        if parent_fd is not None:
            os.close(parent_fd)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--bytes", type=int, required=True)
    parser.add_argument("--index-id", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--role", required=True)
    args = parser.parse_args(argv)
    try:
        result = verify_oci_archive(
            args.path, expected_sha256=args.sha256, expected_bytes=args.bytes,
            expected_index_id=args.index_id, expected_source_commit=args.source_commit,
            role=args.role,
        )
    except OciArchiveEvidenceError as error:
        print(str(error), file=sys.stderr)
        return 1
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
