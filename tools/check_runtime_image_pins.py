#!/usr/bin/env python3
"""Fail closed when a production-owned runtime image can drift by tag.

This intentionally does not inspect reference repositories or arbitrary developer
Dockerfiles.  It covers the Docker build inputs, deployment assemblies, and VM
backup/restore helpers that form the current KSI runtime supply chain.
"""

from __future__ import annotations

import argparse
import re
import shlex
import stat
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

_REQUIRED_BASELINE_FILES = (
    Path("Dockerfile"),
    Path("Dockerfile.worker"),
    Path("Dockerfile.external-inspector"),
    Path("Dockerfile.external-inspector.dockerignore"),
    Path("Dockerfile.external-measurement"),
    Path("Dockerfile.external-measurement.dockerignore"),
    Path("apps/dashboard/Dockerfile"),
    Path("deploy/compose.yaml"),
    Path("deploy/compose.vm.yaml"),
    Path("deploy/compose.synthetic-staging.yaml"),
    Path("deploy/bin/backup-vm.sh"),
    Path("deploy/bin/restore-check-vm.sh"),
)
_EXTERNAL_RUNTIME_CONTEXT_FILES = (
    Path("Dockerfile.external-inspector.dockerignore"),
    Path("Dockerfile.external-measurement.dockerignore"),
)
_EXTERNAL_RUNTIME_CONTEXT_RULES = (
    "**",
    "!pyproject.toml",
    "!uv.lock",
    "!packages/",
    "!packages/*/",
    "!packages/*/pyproject.toml",
    "!packages/*/src/",
    "!packages/*/src/**",
    "!services/",
    "!services/*/",
    "!services/*/pyproject.toml",
    "!services/*/src/",
    "!services/*/src/**",
)
_LOCAL_BUILD_IMAGES = frozenset(
    {
        "ksi-phase2-core:local",
        "ksi-phase2-dashboard:local",
        # Private RC images are built from a clean reviewed checkout, then bound
        # to exact Docker image IDs, the source commit, SBOM, and scanner output.
        "ksi-external-rc-core:local",
        "ksi-external-rc-dashboard:local",
    }
)
_DIGEST_ONLY_EXCEPTIONS = frozenset(
    {
        # NodeODM's approved multi-arch manifest has no matching immutable upstream
        # release tag.  Its NodeODM/ODM versions are independently checked through
        # the processing profile and /info contract; accepting a made-up tag here
        # would weaken, rather than strengthen, provenance.
        "opendronemap/nodeodm@sha256:cb07d06e21fd6189cfad287c6fedfa0b72568100355635cd9035cb86eed42ee2"
    }
)
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_FROM = re.compile(
    r"^\s*FROM(?:\s+--[^\s]+)*\s+(?P<reference>[^\s]+)(?:\s+AS\s+(?P<stage>[^\s]+))?\s*$",
    re.IGNORECASE,
)
_COPY_FROM = re.compile(r"--from(?:=|\s+)(?P<source>[^\s]+)", re.IGNORECASE)
_COMPOSE_IMAGE = re.compile(r"^\s*image:\s*(?P<reference>[^\s#][^#]*?)\s*$")
_OPTIONS_WITH_VALUE = frozenset(
    {
        "--add-host",
        "--annotation",
        "--blkio-weight",
        "--cgroup-parent",
        "--cidfile",
        "--cpus",
        "--entrypoint",
        "--env",
        "--env-file",
        "--hostname",
        "--label",
        "--label-file",
        "--log-driver",
        "--log-opt",
        "--memory",
        "--memory-reservation",
        "--name",
        "--network",
        "--platform",
        "--publish",
        "--runtime",
        "--security-opt",
        "--shm-size",
        "--user",
        "--volume",
        "--volumes-from",
        "--workdir",
        "-e",
        "-h",
        "-l",
        "-m",
        "-p",
        "-u",
        "-v",
        "-w",
    }
)


@dataclass(frozen=True)
class Violation:
    path: Path
    line: int
    message: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.message}"


@dataclass(frozen=True, order=True)
class RuntimeImageReference:
    """One external image reference found in a product-owned runtime file."""

    path: Path
    line: int
    reference: str


def _validate_reference(reference: str, *, path: Path, line: int) -> list[Violation]:
    """Return syntax and policy violations for one external image reference."""
    if reference in _LOCAL_BUILD_IMAGES:
        return []
    if "$" in reference or "${" in reference:
        return [
            Violation(
                path,
                line,
                "runtime image must be a literal version+digest reference, not substitution: "
                f"{reference}",
            )
        ]

    base, separator, digest = reference.rpartition("@")
    if not separator:
        return [Violation(path, line, f"runtime image has no OCI digest: {reference}")]
    if not _DIGEST.fullmatch(digest):
        return [Violation(path, line, f"runtime image has invalid sha256 digest: {reference}")]
    if reference in _DIGEST_ONLY_EXCEPTIONS:
        return []

    image_name = base.rsplit("/", 1)[-1]
    tag_separator = image_name.rfind(":")
    if tag_separator <= 0 or tag_separator == len(image_name) - 1:
        return [Violation(path, line, f"runtime image has no explicit version tag: {reference}")]
    tag = image_name[tag_separator + 1 :]
    if tag.lower() == "latest":
        return [Violation(path, line, f"runtime image must not use :latest: {reference}")]
    return []


def _read_lines(root: Path, relative: Path, violations: list[Violation]) -> list[str] | None:
    path = root / relative
    if not path.is_file():
        violations.append(Violation(relative, 1, "required runtime supply-chain file is missing"))
        return None
    return path.read_text(encoding="utf-8").splitlines()


def _record_reference(
    reference: str,
    *,
    path: Path,
    line: int,
    violations: list[Violation],
    references: list[RuntimeImageReference] | None,
) -> None:
    if reference in _LOCAL_BUILD_IMAGES:
        return
    violations.extend(_validate_reference(reference, path=path, line=line))
    if references is not None:
        references.append(RuntimeImageReference(path=path, line=line, reference=reference))


def _scan_dockerfile(
    root: Path,
    relative: Path,
    violations: list[Violation],
    references: list[RuntimeImageReference] | None,
) -> None:
    lines = _read_lines(root, relative, violations)
    if lines is None:
        return

    stages: set[str] = set()
    for _number, source in enumerate(lines, start=1):
        match = _FROM.match(source)
        if match and match.group("stage"):
            stages.add(match.group("stage").lower())

    for number, source in enumerate(lines, start=1):
        match = _FROM.match(source)
        if match:
            _record_reference(
                match.group("reference"),
                path=relative,
                line=number,
                violations=violations,
                references=references,
            )
            continue
        if not source.lstrip().upper().startswith("COPY "):
            continue
        source_match = _COPY_FROM.search(source)
        if source_match is None:
            continue
        reference = source_match.group("source")
        if reference.lower() not in stages:
            _record_reference(
                reference,
                path=relative,
                line=number,
                violations=violations,
                references=references,
            )


def _compose_reference(raw: str) -> str:
    value = raw.strip()
    if value[:1] in {"'", '"'} and value[-1:] == value[:1]:
        return value[1:-1]
    return value.split(" #", 1)[0].strip()


def _scan_compose(
    root: Path,
    relative: Path,
    violations: list[Violation],
    references: list[RuntimeImageReference] | None,
) -> None:
    lines = _read_lines(root, relative, violations)
    if lines is None:
        return
    for number, source in enumerate(lines, start=1):
        match = _COMPOSE_IMAGE.match(source)
        if match:
            _record_reference(
                _compose_reference(match.group("reference")),
                path=relative,
                line=number,
                violations=violations,
                references=references,
            )


def _logical_shell_lines(lines: Iterable[str]) -> Iterable[tuple[int, str]]:
    start = 1
    fragments: list[str] = []
    for number, source in enumerate(lines, start=1):
        stripped = source.rstrip()
        if not fragments:
            start = number
        if stripped.endswith("\\"):
            fragments.append(stripped[:-1])
            continue
        fragments.append(stripped)
        yield start, " ".join(fragments)
        fragments = []
    if fragments:
        yield start, " ".join(fragments)


def _docker_run_image(command: str) -> str | None:
    try:
        tokens = shlex.split(command, comments=True)
    except ValueError:
        return None
    for index in range(len(tokens) - 1):
        if tokens[index : index + 2] == ["docker", "run"]:
            arguments = tokens[index + 2 :]
            cursor = 0
            while cursor < len(arguments):
                token = arguments[cursor]
                if token == "--":
                    return arguments[cursor + 1] if cursor + 1 < len(arguments) else None
                if token.startswith("--") and "=" in token:
                    cursor += 1
                    continue
                if token in _OPTIONS_WITH_VALUE:
                    cursor += 2
                    continue
                if token.startswith("-"):
                    cursor += 1
                    continue
                return token
    return None


def _scan_shell(
    root: Path,
    relative: Path,
    violations: list[Violation],
    references: list[RuntimeImageReference] | None,
) -> None:
    lines = _read_lines(root, relative, violations)
    if lines is None:
        return
    for number, command in _logical_shell_lines(lines):
        if "docker run" not in command:
            continue
        reference = _docker_run_image(command)
        if reference is None:
            violations.append(Violation(relative, number, "could not determine docker run image"))
            continue
        _record_reference(
            reference,
            path=relative,
            line=number,
            violations=violations,
            references=references,
        )


def _regular_discovered_files(
    root: Path, pattern: str, violations: list[Violation]
) -> tuple[Path, ...]:
    """Return regular matching files and fail closed for every symlink/special file."""
    regular_files: list[Path] = []
    for path in sorted(root.glob(pattern)):
        relative = path.relative_to(root)
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            violations.append(
                Violation(relative, 1, "runtime supply-chain file disappeared during scan")
            )
            continue
        if stat.S_ISLNK(metadata.st_mode):
            violations.append(
                Violation(relative, 1, "runtime supply-chain file must not be a symlink")
            )
            continue
        if not stat.S_ISREG(metadata.st_mode):
            violations.append(Violation(relative, 1, "runtime supply-chain file must be regular"))
            continue
        regular_files.append(relative)
    return tuple(regular_files)


def _validate_required_baseline(root: Path, violations: list[Violation]) -> None:
    for required in _REQUIRED_BASELINE_FILES:
        path = root / required
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            violations.append(
                Violation(required, 1, "required runtime supply-chain file is missing")
            )
            continue
        if stat.S_ISLNK(metadata.st_mode):
            violations.append(
                Violation(required, 1, "required runtime supply-chain file must not be a symlink")
            )
        elif not stat.S_ISREG(metadata.st_mode):
            violations.append(
                Violation(required, 1, "required runtime supply-chain file must be regular")
            )


def _validate_external_runtime_context_allowlists(
    root: Path, violations: list[Violation]
) -> None:
    for relative in _EXTERNAL_RUNTIME_CONTEXT_FILES:
        lines = _read_lines(root, relative, violations)
        if lines is None:
            continue
        if tuple(lines) != _EXTERNAL_RUNTIME_CONTEXT_RULES:
            violations.append(
                Violation(
                    relative,
                    1,
                    "external runtime build-context allowlist differs from the closed baseline",
                )
            )


def _scan_runtime_files(
    root: Path, references: list[RuntimeImageReference] | None = None
) -> list[Violation]:
    """Discover product-owned runtime files and inspect every matching source."""
    violations: list[Violation] = []
    _validate_required_baseline(root, violations)
    _validate_external_runtime_context_allowlists(root, violations)

    for relative in _regular_discovered_files(root, "Dockerfile*", violations):
        _scan_dockerfile(root, relative, violations, references)
    for relative in _regular_discovered_files(root, "apps/*/Dockerfile*", violations):
        _scan_dockerfile(root, relative, violations, references)
    for relative in _regular_discovered_files(root, "services/*/Dockerfile*", violations):
        _scan_dockerfile(root, relative, violations, references)
    for relative in _regular_discovered_files(root, "workers/*/Dockerfile*", violations):
        _scan_dockerfile(root, relative, violations, references)
    for relative in _regular_discovered_files(root, "edge/docker/*Dockerfile", violations):
        _scan_dockerfile(root, relative, violations, references)
    for relative in _regular_discovered_files(root, "deploy/compose*.yaml", violations):
        _scan_compose(root, relative, violations, references)
    for relative in _regular_discovered_files(root, "deploy/compose*.yml", violations):
        _scan_compose(root, relative, violations, references)
    for relative in _regular_discovered_files(root, "deploy/bin/*.sh", violations):
        _scan_shell(root, relative, violations, references)
    return violations


def check_runtime_image_pins(root: Path) -> list[Violation]:
    """Inspect all production-owned external runtime image references."""
    return _scan_runtime_files(root)


def runtime_image_references(root: Path) -> tuple[RuntimeImageReference, ...]:
    """Return validated, exact external runtime refs for release evidence binding.

    The function deliberately refuses to return a partial inventory.  Consumers
    must not produce a release manifest if the same source tree fails the pin
    gate that defines its runtime supply-chain boundary.
    """
    references: list[RuntimeImageReference] = []
    violations = _scan_runtime_files(root, references)
    if violations:
        detail = "; ".join(violation.render() for violation in violations)
        raise ValueError(f"runtime image pin validation failed: {detail}")
    return tuple(sorted(set(references)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root to inspect (default: this script's repository)",
    )
    arguments = parser.parse_args()
    violations = check_runtime_image_pins(arguments.root.resolve())
    if violations:
        for violation in violations:
            print(violation.render(), file=sys.stderr)
        return 1
    print("runtime image pins: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
