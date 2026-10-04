"""Tiny synthetic OCI evidence graphs; never images, authority or release evidence."""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

INDEX = "application/vnd.oci.image.index.v1+json"
MANIFEST = "application/vnd.oci.image.manifest.v1+json"
CONFIG = "application/vnd.oci.image.config.v1+json"
LAYER = "application/vnd.oci.image.layer.v1.tar+gzip"
ATTESTATION = "application/vnd.in-toto+json"


def digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def tar_payload(members: list[tuple[str, bytes]]) -> bytes:
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for name, payload in members:
            node = tarfile.TarInfo(name)
            node.size = len(payload)
            node.mode = 0o400
            archive.addfile(node, io.BytesIO(payload))
    return stream.getvalue()


@dataclass(frozen=True)
class OciFixture:
    payload: bytes
    index_id: str
    config_id: str
    source_commit: str
    role: str
    members: tuple[tuple[str, bytes], ...]


def make_oci_fixture(
    role: str, source_commit: str, *,
    mutate: Callable[[str, dict[str, Any]], bytes | None] | None = None,
) -> OciFixture:
    members: list[tuple[str, bytes]] = []

    def encode(stage: str, value: dict[str, Any]) -> bytes:
        raw = mutate(stage, value) if mutate else None
        return raw if raw is not None else json.dumps(value, separators=(",", ":")).encode()

    def blob(media: str, payload: bytes) -> dict[str, Any]:
        sha = digest(payload)
        members.append(("blobs/sha256/" + sha[7:], payload))
        return {"mediaType": media, "digest": sha, "size": len(payload)}

    layer = blob(LAYER, b"opaque synthetic compressed layer; do not decode")
    config = blob(CONFIG, encode("config", {
        "os": "linux", "architecture": "arm64",
        "config": {
            "User": f"ksi-{role}-image",
            "Cmd": [f"/app/.venv/bin/ksi-external-{role}-entrypoint"],
            "Labels": {"org.opencontainers.image.revision": source_commit},
        },
        "rootfs": {"type": "layers", "diff_ids": ["sha256:" + "1" * 64]},
    }))
    runtime = blob(MANIFEST, encode("manifest", {
        "schemaVersion": 2, "mediaType": MANIFEST, "config": config, "layers": [layer],
    }))
    runtime["platform"] = {"os": "linux", "architecture": "arm64"}
    attestation_config = blob(CONFIG, b'{"os":"unknown","architecture":"unknown"}')
    attestation_layer = blob(ATTESTATION, b'{"synthetic":true,"signatureVerified":false}')
    attestation = blob(MANIFEST, encode("attestation", {
        "schemaVersion": 2, "mediaType": MANIFEST,
        "config": attestation_config, "layers": [attestation_layer],
    }))
    attestation["platform"] = {"os": "unknown", "architecture": "unknown"}
    index = blob(INDEX, encode("nested_index", {
        "schemaVersion": 2, "mediaType": INDEX, "manifests": [runtime, attestation],
    }))
    members.append(("index.json", encode("index", {
        "schemaVersion": 2, "mediaType": INDEX, "manifests": [index],
    })))
    members.append(("oci-layout", encode("layout", {"imageLayoutVersion": "1.0.0"})))
    return OciFixture(
        tar_payload(members), index["digest"], config["digest"], source_commit, role,
        tuple(members),
    )
