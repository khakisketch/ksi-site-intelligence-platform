"""Exact manifest selection uses manifest identity independently of V1 parser naming."""

import hashlib
import json
from pathlib import Path

import pytest
from ksi_event_contracts.inspector_execution_manifest import InspectorExecutionManifestV1
from ksi_processing_controller.external_inspector_catalog import (
    FileInspectorCatalogConfigV1,
    FileInspectorManifestCatalog,
    InspectorCatalogUnavailable,
)
from test_external_inspector_container_entrypoint import _envelope, _manifest


def catalog(
    tmp_path: Path,
) -> tuple[FileInspectorManifestCatalog, InspectorExecutionManifestV1, Path]:
    manifest = _manifest(_envelope())
    path = tmp_path / "manifest.json"
    path.write_text(manifest.model_dump_json(by_alias=True))
    path.chmod(0o600)
    revocations = tmp_path / "revocations.json"
    raw = json.dumps(
        {"version": "external-inspector-revocations.v1", "revokedManifestDigests": []}
    ).encode()
    revocations.write_bytes(raw)
    revocations.chmod(0o600)
    return (
        FileInspectorManifestCatalog(
            FileInspectorCatalogConfigV1(
                manifest_path=path,
                revocation_path=revocations,
                expected_revocation_sha256="sha256:" + hashlib.sha256(raw).hexdigest(),
            )
        ),
        manifest,
        path,
    )


def test_manifest_digest_lookup_preserves_resource_binding_and_v1_lookup(tmp_path: Path) -> None:
    store, manifest, _ = catalog(tmp_path)
    envelope = manifest.body.resource_envelope_digest
    assert (
        store.resolve_manifest_exact(
            execution_manifest_digest=manifest.canonical_body_digest(),
            resource_envelope_digest=envelope,
        )
        == manifest
    )
    assert (
        store.resolve_manifest_exact(
            execution_manifest_digest="sha256:" + "0" * 64, resource_envelope_digest=envelope
        )
        is None
    )
    assert (
        store.resolve_manifest_exact(
            execution_manifest_digest=manifest.canonical_body_digest(),
            resource_envelope_digest="sha256:" + "0" * 64,
        )
        is None
    )
    assert (
        store.resolve_exact(
            parser_build_digest=manifest.parser_build_digest, resource_envelope_digest=envelope
        )
        == manifest
    )


def test_manifest_lookup_reuses_pinned_operator_file_reader(tmp_path: Path) -> None:
    store, manifest, path = catalog(tmp_path)
    assert store.startup_status().available
    replacement = tmp_path / "replacement"
    replacement.write_bytes(path.read_bytes())
    replacement.chmod(0o600)
    replacement.replace(path)
    with pytest.raises(InspectorCatalogUnavailable):
        store.resolve_manifest_exact(
            execution_manifest_digest=manifest.canonical_body_digest(),
            resource_envelope_digest=manifest.body.resource_envelope_digest,
        )
