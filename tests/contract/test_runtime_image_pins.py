"""Production and synthetic runtime images must be immutable OCI references."""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_TOOL = _ROOT / "tools" / "check_runtime_image_pins.py"
_SUPPLY_CHAIN_FILES = (
    Path("Dockerfile"),
    Path("Dockerfile.worker"),
    Path("apps/dashboard/Dockerfile"),
    Path("edge/docker/manifold3-build.Dockerfile"),
    Path("deploy/compose.yaml"),
    Path("deploy/compose.vm.yaml"),
    Path("deploy/compose.synthetic-staging.yaml"),
    Path("deploy/bin/backup-vm.sh"),
    Path("deploy/bin/restore-check-vm.sh"),
)


def _tool() -> Any:
    spec = importlib.util.spec_from_file_location("check_runtime_image_pins", _TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _supply_chain_copy(tmp_path: Path) -> Path:
    root = tmp_path / "repository"
    for relative in _SUPPLY_CHAIN_FILES:
        source = _ROOT / relative
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    return root


def test_current_production_owned_runtime_images_are_pinned() -> None:
    assert _tool().check_runtime_image_pins(_ROOT) == []


def test_rejects_tag_only_compose_image_reference(tmp_path: Path) -> None:
    root = _supply_chain_copy(tmp_path)
    compose = root / "deploy/compose.yaml"
    compose.write_text(
        compose.read_text(encoding="utf-8") + "\n  image: redis:7\n",
        encoding="utf-8",
    )

    violations = _tool().check_runtime_image_pins(root)

    assert any(
        violation.path == Path("deploy/compose.yaml")
        and "no OCI digest" in violation.message
        and "redis:7" in violation.message
        for violation in violations
    )


def test_discovers_new_compose_file_instead_of_allowing_an_inventory_bypass(tmp_path: Path) -> None:
    root = _supply_chain_copy(tmp_path)
    extra_compose = root / "deploy/compose.production.yaml"
    extra_compose.write_text("services:\n  cache:\n    image: redis:7\n", encoding="utf-8")

    violations = _tool().check_runtime_image_pins(root)

    assert any(
        violation.path == Path("deploy/compose.production.yaml")
        and "no OCI digest" in violation.message
        and "redis:7" in violation.message
        for violation in violations
    )


def test_discovers_new_yml_compose_file_instead_of_allowing_an_inventory_bypass(
    tmp_path: Path,
) -> None:
    root = _supply_chain_copy(tmp_path)
    extra_compose = root / "deploy/compose.production.yml"
    extra_compose.write_text("services:\n  cache:\n    image: redis:7\n", encoding="utf-8")

    violations = _tool().check_runtime_image_pins(root)

    assert any(
        violation.path == Path("deploy/compose.production.yml")
        and "no OCI digest" in violation.message
        and "redis:7" in violation.message
        for violation in violations
    )


@pytest.mark.parametrize("relative", [Path("Dockerfile"), Path("deploy/compose.yaml")])
def test_required_runtime_file_symlink_is_refused_instead_of_silently_skipped(
    tmp_path: Path, relative: Path
) -> None:
    root = _supply_chain_copy(tmp_path)
    runtime_file = root / relative
    runtime_file.unlink()
    runtime_file.symlink_to(tmp_path / "outside-runtime-file")

    violations = _tool().check_runtime_image_pins(root)

    assert any(
        violation.path == relative and "must not be a symlink" in violation.message
        for violation in violations
    )


def test_new_matching_compose_symlink_is_refused_instead_of_silently_skipped(
    tmp_path: Path,
) -> None:
    root = _supply_chain_copy(tmp_path)
    extra_compose = root / "deploy/compose.production.yml"
    extra_compose.symlink_to(tmp_path / "outside-compose.yml")

    violations = _tool().check_runtime_image_pins(root)

    assert any(
        violation.path == Path("deploy/compose.production.yml")
        and "must not be a symlink" in violation.message
        for violation in violations
    )


def test_discovers_new_manifold_build_dockerfile_instead_of_allowing_a_bypass(
    tmp_path: Path,
) -> None:
    root = _supply_chain_copy(tmp_path)
    extra_dockerfile = root / "edge/docker/future-build.Dockerfile"
    extra_dockerfile.parent.mkdir(parents=True, exist_ok=True)
    extra_dockerfile.write_text("FROM ubuntu:20.04\n", encoding="utf-8")

    violations = _tool().check_runtime_image_pins(root)

    assert any(
        violation.path == Path("edge/docker/future-build.Dockerfile")
        and "no OCI digest" in violation.message
        and "ubuntu:20.04" in violation.message
        for violation in violations
    )


def test_rejects_tag_only_docker_run(tmp_path: Path) -> None:
    root = _supply_chain_copy(tmp_path)
    backup = root / "deploy/bin/backup-vm.sh"
    backup.write_text(
        backup.read_text(encoding="utf-8")
        + "\ndocker run --rm --name image-pin-test busybox:1.36 true\n",
        encoding="utf-8",
    )

    violations = _tool().check_runtime_image_pins(root)

    assert any(
        violation.path == Path("deploy/bin/backup-vm.sh")
        and "no OCI digest" in violation.message
        and "busybox:1.36" in violation.message
        for violation in violations
    )


def test_rejects_latest_even_when_an_oci_digest_is_present() -> None:
    tool = _tool()
    reference = "busybox:latest@sha256:" + "a" * 64

    violations = tool._validate_reference(reference, path=Path("Dockerfile"), line=1)

    assert [violation.message for violation in violations] == [
        f"runtime image must not use :latest: {reference}"
    ]


def test_rejects_digest_only_external_image_reference() -> None:
    tool = _tool()
    violations = tool._validate_reference(
        "example.invalid/worker@sha256:" + "a" * 64,
        path=Path("Dockerfile"),
        line=1,
    )

    assert [violation.message for violation in violations] == [
        "runtime image has no explicit version tag: example.invalid/worker@sha256:" + "a" * 64
    ]


def test_rejects_unpinned_external_copy_from_image(tmp_path: Path) -> None:
    root = _supply_chain_copy(tmp_path)
    dockerfile = root / "Dockerfile"
    dockerfile.write_text(
        dockerfile.read_text(encoding="utf-8")
        + "\nCOPY --from=ghcr.io/astral-sh/uv:0.11.15 /uv /bin/\n",
        encoding="utf-8",
    )

    violations = _tool().check_runtime_image_pins(root)

    assert any(
        violation.path == Path("Dockerfile")
        and "no OCI digest" in violation.message
        and "ghcr.io/astral-sh/uv:0.11.15" in violation.message
        for violation in violations
    )


def test_expected_multi_arch_digest_references_are_present() -> None:
    dockerfile = (_ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = (_ROOT / "deploy/compose.yaml").read_text(encoding="utf-8")
    python_reference = (
        "python:3.12.14-slim@sha256:"
        "09f7da3bc104798d0afb40bc08d23ab2da20a76130cec1f2ef170848f5d85217"
    )
    minio_reference = (
        "minio/minio:RELEASE.2025-09-07T16-13-09Z@sha256:"
        "14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e"
    )
    nodeodm_reference = (
        "opendronemap/nodeodm@sha256:"
        "cb07d06e21fd6189cfad287c6fedfa0b72568100355635cd9035cb86eed42ee2"
    )

    assert python_reference in dockerfile
    assert minio_reference in compose
    assert nodeodm_reference in compose
