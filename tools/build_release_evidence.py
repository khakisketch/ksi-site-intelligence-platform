#!/usr/bin/env python3
"""Build a non-networked, fail-closed KSI release evidence manifest.

The public CLI derives the current clean Git source state.  It never invokes
Docker, contacts a registry, reads credentials, or treats supplied scanner JSON
as a vulnerability approval or deployment authorization.

The create-once owner-only local envelope and its SHA-256 sidecar are not an
authenticity signature or tamper-proof storage. Signed/WORM/remote anchoring is
an external release gate.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

_GIT_SHA = re.compile(r"[0-9a-f]{40}\Z")
_SAFE_ARTIFACT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_NODEODM_DIGEST_ONLY = (
    "opendronemap/nodeodm@sha256:cb07d06e21fd6189cfad287c6fedfa0b72568100355635cd9035cb86eed42ee2"
)
_PRODUCT_IMAGE_REFERENCE = re.compile(
    r"^(?:[a-z0-9][a-z0-9._-]*(?::[0-9]{1,5})?/)?(?:[a-z0-9][a-z0-9._/-]*/)*ksi-[a-z0-9][a-z0-9._-]*:"
    r"(?!(?:latest|stable|main|master|dev|edge|nightly|local)@)"
    r"(?=[A-Za-z0-9._-]*[0-9])[A-Za-z0-9][A-Za-z0-9._-]*@sha256:[0-9a-f]{64}\Z"
)
_EXTERNAL_RUNTIME_IMAGE_REFERENCE = re.compile(
    r"^(?:[a-z0-9][a-z0-9._-]*(?::[0-9]{1,5})?/)?(?:[a-z0-9][a-z0-9._/-]*/)*[a-z0-9][a-z0-9._-]*:"
    r"(?!(?:latest|stable|main|master|dev|edge|nightly|local)@)"
    r"[A-Za-z0-9][A-Za-z0-9._-]*@sha256:[0-9a-f]{64}\Z"
)
_MAX_JSON_BYTES = 16 * 1024 * 1024
_SCHEMA_VERSION = "1.0"
_OUTPUT_FILENAMES = ("release-evidence.json", "release-evidence.json.sha256")
_CANONICAL_UTC = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")
_RUNTIME_PIN_CHECKER = PurePosixPath("tools/check_runtime_image_pins.py")


class ReleaseEvidenceError(ValueError):
    """A release provenance input was unsafe, incomplete, or unverifiable."""


@dataclass(frozen=True)
class ImageEvidenceInput:
    """A product image and the two local artifacts associated with that image.

    This binds the supplied artifact hashes to one image reference in the local
    envelope. It does not prove that either artifact was generated from that
    image; a signed or remotely anchored release process is a separate gate.
    """

    reference: str
    sbom_path: Path | None
    scanner_path: Path | None


@dataclass(frozen=True)
class ReleaseBuildContext:
    """Internal deterministic context for tests; the CLI never accepts these values."""

    source_commit: str
    generated_at_utc: str


@dataclass(frozen=True)
class ReleaseEvidenceResult:
    output_dir: Path
    manifest_path: Path
    sidecar_path: Path
    manifest_sha256: str


@dataclass(frozen=True)
class _OpenedOutputDirectory:
    path: Path
    parent_fd: int
    directory_fd: int
    name: str


def _run_git(repo_root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repo_root,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    if completed.returncode != 0:
        raise ReleaseEvidenceError(
            "Git source identity could not be derived from the requested repository"
        )
    return completed.stdout


def derive_clean_git_source(repo_root: Path) -> str:
    """Return HEAD only when every tracked and untracked worktree entry is clean."""
    status = _run_git(repo_root, "status", "--porcelain=v1", "--untracked-files=all")
    if status:
        raise ReleaseEvidenceError("refusing release evidence from a dirty Git worktree")
    source_commit = _run_git(repo_root, "rev-parse", "HEAD").strip()
    if _GIT_SHA.fullmatch(source_commit) is None:
        raise ReleaseEvidenceError("Git HEAD is not a full lowercase commit SHA")
    return source_commit


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _validated_context(context: ReleaseBuildContext) -> ReleaseBuildContext:
    if _GIT_SHA.fullmatch(context.source_commit) is None:
        raise ReleaseEvidenceError("release source commit must be a full lowercase Git SHA")
    if _CANONICAL_UTC.fullmatch(context.generated_at_utc) is None:
        raise ReleaseEvidenceError("release generatedAtUtc must be canonical UTC with a trailing Z")
    try:
        parsed = datetime.fromisoformat(context.generated_at_utc.replace("Z", "+00:00"))
    except ValueError as error:
        raise ReleaseEvidenceError(
            "release generatedAtUtc must be an ISO-8601 UTC timestamp"
        ) from error
    normalized_timestamp = (
        parsed.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )
    if parsed.tzinfo is None or context.generated_at_utc != normalized_timestamp:
        raise ReleaseEvidenceError("release generatedAtUtc must be canonical UTC with a trailing Z")
    return context


def _is_under(candidate: Path, parent: Path) -> bool:
    try:
        candidate.relative_to(parent)
    except ValueError:
        return False
    return True


def _validate_absolute_normalized(path: Path, *, label: str) -> None:
    if not path.is_absolute() or ".." in path.parts:
        raise ReleaseEvidenceError(f"{label} must be an absolute normalized path")


def _secure_open_directory(path: Path, *, label: str) -> int:
    """Open an existing directory component-by-component without following symlinks."""
    _validate_absolute_normalized(path, label=label)
    no_follow = getattr(os, "O_NOFOLLOW", None)
    if no_follow is None:
        raise ReleaseEvidenceError("Linux O_NOFOLLOW is required for release evidence")
    flags = os.O_RDONLY | os.O_DIRECTORY | no_follow | getattr(os, "O_CLOEXEC", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(path.anchor, flags)
        for component in path.parts[1:]:
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode):
            raise ReleaseEvidenceError(f"{label} must be a directory")
        return descriptor
    except OSError as error:
        if descriptor is not None:
            os.close(descriptor)
        raise ReleaseEvidenceError(
            f"{label} contains a missing or symlinked path component"
        ) from error
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
        raise


def _secure_open_input_file(path: Path, *, label: str) -> tuple[int, os.stat_result]:
    """Open one input once and keep its regular-file identity on that descriptor."""
    parent_fd = _secure_open_directory(path.parent, label=f"{label} parent path")
    no_follow = getattr(os, "O_NOFOLLOW", None)
    if no_follow is None:  # pragma: no cover - _secure_open_directory checks this first.
        os.close(parent_fd)
        raise ReleaseEvidenceError("Linux O_NOFOLLOW is required for release evidence")
    try:
        descriptor = os.open(
            path.name,
            os.O_RDONLY | no_follow | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent_fd,
        )
    except OSError as error:
        raise ReleaseEvidenceError(f"{label} is missing or is a symlink") from error
    finally:
        os.close(parent_fd)
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode):
        os.close(descriptor)
        raise ReleaseEvidenceError(f"{label} must be a regular file")
    return descriptor, metadata


def _read_descriptor_bytes(
    descriptor: int, *, metadata: os.stat_result, artifact_kind: str, artifact_name: str
) -> bytes:
    if metadata.st_size <= 0 or metadata.st_size > _MAX_JSON_BYTES:
        raise ReleaseEvidenceError(
            f"{artifact_kind} artifact has an unsafe JSON size: {artifact_name}"
        )
    chunks: list[bytes] = []
    remaining = metadata.st_size
    while remaining:
        try:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
        except OSError as error:
            raise ReleaseEvidenceError(
                f"{artifact_kind} artifact could not be read: {artifact_name}"
            ) from error
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    payload = b"".join(chunks)
    after = os.fstat(descriptor)
    before_identity = (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )
    after_identity = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    identity_changed = after_identity != before_identity
    if len(payload) != metadata.st_size or identity_changed:
        raise ReleaseEvidenceError(
            f"{artifact_kind} artifact changed while it was read: {artifact_name}"
        )
    return payload


def _read_regular_json(
    path: Path, *, repo_root: Path, artifact_kind: str
) -> tuple[dict[str, Any], bytes]:
    _validate_absolute_normalized(path, label="release evidence artifact path")
    if _is_under(path, repo_root.resolve()):
        raise ReleaseEvidenceError(
            f"{artifact_kind} artifact must live outside the Git worktree: {path.name}"
        )
    if _SAFE_ARTIFACT_NAME.fullmatch(path.name) is None:
        raise ReleaseEvidenceError(f"{artifact_kind} artifact has an unsafe filename")
    descriptor, metadata = _secure_open_input_file(path, label=f"{artifact_kind} artifact")
    try:
        payload = _read_descriptor_bytes(
            descriptor,
            metadata=metadata,
            artifact_kind=artifact_kind,
            artifact_name=path.name,
        )
    finally:
        os.close(descriptor)
    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=_reject_duplicate_json_keys)
    except (UnicodeDecodeError, json.JSONDecodeError, ReleaseEvidenceError) as error:
        raise ReleaseEvidenceError(
            f"{artifact_kind} artifact is not valid JSON: {path.name}"
        ) from error
    if not isinstance(value, dict):
        raise ReleaseEvidenceError(
            f"{artifact_kind} artifact JSON root must be an object: {path.name}"
        )
    return value, payload


def _reject_duplicate_json_keys(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReleaseEvidenceError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _artifact_record(path: Path, *, repo_root: Path, artifact_kind: str) -> dict[str, str | int]:
    parsed, payload = _read_regular_json(path, repo_root=repo_root, artifact_kind=artifact_kind)
    if artifact_kind == "sbom" and (
        parsed.get("bomFormat") != "CycloneDX" or not isinstance(parsed.get("specVersion"), str)
    ):
        raise ReleaseEvidenceError(f"SBOM is not a CycloneDX JSON document: {path.name}")
    if artifact_kind == "scanner" and not parsed:
        raise ReleaseEvidenceError(
            f"scanner artifact must not be an empty JSON object: {path.name}"
        )
    return {
        "name": path.name,
        "type": "cyclonedx-json" if artifact_kind == "sbom" else "scanner-json",
        "bytes": len(payload),
        "sha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
    }


def _validate_product_image_reference(reference: str) -> str:
    if _PRODUCT_IMAGE_REFERENCE.fullmatch(reference) is None:
        raise ReleaseEvidenceError(
            "product image must be a literal ksi-* exact version tag plus sha256 digest: "
            f"{reference}"
        )
    return reference


def _validate_external_runtime_image_reference(reference: str) -> str:
    if reference == _NODEODM_DIGEST_ONLY:
        return reference
    if _EXTERNAL_RUNTIME_IMAGE_REFERENCE.fullmatch(reference) is None:
        raise ReleaseEvidenceError(
            "external runtime image must have a non-floating version tag plus sha256 digest: "
            f"{reference}"
        )
    return reference


def _run_git_bytes(repo_root: Path, *arguments: str) -> bytes:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repo_root,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if completed.returncode != 0:
        raise ReleaseEvidenceError("exact Git source snapshot could not be read")
    return completed.stdout


def _is_runtime_snapshot_path(path: PurePosixPath) -> bool:
    """Match the pin gate's product-owned file scope without reading live files."""
    parts = path.parts
    name = path.name
    if path == _RUNTIME_PIN_CHECKER:
        return True
    if len(parts) == 1:
        return name.startswith("Dockerfile")
    if len(parts) == 3 and parts[0] in {"apps", "services", "workers"}:
        return parts[2].startswith("Dockerfile")
    if len(parts) == 3 and parts[:2] == ("edge", "docker"):
        return name.endswith("Dockerfile")
    if len(parts) == 2 and parts[0] == "deploy":
        return name.startswith("compose") and name.endswith((".yaml", ".yml"))
    return len(parts) == 3 and parts[:2] == ("deploy", "bin") and name.endswith(".sh")


def _snapshot_tree_entries(
    repo_root: Path, source_commit: str
) -> list[tuple[str, str, PurePosixPath]]:
    output = _run_git_bytes(repo_root, "ls-tree", "-r", "-z", "--full-tree", source_commit)
    entries: list[tuple[str, str, PurePosixPath]] = []
    for record in output.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, object_type, _object_id = metadata.decode("ascii").split(" ", 2)
            path = PurePosixPath(raw_path.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as error:
            raise ReleaseEvidenceError("exact Git source snapshot has an invalid path") from error
        if path.is_absolute() or ".." in path.parts or "." in path.parts:
            raise ReleaseEvidenceError("exact Git source snapshot has an unsafe path")
        if _is_runtime_snapshot_path(path):
            entries.append((mode, object_type, path))
    return entries


@contextmanager
def _runtime_pin_snapshot(repo_root: Path, source_commit: str) -> Iterator[Path]:
    """Materialize only pin-gate inputs from one Git tree into a fresh safe directory."""
    if _GIT_SHA.fullmatch(source_commit) is None:
        raise ReleaseEvidenceError("runtime source commit must be a full lowercase Git SHA")
    entries = _snapshot_tree_entries(repo_root, source_commit)
    if not any(path == _RUNTIME_PIN_CHECKER for _mode, _type, path in entries):
        raise ReleaseEvidenceError("runtime image pin gate is absent from the exact Git source")
    with tempfile.TemporaryDirectory(prefix="ksi-release-runtime-") as temporary:
        snapshot_root = Path(temporary)
        for mode, object_type, path in entries:
            if object_type != "blob" or mode not in {"100644", "100755"}:
                raise ReleaseEvidenceError(
                    "runtime source snapshot contains a non-regular pin-gate file: "
                    f"{path.as_posix()}"
                )
            destination = snapshot_root.joinpath(*path.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            payload = _run_git_bytes(repo_root, "show", f"{source_commit}:{path.as_posix()}")
            with destination.open("xb") as target:
                target.write(payload)
        yield snapshot_root


def _runtime_image_references(repo_root: Path, source_commit: str) -> list[str]:
    """Read pin references only from the same committed tree as the source SHA."""
    with _runtime_pin_snapshot(repo_root, source_commit) as snapshot_root:
        checker_path = snapshot_root.joinpath(*_RUNTIME_PIN_CHECKER.parts)
        spec = importlib.util.spec_from_file_location(
            "ksi_runtime_image_pins_snapshot", checker_path
        )
        if spec is None or spec.loader is None:
            raise ReleaseEvidenceError("runtime image pin gate could not be loaded")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        try:
            references = module.runtime_image_references(snapshot_root)
        except (AttributeError, ValueError) as error:
            raise ReleaseEvidenceError(
                "runtime image pin gate rejected the exact source tree"
            ) from error
    return sorted(
        {_validate_external_runtime_image_reference(entry.reference) for entry in references}
    )


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    return serialized.encode("utf-8")


def _create_output_directory(output_dir: Path, *, repo_root: Path) -> _OpenedOutputDirectory:
    _validate_absolute_normalized(output_dir, label="release evidence output directory")
    if _is_under(output_dir, repo_root.resolve()):
        raise ReleaseEvidenceError(
            "release evidence output directory must be outside the Git worktree"
        )
    parent_fd = _secure_open_directory(
        output_dir.parent, label="release evidence output parent path"
    )
    created = False
    directory_fd: int | None = None
    try:
        os.mkdir(output_dir.name, mode=0o700, dir_fd=parent_fd)
        created = True
        no_follow = getattr(os, "O_NOFOLLOW", None)
        if no_follow is None:  # pragma: no cover - _secure_open_directory checks this first.
            raise ReleaseEvidenceError("Linux O_NOFOLLOW is required for release evidence")
        directory_fd = os.open(
            output_dir.name,
            os.O_RDONLY | os.O_DIRECTORY | no_follow | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent_fd,
        )
        os.fchmod(directory_fd, 0o700)
        directory_stat = os.fstat(directory_fd)
        is_owner_only_directory = (
            stat.S_ISDIR(directory_stat.st_mode)
            and directory_stat.st_uid == os.getuid()
            and stat.S_IMODE(directory_stat.st_mode) == 0o700
        )
        if not is_owner_only_directory:
            raise ReleaseEvidenceError("release evidence output directory is not owner-only")
        return _OpenedOutputDirectory(
            path=output_dir,
            parent_fd=parent_fd,
            directory_fd=directory_fd,
            name=output_dir.name,
        )
    except FileExistsError as error:
        os.close(parent_fd)
        raise ReleaseEvidenceError("release evidence output directory already exists") from error
    except BaseException:
        if directory_fd is not None:
            os.close(directory_fd)
        if created:
            with contextlib.suppress(OSError):
                os.rmdir(output_dir.name, dir_fd=parent_fd)
        os.close(parent_fd)
        raise


def _write_owner_only(output: _OpenedOutputDirectory, name: str, payload: bytes) -> Path:
    if name not in _OUTPUT_FILENAMES:
        raise ReleaseEvidenceError("release evidence attempted to write an unexpected filename")
    no_follow = getattr(os, "O_NOFOLLOW", None)
    if no_follow is None:  # pragma: no cover - _secure_open_directory checks this first.
        raise ReleaseEvidenceError("Linux O_NOFOLLOW is required for release evidence")
    try:
        descriptor = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | no_follow | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=output.directory_fd,
        )
    except OSError as error:
        raise ReleaseEvidenceError(
            f"release evidence output could not be safely created: {name}"
        ) from error
    try:
        with os.fdopen(descriptor, "wb") as target:
            target.write(payload)
            target.flush()
            os.fsync(target.fileno())
            file_stat = os.fstat(target.fileno())
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(name, dir_fd=output.directory_fd)
        raise
    is_owner_only_file = (
        stat.S_ISREG(file_stat.st_mode)
        and file_stat.st_uid == os.getuid()
        and stat.S_IMODE(file_stat.st_mode) == 0o600
    )
    if not is_owner_only_file:
        raise ReleaseEvidenceError(f"release evidence output is not owner-only: {name}")
    return output.path / name


def _close_output_directory(output: _OpenedOutputDirectory) -> None:
    os.close(output.directory_fd)
    os.close(output.parent_fd)


def _cleanup_created_output(output: _OpenedOutputDirectory) -> None:
    failures: list[str] = []
    for name in _OUTPUT_FILENAMES:
        try:
            os.unlink(name, dir_fd=output.directory_fd)
        except FileNotFoundError:
            continue
        except OSError as error:
            failures.append(f"could not remove {name}: {error.strerror or error}")
    try:
        os.rmdir(output.name, dir_fd=output.parent_fd)
    except OSError as error:
        failures.append(f"could not remove output directory: {error.strerror or error}")
    finally:
        try:
            _close_output_directory(output)
        except OSError as error:
            failures.append(f"could not close output descriptor: {error.strerror or error}")
    if failures:
        raise ReleaseEvidenceError(
            f"release evidence cleanup left residual output at {output.path}: {'; '.join(failures)}"
        )


def build_release_evidence(
    *,
    repo_root: Path,
    output_dir: Path,
    image_artifacts: Sequence[ImageEvidenceInput],
    context: ReleaseBuildContext | None = None,
) -> ReleaseEvidenceResult:
    """Create a release manifest; ``context`` exists only for deterministic tests."""
    repository = repo_root.resolve(strict=True)
    effective_context = (
        _validated_context(context)
        if context is not None
        else ReleaseBuildContext(
            source_commit=derive_clean_git_source(repository), generated_at_utc=_utc_now()
        )
    )
    if not image_artifacts:
        raise ReleaseEvidenceError("at least one locally built product image is required")

    normalized_inputs: list[tuple[str, Path, Path]] = []
    seen_images: set[str] = set()
    for item in image_artifacts:
        reference = _validate_product_image_reference(item.reference)
        if reference in seen_images:
            raise ReleaseEvidenceError(f"duplicate product image reference: {reference}")
        seen_images.add(reference)
        if item.sbom_path is None or item.scanner_path is None:
            raise ReleaseEvidenceError(
                f"SBOM and scanner evidence are both required for {reference}"
            )
        sbom_path = item.sbom_path
        scanner_path = item.scanner_path
        if sbom_path == scanner_path:
            raise ReleaseEvidenceError(
                f"SBOM and scanner evidence must be separate files for {reference}"
            )
        normalized_inputs.append((reference, sbom_path, scanner_path))

    runtime_references = _runtime_image_references(repository, effective_context.source_commit)
    output = _create_output_directory(output_dir, repo_root=repository)
    try:
        product_images = [
            {
                "reference": reference,
                "sbom": _artifact_record(sbom_path, repo_root=repository, artifact_kind="sbom"),
                "scanner": _artifact_record(
                    scanner_path, repo_root=repository, artifact_kind="scanner"
                ),
            }
            for reference, sbom_path, scanner_path in sorted(normalized_inputs)
        ]
        manifest: dict[str, Any] = {
            "schemaVersion": _SCHEMA_VERSION,
            "generatedAtUtc": effective_context.generated_at_utc,
            "source": {"gitCommitSha": effective_context.source_commit},
            "productImages": product_images,
            "externalRuntimeImages": runtime_references,
        }
        manifest_bytes = _canonical_json(manifest)
        manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
        manifest_path = _write_owner_only(output, "release-evidence.json", manifest_bytes)
        sidecar = f"{manifest_sha256}  release-evidence.json\n".encode("ascii")
        sidecar_path = _write_owner_only(output, "release-evidence.json.sha256", sidecar)
        result = ReleaseEvidenceResult(
            output_dir=output.path,
            manifest_path=manifest_path,
            sidecar_path=sidecar_path,
            manifest_sha256=manifest_sha256,
        )
    except BaseException as error:
        try:
            _cleanup_created_output(output)
        except ReleaseEvidenceError as cleanup_error:
            raise cleanup_error from error
        raise
    _close_output_directory(output)
    return result


def _parse_image_artifact(values: Sequence[str]) -> ImageEvidenceInput:
    reference, sbom, scanner = values
    return ImageEvidenceInput(reference=reference, sbom_path=Path(sbom), scanner_path=Path(scanner))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--image-artifact",
        action="append",
        nargs=3,
        metavar=("IMAGE_REF", "CYCLONEDX_JSON", "SCANNER_JSON"),
        required=True,
        help="repeat once per locally built KSI product image",
    )
    arguments = parser.parse_args()
    try:
        result = build_release_evidence(
            repo_root=arguments.repo_root,
            output_dir=arguments.output_dir,
            image_artifacts=[_parse_image_artifact(values) for values in arguments.image_artifact],
        )
    except ReleaseEvidenceError as error:
        print(f"release evidence refused: {error}", file=sys.stderr)
        return 1
    print(f"release evidence written: {result.manifest_path}")
    print(f"release evidence sha256: {result.manifest_sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
