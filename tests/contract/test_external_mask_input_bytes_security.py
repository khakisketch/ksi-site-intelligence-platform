"""Mask byte-store security negatives: closed journals, immutability, safe paths.

Synthetic bytes only.  Every test drives the real
``ExternalMaskInputByteStore``; no fakes stand in for the store itself.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime

import pytest
from ksi_core.domains.external.ingress.external_mask_input_bytes import (
    ExternalMaskInputByteStore,
    MaskByteStoreRecoveryError,
)
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.foundation.durable_journal import DurableJournal
from ksi_core.identity.auth import Principal, PrincipalKind, Role
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import ResourceEnvelopeV1

NOW = datetime(2026, 10, 26, tzinfo=UTC)


def _digest(value: str | bytes) -> str:
    raw = value.encode() if isinstance(value, str) else value
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _envelope() -> ResourceEnvelopeV1:
    return ResourceEnvelopeV1(
        max_input_bytes=4000000,
        max_streamed_bytes=4000000,
        max_tiff_directories=8,
        max_tiff_entries=128,
        max_pixels=1000000,
        max_bands=4,
        max_blocks=512,
        max_decompressed_bytes=20000000,
        max_sample_bytes=4000000,
        max_geometry_vertices=64,
        max_cpu_seconds=30.0,
        max_memory_bytes=50000000,
        max_workspace_bytes=50000000,
        max_output_bytes=1000000,
        max_tenant_concurrency=2,
        max_queue_depth=4,
        max_deadline_seconds=60.0,
        lease_duration_seconds=10.0,
        max_retry_attempts=2,
    ).sealed()


def _operator() -> Principal:
    return Principal("operator-a", PrincipalKind.OPERATOR, Role.ADMIN, None, "org-a")


def _store(tmp_path, name: str = "bytes") -> ExternalMaskInputByteStore:
    return ExternalMaskInputByteStore(
        DurableJournal(tmp_path / f"{name}.journal"),
        tmp_path / name,
        resource_envelope=_envelope(),
        clock=lambda: NOW,
        coordinator=ExternalAuthorityCurrentnessCoordinator(),
    )


def _grant(store: ExternalMaskInputByteStore, data: bytes, child: str = "child-1"):
    return store.issue_grant(
        principal=_operator(),
        organization_id="org-a",
        site_id="site-a",
        work_area_id="work-area-a",
        mask_child_id=child,
        mask_artifact_id="mask-artifact-1",
        subject_digest=_digest("parent-subject"),
        declared_sha256=_digest(data),
        declared_size_bytes=len(data),
        now=NOW,
    )


def test_oversized_declared_bytes_rejected_at_grant_time(tmp_path) -> None:
    """The declared cap is enforced before any upload bytes exist."""
    store = _store(tmp_path)
    with pytest.raises(ValueError, match="finite byte cap"):
        store.issue_grant(
            principal=_operator(),
            organization_id="org-a",
            site_id="site-a",
            work_area_id="work-area-a",
            mask_child_id="child-1",
            mask_artifact_id="mask-artifact-1",
            subject_digest=_digest("parent-subject"),
            declared_sha256=_digest("b"),
            declared_size_bytes=9_999_999,
            now=NOW,
        )


def test_sealed_overwrite_rejected_and_original_bytes_intact(tmp_path) -> None:
    store = _store(tmp_path)
    first = bytes(i % 251 for i in range(64))
    grant = _grant(store, first)
    store.complete_upload(grant_id=grant.grant_id, data=first, principal=_operator(), now=NOW)
    target = store.sealed_object_path(
        organization_id="org-a",
        site_id="site-a",
        mask_child_id="child-1",
        mask_artifact_id="mask-artifact-1",
    )
    assert target.read_bytes() == first
    # A second grant for the same key with different bytes fails at issuance.
    other = bytes(255 - (i % 251) for i in range(64))
    with pytest.raises(ValueError, match="already bound|already sealed"):
        store.issue_grant(
            principal=_operator(),
            organization_id="org-a",
            site_id="site-a",
            work_area_id="work-area-a",
            mask_child_id="child-1",
            mask_artifact_id="mask-artifact-1",
            subject_digest=_digest("parent-subject"),
            declared_sha256=_digest(other),
            declared_size_bytes=len(other),
            now=NOW,
        )
    assert target.read_bytes() == first
    # Idempotent re-completion of the identical bytes appends nothing.
    journal_path = tmp_path / "bytes.journal"
    before = len(journal_path.read_text().splitlines())
    sha, size = store.complete_upload(
        grant_id=grant.grant_id, data=first, principal=_operator(), now=NOW
    )
    assert (sha, size) == (_digest(first), 64)
    assert len(journal_path.read_text().splitlines()) == before
    store._journal.close()  # noqa: SLF001


def test_subject_ambiguity_rejected_at_grant(tmp_path) -> None:
    """One object key binds exactly one subject: a second subject fails."""
    store = _store(tmp_path)
    data = b"y" * 32
    _grant(store, data)
    with pytest.raises(ValueError, match="already bound"):
        store.issue_grant(
            principal=_operator(),
            organization_id="org-a",
            site_id="site-a",
            work_area_id="work-area-a",
            mask_child_id="child-1",
            mask_artifact_id="mask-artifact-1",
            subject_digest=_digest("other-subject"),
            declared_sha256=_digest(data),
            declared_size_bytes=len(data),
            now=NOW,
        )
    store._journal.close()  # noqa: SLF001


def test_unknown_grant_complete_rejected(tmp_path) -> None:
    store = _store(tmp_path)
    with pytest.raises(ValueError, match="unknown"):
        store.complete_upload(
            grant_id="no-such-grant", data=b"z" * 16, principal=_operator(), now=NOW
        )
    store._journal.close()  # noqa: SLF001


def test_symlink_post_seal_tamper_fails_proof(tmp_path) -> None:
    store = _store(tmp_path)
    data = bytes(7 for _ in range(32))
    grant = _grant(store, data)
    store.complete_upload(grant_id=grant.grant_id, data=data, principal=_operator(), now=NOW)
    target = store.sealed_object_path(
        organization_id="org-a",
        site_id="site-a",
        mask_child_id="child-1",
        mask_artifact_id="mask-artifact-1",
    )
    assert target.read_bytes() == data
    link_target = tmp_path / "elsewhere.bin"
    link_target.write_bytes(b"tampered")
    target.unlink()
    os.symlink(link_target, target)
    with pytest.raises(ValueError, match="unavailable|regular file|match the sealed proof"):
        store.fetch_proof(
            organization_id="org-a",
            site_id="site-a",
            subject_digest=_digest("parent-subject"),
            mask_child_id="child-1",
            mask_artifact_id="mask-artifact-1",
        )
    store._journal.close()  # noqa: SLF001


def test_hardlink_post_seal_tamper_fails_proof(tmp_path) -> None:
    store = _store(tmp_path)
    data = bytes(9 for _ in range(32))
    grant = _grant(store, data)
    store.complete_upload(grant_id=grant.grant_id, data=data, principal=_operator(), now=NOW)
    target = store.sealed_object_path(
        organization_id="org-a",
        site_id="site-a",
        mask_child_id="child-1",
        mask_artifact_id="mask-artifact-1",
    )
    extra = tmp_path / "extra-link.bin"
    os.link(target, extra)
    try:
        with pytest.raises(ValueError, match="single-link|regular file"):
            store.fetch_proof(
                organization_id="org-a",
                site_id="site-a",
                subject_digest=_digest("parent-subject"),
                mask_child_id="child-1",
                mask_artifact_id="mask-artifact-1",
            )
    finally:
        extra.unlink()
    proof = store.fetch_proof(
        organization_id="org-a",
        site_id="site-a",
        subject_digest=_digest("parent-subject"),
        mask_child_id="child-1",
        mask_artifact_id="mask-artifact-1",
    )
    assert proof == (_digest(data), len(data))
    store._journal.close()  # noqa: SLF001


def test_non_private_root_rejected(tmp_path) -> None:
    root = tmp_path / "wide-bytes"
    root.mkdir(mode=0o755)
    with pytest.raises(ValueError, match="private 0700"):
        ExternalMaskInputByteStore(
            DurableJournal(tmp_path / "wide.journal"),
            root,
            resource_envelope=_envelope(),
            clock=lambda: NOW,
            coordinator=ExternalAuthorityCurrentnessCoordinator(),
        )


def _journal_event_digest(raw: dict) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(raw)).hexdigest()


def _write_grant_journal(path, *, grant_id="grant-1", sha=None, size=16) -> None:
    sha = sha or _digest(b"q" * size)
    event = {
        "kind": "external-mask-input-grant-issued.v1",
        "version": 1,
        "grantId": grant_id,
        "organizationId": "org-a",
        "siteId": "site-a",
        "workAreaId": "work-area-a",
        "maskChildId": "child-1",
        "maskArtifactId": "mask-artifact-1",
        "subjectDigest": _digest("parent-subject"),
        "objectKey": "mask/org-a/site-a/child-1/mask-artifact-1.tif",
        "declaredSha256": sha,
        "declaredSizeBytes": size,
        "issuedAt": "2026-10-26T00:00:00Z",
        "expiresAt": "2026-10-27T00:00:00Z",
    }
    event["eventDigest"] = _journal_event_digest(
        {k: v for k, v in event.items() if k != "eventDigest"}
    )
    path.write_text(json.dumps(event, ensure_ascii=True, separators=(",", ":")) + "\n")


def test_replay_rejects_unknown_grant_seal(tmp_path) -> None:
    journal_path = tmp_path / "bytes.journal"
    _write_grant_journal(journal_path)
    lines = journal_path.read_text().splitlines()
    import json as _json

    event = {
        "kind": "external-mask-input-bytes-sealed.v1",
        "version": 1,
        "grantId": "grant-unknown",
        "organizationId": "org-a",
        "siteId": "site-a",
        "maskChildId": "child-1",
        "maskArtifactId": "mask-artifact-1",
        "objectKey": "mask/org-a/site-a/child-1/mask-artifact-1.tif",
        "observedSha256": _digest(b"q" * 16),
        "observedSizeBytes": 16,
        "sealedAt": "2026-10-26T01:00:00Z",
    }
    event["eventDigest"] = _journal_event_digest(
        {k: v for k, v in event.items() if k != "eventDigest"}
    )
    lines.append(_json.dumps(event, ensure_ascii=True, separators=(",", ":")))
    journal_path.write_text("\n".join(lines) + "\n")

    with pytest.raises(MaskByteStoreRecoveryError, match="unknown grant"):
        ExternalMaskInputByteStore(
            DurableJournal(journal_path),
            tmp_path / "bytes",
            resource_envelope=_envelope(),
            clock=lambda: NOW,
            coordinator=ExternalAuthorityCurrentnessCoordinator(),
        )


def test_replay_rejects_divergent_seal_and_tampered_digest(tmp_path) -> None:
    import json as _json

    journal_path = tmp_path / "bytes.journal"
    _write_grant_journal(journal_path)
    event = {
        "kind": "external-mask-input-bytes-sealed.v1",
        "version": 1,
        "grantId": "grant-1",
        "organizationId": "org-a",
        "siteId": "site-a",
        "maskChildId": "child-1",
        "maskArtifactId": "mask-artifact-1",
        "objectKey": "mask/org-a/site-a/child-1/mask-artifact-1.tif",
        "observedSha256": _digest(b"X" * 16),
        "observedSizeBytes": 16,
        "sealedAt": "2026-10-26T01:00:00Z",
    }
    event["eventDigest"] = _journal_event_digest(
        {k: v for k, v in event.items() if k != "eventDigest"}
    )
    lines = journal_path.read_text().splitlines()
    lines.append(_json.dumps(event, ensure_ascii=True, separators=(",", ":")))
    journal_path.write_text("\n".join(lines) + "\n")
    with pytest.raises(MaskByteStoreRecoveryError, match="diverges"):
        ExternalMaskInputByteStore(
            DurableJournal(journal_path),
            tmp_path / "bytes",
            resource_envelope=_envelope(),
            clock=lambda: NOW,
            coordinator=ExternalAuthorityCurrentnessCoordinator(),
        )
    tampered = _json.loads(lines[0])
    tampered["declaredSizeBytes"] = 17
    lines[0] = _json.dumps(tampered, ensure_ascii=True, separators=(",", ":"))
    journal_path.write_text("\n".join(lines) + "\n")
    with pytest.raises(MaskByteStoreRecoveryError, match="digest is invalid"):
        ExternalMaskInputByteStore(
            DurableJournal(journal_path),
            tmp_path / "bytes2",
            resource_envelope=_envelope(),
            clock=lambda: NOW,
            coordinator=ExternalAuthorityCurrentnessCoordinator(),
        )


def test_replay_rejects_version_spoof_and_bool_size(tmp_path) -> None:
    import json as _json

    journal_path = tmp_path / "bytes.journal"
    _write_grant_journal(journal_path)
    lines = journal_path.read_text().splitlines()
    spoofed = _json.loads(lines[0])
    spoofed["version"] = True
    lines[0] = _json.dumps(spoofed, ensure_ascii=True, separators=(",", ":"))
    journal_path.write_text("\n".join(lines) + "\n")
    with pytest.raises(MaskByteStoreRecoveryError, match="version is unsupported"):
        ExternalMaskInputByteStore(
            DurableJournal(journal_path),
            tmp_path / "bytes",
            resource_envelope=_envelope(),
            clock=lambda: NOW,
            coordinator=ExternalAuthorityCurrentnessCoordinator(),
        )


def _sealed_fixture(tmp_path, name: str = "bytes") -> tuple[ExternalMaskInputByteStore, bytes]:
    """Seal 256 deterministic bytes and return the store plus the bytes."""
    store = _store(tmp_path, name)
    data = bytes(i % 251 for i in range(256))
    grant = _grant(store, data)
    store.complete_upload(grant_id=grant.grant_id, data=data, principal=_operator(), now=NOW)
    return store, data


def _proof_kwargs() -> dict:
    return {
        "organization_id": "org-a",
        "site_id": "site-a",
        "subject_digest": _digest("parent-subject"),
        "mask_child_id": "child-1",
        "mask_artifact_id": "mask-artifact-1",
    }


def test_root_ancestor_symlink_rejected(tmp_path) -> None:
    """A symlinked ancestor anywhere above the root fails closed at pin time."""
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    link = tmp_path / "linkdir"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError, match="cannot pin mask store root|substitutable"):
        ExternalMaskInputByteStore(
            DurableJournal(tmp_path / "link.journal"),
            link / "mask-bytes",
            resource_envelope=_envelope(),
            clock=lambda: NOW,
            coordinator=ExternalAuthorityCurrentnessCoordinator(),
        )


def test_root_group_writable_ancestor_rejected_unless_sticky(tmp_path) -> None:
    """Group/other-writable ancestors fail closed; sticky+owned is the only pass."""
    farm = tmp_path / "farm"
    farm.mkdir(mode=0o700)
    farm.chmod(0o770)
    with pytest.raises(ValueError, match="substitutable"):
        ExternalMaskInputByteStore(
            DurableJournal(tmp_path / "farm.journal"),
            farm / "mask-bytes",
            resource_envelope=_envelope(),
            clock=lambda: NOW,
            coordinator=ExternalAuthorityCurrentnessCoordinator(),
        )
    farm.chmod(0o1770)
    store = ExternalMaskInputByteStore(
        DurableJournal(tmp_path / "farm-ok.journal"),
        farm / "mask-bytes",
        resource_envelope=_envelope(),
        clock=lambda: NOW,
        coordinator=ExternalAuthorityCurrentnessCoordinator(),
    )
    store.close()


def test_root_wrong_mode_rejected(tmp_path) -> None:
    root = tmp_path / "wide-bytes"
    root.mkdir(mode=0o700)
    root.chmod(0o755)
    with pytest.raises(ValueError, match="private 0700"):
        ExternalMaskInputByteStore(
            DurableJournal(tmp_path / "wide2.journal"),
            root,
            resource_envelope=_envelope(),
            clock=lambda: NOW,
            coordinator=ExternalAuthorityCurrentnessCoordinator(),
        )


def test_object_subdir_wrong_mode_rejected(tmp_path) -> None:
    store, _ = _sealed_fixture(tmp_path)
    leaf = tmp_path / "bytes" / "org-a" / "site-a" / "child-1"
    leaf.chmod(0o755)
    try:
        with pytest.raises(ValueError, match="owner-private 0700"):
            store.fetch_proof(**_proof_kwargs())
        with pytest.raises(ValueError, match="owner-private 0700"):
            store.read_slice(offset=0, length=8, **_proof_kwargs())
    finally:
        leaf.chmod(0o700)
    assert store.fetch_proof(**_proof_kwargs())[1] == 256
    store.close()


def test_object_file_uid_shift_rejected(monkeypatch, tmp_path) -> None:
    """Files not owned by the caller fail closed, even with correct bytes."""
    import os as _os

    store, _ = _sealed_fixture(tmp_path)
    real_uid = _os.geteuid()
    monkeypatch.setattr(_os, "geteuid", lambda: real_uid + 100000 if real_uid < 100000 else 1)
    with pytest.raises(ValueError, match="private single-link|owner-private"):
        store.fetch_proof(**_proof_kwargs())
    monkeypatch.undo()
    assert store.fetch_proof(**_proof_kwargs())[1] == 256
    store.close()


def test_replacing_root_between_ops_keeps_pinned_view(tmp_path) -> None:
    """Swapping the root path cannot redirect a pinned store; new pins fail."""
    store, data = _sealed_fixture(tmp_path, "pinned")
    root = tmp_path / "pinned"
    moved = tmp_path / "pinned-orig"
    os.rename(root, moved)
    replacement = tmp_path / "replacement"
    replacement.mkdir(mode=0o700)
    (replacement / "org-a").mkdir(mode=0o700)
    try:
        # The pinned store still serves the original bytes from its held fd.
        assert store.read_slice(offset=0, length=len(data), **_proof_kwargs()) == data
        # A fresh pin of a symlinked root fails closed instead of following it.
        os.rename(replacement, tmp_path / "replacement-orig")
        os.symlink(tmp_path / "replacement-orig", root, target_is_directory=True)
        with pytest.raises(ValueError, match="cannot pin|substitutable|unavailable"):
            ExternalMaskInputByteStore(
                DurableJournal(tmp_path / "pinned2.journal"),
                root,
                resource_envelope=_envelope(),
                clock=lambda: NOW,
                coordinator=ExternalAuthorityCurrentnessCoordinator(),
            )
        # Even divergent bytes planted at the same relative path cannot fool
        # the pinned view: the seal proof still binds the original bytes.
        planted = tmp_path / "replacement-orig" / "org-a" / "site-a" / "child-1"
        planted.mkdir(mode=0o700, parents=True, exist_ok=True)
        (planted / "mask-artifact-1.tif").write_bytes(b"X" * len(data))
        assert store.read_slice(offset=0, length=len(data), **_proof_kwargs()) == data
    finally:
        if os.path.islink(root):
            os.unlink(root)
        if moved.exists() and not root.exists():
            os.rename(moved, root)
        if (tmp_path / "replacement-orig").exists():
            import shutil as _shutil

            _shutil.rmtree(tmp_path / "replacement-orig", ignore_errors=True)
    store.close()


def test_read_slice_trusted_window_and_bounds(tmp_path) -> None:
    store, data = _sealed_fixture(tmp_path)
    assert store.read_slice(offset=10, length=20, **_proof_kwargs()) == data[10:30]
    assert store.read_slice(offset=0, length=len(data), **_proof_kwargs()) == data
    with pytest.raises(ValueError, match="out of range|exceeds the sealed"):
        store.read_slice(offset=250, length=20, **_proof_kwargs())
    with pytest.raises(ValueError, match="out of range"):
        store.read_slice(offset=-1, length=8, **_proof_kwargs())
    with pytest.raises(ValueError, match="out of range"):
        store.read_slice(offset=0, length=0, **_proof_kwargs())
    with pytest.raises(ValueError, match="out of range|exceeds the finite"):
        store.read_slice(offset=0, length=9_999_999, **_proof_kwargs())
    with pytest.raises(ValueError, match="not sealed"):
        store.read_slice(
            offset=0,
            length=8,
            **{**_proof_kwargs(), "mask_child_id": "no-such-child"},
        )
    with pytest.raises(ValueError, match="do not bind the subject"):
        store.read_slice(
            offset=0, length=8, **{**_proof_kwargs(), "subject_digest": _digest("other")}
        )
    store.close()


def test_read_slice_detects_post_seal_tamper(tmp_path) -> None:
    store, data = _sealed_fixture(tmp_path)
    target = store.sealed_object_path(
        organization_id="org-a",
        site_id="site-a",
        mask_child_id="child-1",
        mask_artifact_id="mask-artifact-1",
    )
    with open(target, "wb") as handle:
        handle.write(b"X" * len(data))
    with pytest.raises(ValueError, match="do not match the sealed proof|size"):
        store.read_slice(offset=0, length=8, **_proof_kwargs())
    with pytest.raises(ValueError, match="do not match the sealed proof|size"):
        store.fetch_proof(**_proof_kwargs())
    store.close()


def test_read_slice_uses_no_absolute_open(tmp_path, monkeypatch) -> None:
    """Window reads must never open an absolute path after the sealed proof."""
    import os as _real_os

    store, _ = _sealed_fixture(tmp_path)
    opened: list[str] = []
    real_open = _real_os.open

    def _spy(path, *args, **kwargs):
        if isinstance(path, (str, bytes)):
            text = path.decode() if isinstance(path, bytes) else path
            if isinstance(text, str) and text.startswith("/"):
                opened.append(text)
        elif hasattr(path, "__fspath__"):
            text = str(path)
            if text.startswith("/"):
                opened.append(text)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(_real_os, "open", _spy)
    store.read_slice(offset=0, length=16, **_proof_kwargs())
    store.fetch_proof(**_proof_kwargs())
    assert opened == []
    store.close()


def test_close_is_idempotent_and_blocks_ops(tmp_path) -> None:
    store, data = _sealed_fixture(tmp_path)
    store.close()
    store.close()
    with pytest.raises(ValueError, match="closed"):
        store.fetch_proof(**_proof_kwargs())
    with pytest.raises(ValueError, match="closed"):
        store.read_slice(offset=0, length=8, **_proof_kwargs())
    with pytest.raises(ValueError, match="closed"):
        store.issue_grant(
            principal=_operator(),
            organization_id="org-a",
            site_id="site-a",
            work_area_id="work-area-a",
            mask_child_id="child-1",
            mask_artifact_id="mask-artifact-1",
            subject_digest=_digest("parent-subject"),
            declared_sha256=_digest(data),
            declared_size_bytes=len(data),
            now=NOW,
        )
    with pytest.raises(ValueError, match="closed"):
        store.sealed_object_path(
            organization_id="org-a",
            site_id="site-a",
            mask_child_id="child-1",
            mask_artifact_id="mask-artifact-1",
        )


def test_journal_replay_after_restart_with_pinned_root(tmp_path) -> None:
    store, data = _sealed_fixture(tmp_path, name="restart")
    store.close()
    store._journal.close()  # noqa: SLF001 - release the journal flock for reopen
    reopened = ExternalMaskInputByteStore(
        DurableJournal(tmp_path / "restart.journal"),
        tmp_path / "restart",
        resource_envelope=_envelope(),
        clock=lambda: NOW,
        coordinator=ExternalAuthorityCurrentnessCoordinator(),
    )
    assert reopened.fetch_proof(**_proof_kwargs()) == (_digest(data), len(data))
    assert reopened.read_slice(offset=0, length=8, **_proof_kwargs()) == data[:8]
    reopened.close()
