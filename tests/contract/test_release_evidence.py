"""Release evidence is provenance, not a deployment or vulnerability approval."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator, FormatChecker

_ROOT = Path(__file__).resolve().parents[2]
_TOOL = _ROOT / "tools" / "build_release_evidence.py"
_RUNTIME_IMAGE_PINS = _ROOT / "tools" / "check_runtime_image_pins.py"
_SCHEMA = _ROOT / "contracts" / "schemas" / "release-evidence.v1.json"
_STAGE = _ROOT / "deploy" / "bin" / "external-runtime-stage.sh"
_REFERENCE = "ksi-core:2026.08.30.1@sha256:" + "a" * 64
_CONTEXT_SHA = subprocess.run(
    ["git", "rev-parse", "HEAD"],
    cwd=_ROOT,
    check=True,
    stdout=subprocess.PIPE,
    text=True,
).stdout.strip()
_CONTEXT_TIME = "2026-08-30T12:34:56Z"
_NODEODM_DIGEST_ONLY = "opendronemap/nodeodm@sha256:" + (
    "cb07d06e21fd6189cfad287c6fedfa0b72568100355635cd9035cb86eed42ee2"
)
_MODULE: Any | None = None
_PINNED_PYTHON = (
    "python:3.12.14-slim@sha256:09f7da3bc104798d0afb40bc08d23ab2da20a76130cec1f2ef170848f5d85217"
)


def _tool() -> Any:
    global _MODULE
    if _MODULE is not None:
        return _MODULE
    spec = importlib.util.spec_from_file_location("build_release_evidence", _TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    _MODULE = module
    return _MODULE


def _json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _candidate_compose_external_references() -> list[str]:
    result = subprocess.run(
        [sys.executable, str(_RUNTIME_IMAGE_PINS), "--root", str(_ROOT), "--references-json"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return sorted(
        {
            entry["reference"]
            for entry in json.loads(result.stdout)
            if entry["path"] == "deploy/compose.external-reconstruction.yaml"
        }
    )


def _inputs(tmp_path: Path) -> tuple[Path, Path]:
    sbom = _json(
        tmp_path / "release-inputs" / "ksi-core.cdx.json",
        {"bomFormat": "CycloneDX", "specVersion": "1.5", "components": [{"name": "not-recorded"}]},
    )
    scanner = _json(
        tmp_path / "release-inputs" / "ksi-core.scan.json",
        {"scanner": {"name": "example"}, "results": []},
    )
    return sbom, scanner


def _build(
    tmp_path: Path,
    *,
    output_name: str = "release-evidence",
    reference: str = _REFERENCE,
    sbom: Path | None = None,
    scanner: Path | None = None,
    output_dir: Path | None = None,
) -> Any:
    tool = _tool()
    default_sbom, default_scanner = _inputs(tmp_path)
    return tool.build_release_evidence(
        repo_root=_ROOT,
        output_dir=tmp_path / output_name if output_dir is None else output_dir,
        image_artifacts=[
            tool.ImageEvidenceInput(
                reference=reference,
                sbom_path=default_sbom if sbom is None else sbom,
                scanner_path=default_scanner if scanner is None else scanner,
            )
        ],
        context=tool.ReleaseBuildContext(
            source_commit=_CONTEXT_SHA,
            generated_at_utc=_CONTEXT_TIME,
        ),
    )


def _validator() -> Draft202012Validator:
    return Draft202012Validator(
        json.loads(_SCHEMA.read_text(encoding="utf-8")), format_checker=FormatChecker()
    )


def _commit_runtime_snapshot_repository(tmp_path: Path) -> tuple[Path, str]:
    """Commit a small valid pin-gate tree, then let callers alter the live tree."""
    repository = tmp_path / "runtime-snapshot-repository"
    repository.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"], cwd=repository, check=True
    )
    subprocess.run(["git", "config", "user.name", "KSI Test"], cwd=repository, check=True)
    (repository / "tools").mkdir()
    (repository / "tools" / "check_runtime_image_pins.py").write_bytes(
        (_ROOT / "tools" / "check_runtime_image_pins.py").read_bytes()
    )
    (repository / "Dockerfile").write_text(f"FROM {_PINNED_PYTHON}\n", encoding="utf-8")
    for relative in (
        "Dockerfile.worker",
        "Dockerfile.external-inspector",
        "Dockerfile.external-measurement",
        "apps/dashboard/Dockerfile",
        "deploy/compose.yaml",
        "deploy/compose.vm.yaml",
        "deploy/compose.synthetic-staging.yaml",
        "deploy/bin/backup-vm.sh",
        "deploy/bin/restore-check-vm.sh",
    ):
        path = repository / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n", encoding="utf-8")
    for relative in (
        "Dockerfile.external-inspector.dockerignore",
        "Dockerfile.external-measurement.dockerignore",
    ):
        path = repository / relative
        path.write_bytes((_ROOT / relative).read_bytes())
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-qm", "runtime snapshot"], cwd=repository, check=True)
    source_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout.strip()
    return repository, source_commit


def test_release_evidence_schema_is_valid_and_positive_manifest_is_canonical(
    tmp_path: Path,
) -> None:
    Draft202012Validator.check_schema(json.loads(_SCHEMA.read_text(encoding="utf-8")))

    result = _build(tmp_path)

    manifest_bytes = result.manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    validator = _validator()
    errors = list(validator.iter_errors(manifest))
    assert errors == []
    assert manifest["source"] == {"gitCommitSha": _CONTEXT_SHA}
    assert "gitCommitSha256" not in manifest["source"]
    assert manifest_bytes == (
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    assert result.sidecar_path.read_text(encoding="ascii") == (
        f"{result.manifest_sha256}  release-evidence.json\n"
    )
    assert stat.S_IMODE(os.lstat(result.output_dir).st_mode) == 0o700
    assert stat.S_IMODE(os.lstat(result.manifest_path).st_mode) == 0o600
    assert stat.S_IMODE(os.lstat(result.sidecar_path).st_mode) == 0o600
    assert str(tmp_path) not in manifest_bytes.decode("utf-8")
    assert "not-recorded" not in manifest_bytes.decode("utf-8")


def test_stage_consumes_the_canonical_generator_output_without_legacy_manifest_fields(
    tmp_path: Path,
) -> None:
    """The candidate gate consumes the producer's public v1 shape unchanged.

    Breaking change caught: rewriting the gate to read the old host-local
    ``sourceCommit``/``images`` shape rejects the output made by the canonical
    release-evidence generator before a Docker observation is even reached.
    Docker inspection is isolated below this contract test; its live binding is
    exercised separately by the staging deployment test.
    """
    tool = _tool()
    core_sbom, core_scanner = _inputs(tmp_path)
    dashboard_sbom = _json(
        tmp_path / "release-inputs" / "ksi-dashboard.cdx.json",
        {"bomFormat": "CycloneDX", "specVersion": "1.5", "components": []},
    )
    dashboard_scanner = _json(
        tmp_path / "release-inputs" / "ksi-dashboard.scan.json",
        {"scanner": {"name": "example"}, "results": [{"status": "clear"}]},
    )
    dashboard_reference = "ksi-dashboard:2026.09.10.1@sha256:" + "d" * 64
    evidence = tool.build_release_evidence(
        repo_root=_ROOT,
        output_dir=tmp_path / "release-evidence",
        image_artifacts=[
            tool.ImageEvidenceInput(_REFERENCE, core_sbom, core_scanner),
            tool.ImageEvidenceInput(dashboard_reference, dashboard_sbom, dashboard_scanner),
        ],
        context=tool.ReleaseBuildContext(_CONTEXT_SHA, _CONTEXT_TIME),
    )
    manifest = json.loads(evidence.manifest_path.read_text(encoding="utf-8"))
    runtime_sbom = _json(
        tmp_path / "release-inputs" / "runtime.cdx.json",
        {"bomFormat": "CycloneDX", "specVersion": "1.5", "components": [{"name": "runtime"}]},
    )
    runtime_scanner = _json(
        tmp_path / "release-inputs" / "runtime.scan.json",
        {"scanner": {"name": "example", "schemaVersion": "1.0"}, "results": []},
    )

    def observed(path: Path, artifact_type: str) -> dict[str, str | int]:
        return {
            "path": str(path),
            "sha256": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes": len(path.read_bytes()),
            "type": artifact_type,
        }

    def canonical_repo_digest(reference: str) -> str:
        if reference == _NODEODM_DIGEST_ONLY:
            return reference
        name_and_tag, digest = reference.rsplit("@", maxsplit=1)
        return name_and_tag.rsplit(":", maxsplit=1)[0] + "@" + digest

    candidate_external_references = _candidate_compose_external_references()
    assert len(candidate_external_references) == 3
    assert set(candidate_external_references).issubset(manifest["externalRuntimeImages"])
    external_bindings = [
        {
            "releaseReference": reference,
            "dockerImageId": "sha256:" + f"{index + 1:x}" * 64,
            "repoDigests": [canonical_repo_digest(reference)],
        }
        for index, reference in enumerate(candidate_external_references)
    ]
    binding = {
        "schemaVersion": "external-runtime-host-binding.v1",
        "releaseEvidence": {"sha256": "sha256:" + evidence.manifest_sha256},
        "source": {"gitCommitSha": _CONTEXT_SHA},
        "productImages": [
            {
                "component": component,
                "releaseReference": product["reference"],
                "dockerImageId": "sha256:" + image_digit * 64,
                "repoDigests": [canonical_repo_digest(product["reference"])],
                "sbom": observed(sbom, "cyclonedx-json"),
                "scanner": observed(scanner, "scanner-json"),
            }
            for component, product, sbom, scanner, image_digit in (
                ("core", manifest["productImages"][0], core_sbom, core_scanner, "a"),
                ("dashboard", manifest["productImages"][1], dashboard_sbom, dashboard_scanner, "b"),
            )
        ],
        "runtimeProducts": [
            {
                "role": "inspector",
                "releaseReference": "ksi-inspector:2026.09.10.1@sha256:" + "e" * 64,
                "dockerImageId": "sha256:" + "c" * 64,
                "repoDigests": ["ksi-inspector@sha256:" + "e" * 64],
                "sbom": observed(runtime_sbom, "cyclonedx-json"),
                "scanner": observed(runtime_scanner, "scanner-json"),
            },
            {
                "role": "measurement",
                "releaseReference": "ksi-measurement:2026.09.10.1@sha256:" + "f" * 64,
                "dockerImageId": "sha256:" + "d" * 64,
                "repoDigests": ["ksi-measurement@sha256:" + "f" * 64],
                "sbom": observed(runtime_sbom, "cyclonedx-json"),
                "scanner": observed(runtime_scanner, "scanner-json"),
            },
        ],
        "externalRuntimeImages": external_bindings,
    }
    binding_path = tmp_path / "host-binding.json"
    binding_path.write_text(json.dumps(binding, separators=(",", ":")), encoding="utf-8")
    binding_path.chmod(0o600)

    shell = r'''source "$1"
repo_dir="$2"
KSI_EXTERNAL_RC_RELEASE_EVIDENCE="$3"
KSI_EXTERNAL_RC_HOST_BINDING="$4"
expected_commit="$5"
git() {
  if [[ "$1" == "-C" && "$3" == "status" ]]; then return 0; fi
  if [[ "$1" == "-C" && "$3" == "rev-parse" && "$4" == "HEAD" ]]; then
    printf '%s\n' "$expected_commit"
    return 0
  fi
  command git "$@"
}
verify_product_image_binding() { return 0; }
verify_image_binding() { return 0; }
verify_observed_repo_digests() { return 0; }
require_release_evidence
'''
    result = subprocess.run(
        [
            "bash",
            "-c",
            shell,
            "bash",
            str(_STAGE),
            str(_ROOT),
            str(evidence.manifest_path),
            str(binding_path),
            _CONTEXT_SHA,
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_schema_refuses_the_legacy_misnamed_git_commit_hash_field(tmp_path: Path) -> None:
    result = _build(tmp_path)
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    manifest["source"] = {"gitCommitSha256": _CONTEXT_SHA}
    validator = _validator()

    errors = list(validator.iter_errors(manifest))

    assert errors
    assert any(error.validator in {"required", "additionalProperties"} for error in errors)


@pytest.mark.parametrize(
    "timestamp",
    [
        "2026-08-30T12:34:56+00:00",
        "2026-08-30T12:34:56.000Z",
        "not-a-timestamp",
    ],
)
def test_schema_requires_canonical_utc_timestamp_and_format_checking(
    tmp_path: Path, timestamp: str
) -> None:
    result = _build(tmp_path)
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    manifest["generatedAtUtc"] = timestamp

    assert list(_validator().iter_errors(manifest))


def test_generator_refuses_noncanonical_utc_timestamp_before_creating_output(
    tmp_path: Path,
) -> None:
    tool = _tool()
    sbom, scanner = _inputs(tmp_path)
    output = tmp_path / "noncanonical-timestamp"

    with pytest.raises(tool.ReleaseEvidenceError, match="canonical UTC"):
        tool.build_release_evidence(
            repo_root=_ROOT,
            output_dir=output,
            image_artifacts=[tool.ImageEvidenceInput(_REFERENCE, sbom, scanner)],
            context=tool.ReleaseBuildContext(_CONTEXT_SHA, "2026-08-30T12:34:56+00:00"),
        )

    assert not output.exists()


@pytest.mark.parametrize(
    "reference",
    [
        "not-ksi-core:2026.08.30.1@sha256:" + "a" * 64,
        "ksi-core:stable@sha256:" + "a" * 64,
        "ksi-core:release@sha256:" + "a" * 64,
        "ksi-core@sha256:" + "a" * 64,
    ],
)
def test_schema_enforces_exact_nonfloating_ksi_product_image_references(
    tmp_path: Path, reference: str
) -> None:
    result = _build(tmp_path)
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    manifest["productImages"][0]["reference"] = reference
    validator = _validator()

    errors = list(validator.iter_errors(manifest))

    assert errors


@pytest.mark.parametrize(
    "reference",
    [
        "ubuntu@sha256:" + "a" * 64,
        "ubuntu:latest@sha256:" + "a" * 64,
        "ubuntu:stable@sha256:" + "a" * 64,
    ],
)
def test_schema_enforces_external_runtime_version_tag_or_nodeodm_exception(
    tmp_path: Path, reference: str
) -> None:
    result = _build(tmp_path)
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    manifest["externalRuntimeImages"] = [reference]
    validator = _validator()

    assert list(validator.iter_errors(manifest))

    manifest["externalRuntimeImages"] = [_NODEODM_DIGEST_ONLY]
    assert list(validator.iter_errors(manifest)) == []


@pytest.mark.parametrize(
    "reference",
    [
        "ubuntu@sha256:" + "a" * 64,
        "ubuntu:latest@sha256:" + "a" * 64,
        "ubuntu:stable@sha256:" + "a" * 64,
    ],
)
def test_generator_enforces_the_same_external_runtime_reference_boundary(reference: str) -> None:
    tool = _tool()

    with pytest.raises(tool.ReleaseEvidenceError, match="non-floating version tag"):
        tool._validate_external_runtime_image_reference(reference)

    assert (
        tool._validate_external_runtime_image_reference(_NODEODM_DIGEST_ONLY)
        == _NODEODM_DIGEST_ONLY
    )


def test_fixed_internal_context_produces_the_same_manifest_digest(tmp_path: Path) -> None:
    first = _build(tmp_path, output_name="first")
    second = _build(tmp_path, output_name="second")

    assert first.manifest_sha256 == second.manifest_sha256
    assert first.manifest_path.read_bytes() == second.manifest_path.read_bytes()
    assert first.sidecar_path.read_bytes() == second.sidecar_path.read_bytes()


def test_runtime_refs_are_scanned_from_the_exact_source_commit_not_live_worktree(
    tmp_path: Path,
) -> None:
    tool = _tool()
    repository, source_commit = _commit_runtime_snapshot_repository(tmp_path)
    (repository / "Dockerfile").write_text("FROM python:latest\n", encoding="utf-8")

    references = tool._runtime_image_references(repository, source_commit)

    assert references == [_PINNED_PYTHON]


@pytest.mark.parametrize("mutation", ["missing", "relaxed"])
def test_release_snapshot_rejects_missing_or_relaxed_runtime_context_allowlist(
    tmp_path: Path, mutation: str
) -> None:
    tool = _tool()
    repository, _source_commit = _commit_runtime_snapshot_repository(tmp_path)
    allowlist = repository / "Dockerfile.external-inspector.dockerignore"
    if mutation == "missing":
        allowlist.unlink()
    else:
        allowlist.write_text(
            allowlist.read_text(encoding="utf-8") + "!download/**\n", encoding="utf-8"
        )
    subprocess.run(["git", "add", "-A"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-qm", f"{mutation} allowlist"], cwd=repository, check=True)
    source_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout.strip()

    with pytest.raises(tool.ReleaseEvidenceError, match="exact source tree"):
        tool._runtime_image_references(repository, source_commit)


def test_dirty_git_source_is_refused_by_the_derived_source_boundary(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"], cwd=repository, check=True
    )
    subprocess.run(["git", "config", "user.name", "KSI Test"], cwd=repository, check=True)
    (repository / "tracked.txt").write_text("clean\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=repository, check=True)

    tool = _tool()
    assert len(tool.derive_clean_git_source(repository)) == 40
    (repository / "tracked.txt").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(tool.ReleaseEvidenceError, match="dirty Git worktree"):
        tool.derive_clean_git_source(repository)


def test_symlink_artifact_is_refused_and_partial_output_is_removed(tmp_path: Path) -> None:
    tool = _tool()
    sbom, scanner = _inputs(tmp_path)
    linked_sbom = tmp_path / "release-inputs" / "linked.cdx.json"
    try:
        linked_sbom.symlink_to(sbom)
    except OSError as error:  # pragma: no cover - all supported Linux runners allow it.
        pytest.skip(f"symlinks unavailable: {error}")

    with pytest.raises(tool.ReleaseEvidenceError, match="symlink"):
        _build(tmp_path, output_name="must-clean", sbom=linked_sbom, scanner=scanner)

    assert not (tmp_path / "must-clean").exists()


def test_input_path_swap_to_symlink_is_refused_on_the_final_descriptor_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _tool()
    sbom, scanner = _inputs(tmp_path)
    replacement = tmp_path / "replacement.cdx.json"
    replacement.write_text('{"bomFormat":"CycloneDX","specVersion":"1.5"}', encoding="utf-8")
    original_open = tool.os.open
    swapped = False

    def swap_then_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        nonlocal swapped
        if path == sbom.name and kwargs.get("dir_fd") is not None and not swapped:
            swapped = True
            sbom.unlink()
            sbom.symlink_to(replacement)
        return cast(int, original_open(path, flags, *args, **kwargs))

    monkeypatch.setattr(tool.os, "open", swap_then_open)
    with pytest.raises(tool.ReleaseEvidenceError, match="symlink"):
        _build(tmp_path, output_name="path-swap", sbom=sbom, scanner=scanner)

    assert swapped
    assert not (tmp_path / "path-swap").exists()


def test_output_parent_symlink_and_preexisting_output_symlink_are_refused(tmp_path: Path) -> None:
    tool = _tool()
    real_parent = tmp_path / "real-output-parent"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked-output-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)

    with pytest.raises(tool.ReleaseEvidenceError, match="symlinked path component"):
        _build(tmp_path, output_dir=linked_parent / "release")

    output = tool._create_output_directory(tmp_path / "direct-output", repo_root=_ROOT)
    try:
        (output.path / "release-evidence.json").symlink_to(tmp_path / "outside-manifest.json")
        with pytest.raises(tool.ReleaseEvidenceError, match="safely created"):
            tool._write_owner_only(output, "release-evidence.json", b"{}\n")
    finally:
        tool._cleanup_created_output(output)


def test_malformed_and_oversized_json_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _tool()
    malformed = tmp_path / "release-inputs" / "bad.cdx.json"
    malformed.parent.mkdir(parents=True)
    malformed.write_text("{not-json", encoding="utf-8")
    _, scanner = _inputs(tmp_path)

    with pytest.raises(tool.ReleaseEvidenceError, match="not valid JSON"):
        _build(tmp_path, output_name="malformed", sbom=malformed, scanner=scanner)
    assert not (tmp_path / "malformed").exists()

    monkeypatch.setattr(tool, "_MAX_JSON_BYTES", 8)
    oversized = _json(
        tmp_path / "release-inputs" / "large.cdx.json",
        {"bomFormat": "CycloneDX", "specVersion": "1.5"},
    )
    with pytest.raises(tool.ReleaseEvidenceError, match="unsafe JSON size"):
        _build(tmp_path, output_name="oversized", sbom=oversized, scanner=scanner)
    assert not (tmp_path / "oversized").exists()


def test_empty_scanner_object_is_refused(tmp_path: Path) -> None:
    tool = _tool()
    empty_scanner = _json(tmp_path / "release-inputs" / "empty.scan.json", {})

    with pytest.raises(tool.ReleaseEvidenceError, match="must not be an empty JSON object"):
        _build(tmp_path, output_name="empty-scanner", scanner=empty_scanner)

    assert not (tmp_path / "empty-scanner").exists()


def test_cleanup_failure_reports_residual_output_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _tool()
    empty_scanner = _json(tmp_path / "release-inputs" / "empty.scan.json", {})
    output = tmp_path / "cleanup-residual"
    original_rmdir = tool.os.rmdir

    def deny_output_removal(path: Any, *args: Any, **kwargs: Any) -> None:
        if path == output.name and kwargs.get("dir_fd") is not None:
            raise PermissionError("test cleanup denial")
        original_rmdir(path, *args, **kwargs)

    monkeypatch.setattr(tool.os, "rmdir", deny_output_removal)
    with pytest.raises(tool.ReleaseEvidenceError, match="cleanup left residual output") as error:
        _build(tmp_path, output_dir=output, scanner=empty_scanner)

    assert str(output) in str(error.value)
    assert output.is_dir()


@pytest.mark.parametrize(
    "reference",
    [
        "ksi-core:2026.08.30.1",
        "ksi-core@sha256:" + "a" * 64,
        "ksi-core:latest@sha256:" + "a" * 64,
    ],
)
def test_tag_only_digest_only_and_floating_image_syntax_are_refused(
    tmp_path: Path, reference: str
) -> None:
    tool = _tool()

    with pytest.raises(tool.ReleaseEvidenceError):
        _build(tmp_path, reference=reference)


def test_missing_sbom_or_scanner_pair_is_refused(tmp_path: Path) -> None:
    tool = _tool()
    sbom, _scanner = _inputs(tmp_path)
    output = tmp_path / "missing-pair"

    with pytest.raises(tool.ReleaseEvidenceError, match="both required"):
        tool.build_release_evidence(
            repo_root=_ROOT,
            output_dir=output,
            image_artifacts=[tool.ImageEvidenceInput(_REFERENCE, sbom, None)],
            context=tool.ReleaseBuildContext(_CONTEXT_SHA, _CONTEXT_TIME),
        )

    assert not output.exists()


def test_internal_worktree_artifact_and_existing_output_are_refused(tmp_path: Path) -> None:
    tool = _tool()
    _sbom, scanner = _inputs(tmp_path)

    with pytest.raises(tool.ReleaseEvidenceError, match="outside the Git worktree"):
        _build(
            tmp_path,
            output_name="internal-artifact",
            sbom=_SCHEMA,
            scanner=scanner,
        )
    assert not (tmp_path / "internal-artifact").exists()

    existing = tmp_path / "existing-output"
    existing.mkdir()
    with pytest.raises(tool.ReleaseEvidenceError, match="already exists"):
        _build(tmp_path, output_name="existing-output")
