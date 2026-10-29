"""Directory-identity regression: legitimate st_size drift must not break cleanup.

Filesystem finding (isolated tmpfs vs host ext4, real code): an attempt
directory snapshots at st_size 40 before its owned artifact child exists and
reports 60 afterwards on tmpfs, while ext4 reports a stable 4096.  The staging
identity therefore compared a pre-child snapshot against a post-child live
directory and failed closed -- strict abort raised, non-strict abort orphaned
the attempt directory, and journal recovery returned OWNERSHIP_UNCERTAIN with
owned nodes retained.

Rule under test: directory identity is device/inode/mode/owner/link-count
exact and st_size-free, and the directory matcher fails closed on
non-directories.  Existing seal/receipt/digest byte-size checks stay
unchanged; cleanup artifact matching intentionally ignores file size
(device/inode/type/owner exact, link count when strict).  Size drift is
simulated deterministically by forging the recorded size, so every test below
runs on any filesystem; the tmpfs behavior itself was verified separately
with the real module on a private tmpfs staging root.
"""

from __future__ import annotations

import os
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
from ksi_processing_controller.external_inspector_attempts import (
    StagingAllocationPlanV1,
)
from ksi_processing_controller.external_inspector_staging import (
    FileSystemInputStaging,
    InspectorStagingUnavailable,
    MappedInspectorReaderV1,
    NamedReaderAclPort,
    RegisteredStagingRecoveryDispositionV1,
    _cleanup_exact,
    _Identity,
    _matches_staging_directory_identity,
    _matches_staging_identity,
    _same_owned_directory,
    _staging_identity,
)


class _Mapping:
    def resolve_exact(self, **kwargs: Any) -> MappedInspectorReaderV1:
        del kwargs
        return MappedInspectorReaderV1(1, 1, 1, 1, "mapping")


class _Acl:
    def grant_exact(self, **kwargs: Any) -> bool:
        del kwargs
        return True

    def verifies_exact(self, **kwargs: Any) -> bool:
        del kwargs
        return True

    def revoke_exact(self, **kwargs: Any) -> bool:
        del kwargs
        return True


def _digest(marker: str) -> str:
    return "sha256:" + marker * 64


def _plan(root_identity: Any, nonce: str) -> StagingAllocationPlanV1:
    return StagingAllocationPlanV1(
        attempt_nonce=nonce,
        binding_digest=_digest("d"),
        owner="worker-1",
        allocation_nonce=f"allocation-{nonce}",
        root=root_identity,
        staging_name=nonce,
        artifact_leaf="artifact",
        provisional_marker_name=f".{nonce}.provisional",
        committed_marker_name=f".{nonce}.committed",
    )


def _staging(root: Path) -> FileSystemInputStaging:
    return FileSystemInputStaging(
        private_root=root, reader_mapping=_Mapping(), acl=cast(NamedReaderAclPort, _Acl())
    )


def _open_layout(root: Path, name: str = "attempt-1") -> tuple[int, int, _Identity, _Identity]:
    """Mirror the allocation tail: mkdir, snapshot, open fds, create artifact."""
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    os.mkdir(name, 0o700, dir_fd=root_fd)
    attempt_identity = _Identity.from_stat(os.stat(name, dir_fd=root_fd, follow_symlinks=False))
    attempt_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
    writer_fd = os.open(
        "artifact",
        os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
        dir_fd=attempt_fd,
    )
    os.write(writer_fd, b"owned")
    file_identity = _Identity.from_stat(os.fstat(writer_fd))
    os.close(writer_fd)
    return root_fd, attempt_fd, attempt_identity, file_identity


def test_directory_identity_ignores_only_size_drift() -> None:
    base = _Identity(
        device=1, inode=2, mode=0o40700, owner_uid=3, owner_gid=4, link_count=2, size=40
    )
    assert _same_owned_directory(base, replace(base, size=60)) is True
    assert _same_owned_directory(base, replace(base, device=9)) is False
    assert _same_owned_directory(base, replace(base, inode=9)) is False
    assert _same_owned_directory(base, replace(base, mode=0o40755)) is False
    assert _same_owned_directory(base, replace(base, owner_uid=9)) is False
    assert _same_owned_directory(base, replace(base, owner_gid=9)) is False
    assert _same_owned_directory(base, replace(base, link_count=3)) is False


def test_file_identity_still_requires_exact_size(tmp_path: Path) -> None:
    probe = tmp_path / "probe"
    probe.write_bytes(b"123456")
    os.chmod(probe, 0o600)
    identity = _Identity.from_stat(os.stat(probe, follow_symlinks=False))
    expected = _staging_identity(identity)
    assert _matches_staging_identity(identity, expected) is True
    assert _matches_staging_identity(replace(identity, size=identity.size + 1), expected) is False
    # The directory matcher fails closed on non-directories: masking
    # `mode & 0o777` drops file-type bits, so without the S_ISDIR gate a
    # mode-0700 regular file could satisfy a directory receipt.
    assert _matches_staging_directory_identity(identity, expected) is False
    link = tmp_path / "link"
    os.symlink(probe, link)
    link_identity = _Identity.from_stat(os.stat(link, follow_symlinks=False))
    assert _matches_staging_directory_identity(link_identity, expected) is False


def test_directory_receipt_match_ignores_only_size_drift(tmp_path: Path) -> None:
    target = tmp_path / "attempt-dir"
    target.mkdir(mode=0o700)
    identity = _Identity.from_stat(os.stat(target, follow_symlinks=False))
    expected = _staging_identity(identity)
    drifted = replace(identity, size=identity.size + 20)
    assert _matches_staging_directory_identity(drifted, expected) is True
    assert (
        _matches_staging_directory_identity(replace(identity, inode=identity.inode + 1), expected)
        is False
    )
    assert (
        _matches_staging_directory_identity(
            replace(identity, link_count=identity.link_count + 1), expected
        )
        is False
    )
    masked = replace(identity, mode=0o40710)
    if (identity.mode & 0o777) == 0o700:
        assert _matches_staging_directory_identity(masked, expected) is True


def test_cleanup_removes_owned_nodes_despite_simulated_size_drift(tmp_path: Path) -> None:
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    root_fd, attempt_fd, attempt_identity, file_identity = _open_layout(root)
    drifted = replace(attempt_identity, size=attempt_identity.size + 20)
    _cleanup_exact(
        root_fd, attempt_fd, "attempt-1", file_identity, drifted, strict_name_identity=True
    )
    assert not (root / "attempt-1").exists()


def test_cleanup_nonstrict_removes_owned_nodes_despite_size_drift(tmp_path: Path) -> None:
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    root_fd, attempt_fd, attempt_identity, file_identity = _open_layout(root)
    drifted = replace(attempt_identity, size=attempt_identity.size + 20)
    _cleanup_exact(
        root_fd, attempt_fd, "attempt-1", file_identity, drifted, strict_name_identity=False
    )
    assert not (root / "attempt-1").exists()


def test_cleanup_strict_rejects_replaced_directory_inode(tmp_path: Path) -> None:
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    root_fd, attempt_fd, attempt_identity, file_identity = _open_layout(root)
    forged = replace(attempt_identity, inode=attempt_identity.inode + 999999)
    with pytest.raises(InspectorStagingUnavailable, match="identity"):
        _cleanup_exact(
            root_fd, attempt_fd, "attempt-1", file_identity, forged, strict_name_identity=True
        )
    assert (root / "attempt-1" / "artifact").exists()


def test_cleanup_strict_rejects_symlink_substituted_directory(tmp_path: Path) -> None:
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    root_fd, attempt_fd, attempt_identity, file_identity = _open_layout(root)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir(mode=0o700)
    (elsewhere / "payload").write_bytes(b"not-owned")
    os.rename("attempt-1", "attempt-1-orig", src_dir_fd=root_fd, dst_dir_fd=root_fd)
    os.symlink(str(elsewhere), "attempt-1", dir_fd=root_fd)
    with pytest.raises(InspectorStagingUnavailable, match="identity"):
        _cleanup_exact(
            root_fd,
            attempt_fd,
            "attempt-1",
            file_identity,
            attempt_identity,
            strict_name_identity=True,
        )
    assert os.path.islink(root / "attempt-1")
    assert (elsewhere / "payload").read_bytes() == b"not-owned"


def test_cleanup_strict_rejects_permission_widened_directory(tmp_path: Path) -> None:
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    root_fd, attempt_fd, attempt_identity, file_identity = _open_layout(root)
    os.fchmod(attempt_fd, 0o755)
    with pytest.raises(InspectorStagingUnavailable, match="identity"):
        _cleanup_exact(
            root_fd,
            attempt_fd,
            "attempt-1",
            file_identity,
            attempt_identity,
            strict_name_identity=True,
        )
    assert (root / "attempt-1").is_dir() and not os.path.islink(root / "attempt-1")


def test_cleanup_strict_rejects_substituted_artifact(tmp_path: Path) -> None:
    # A live owner descriptor pins the original inode (as the sealed reader does),
    # so a same-name substitute necessarily carries a new inode and is rejected.
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    root_fd, attempt_fd, attempt_identity, file_identity = _open_layout(root)
    pin_fd = os.open("artifact", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=attempt_fd)
    try:
        os.unlink("artifact", dir_fd=attempt_fd)
        replacement = os.open(
            "artifact", os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=attempt_fd
        )
        os.write(replacement, b"replacement")
        os.close(replacement)
    finally:
        os.close(pin_fd)
    with pytest.raises(InspectorStagingUnavailable, match="identity"):
        _cleanup_exact(
            root_fd,
            attempt_fd,
            "attempt-1",
            file_identity,
            attempt_identity,
            strict_name_identity=True,
        )
    assert (root / "attempt-1" / "artifact").read_bytes() == b"replacement"


def test_cleanup_strict_rejects_extra_child(tmp_path: Path) -> None:
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    root_fd, attempt_fd, attempt_identity, file_identity = _open_layout(root)
    extra = os.open(
        "extra", os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=attempt_fd
    )
    os.close(extra)
    with pytest.raises(InspectorStagingUnavailable):
        _cleanup_exact(
            root_fd,
            attempt_fd,
            "attempt-1",
            file_identity,
            attempt_identity,
            strict_name_identity=True,
        )
    assert (root / "attempt-1" / "extra").exists()


def test_registered_abort_cleans_up_after_legitimate_child_creation(tmp_path: Path) -> None:
    root = tmp_path / "private"
    staging = _staging(root)
    plan = _plan(staging.private_root_identity(), "attempt-e2e-1")
    mutable, receipt = staging.begin_registered(
        plan=plan, maximum_bytes=8, deadline_monotonic=time.monotonic() + 5.0
    )
    mutable.write(b"sealed!!")
    mutable.abort()
    staging.finalize_registered_cleanup(plan=plan, receipt=receipt)
    assert not (root / plan.staging_name).exists()
    assert not (root / plan.committed_marker_name).exists()


def test_recovery_rejects_replaced_directory(tmp_path: Path) -> None:
    root = tmp_path / "private"
    staging = _staging(root)
    plan = _plan(staging.private_root_identity(), "attempt-rec-1")
    mutable, receipt = staging.begin_registered(
        plan=plan, maximum_bytes=8, deadline_monotonic=time.monotonic() + 5.0
    )
    mutable.write(b"crashpad")
    mutable.relinquish_for_recovery()
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.rename(
            plan.staging_name,
            plan.staging_name + "-orig",
            src_dir_fd=root_fd,
            dst_dir_fd=root_fd,
        )
        os.mkdir(plan.staging_name, 0o700, dir_fd=root_fd)
    finally:
        os.close(root_fd)
    assert staging.recover_registered(plan=plan, receipt=receipt) is (
        RegisteredStagingRecoveryDispositionV1.OWNERSHIP_UNCERTAIN
    )
    assert (root / plan.staging_name).is_dir()
