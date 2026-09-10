"""Synthetic local tests for the sealed input handoff before any runtime launch."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest


@dataclass(frozen=True)
class _Reader:
    container_uid: int = 10001
    container_gid: int = 10001
    host_uid: int = 20001
    host_gid: int = 20001
    mapping_witness: str = "synthetic-reader-map-v1"


class _Mapping:
    def __init__(self, reader: _Reader | None, groups: tuple[int, ...] = ()) -> None:
        self.reader = reader
        self.groups = groups
        self.calls: list[tuple[int, int, tuple[int, ...]]] = []

    def resolve_exact(
        self,
        *,
        runtime_uid: int,
        runtime_gid: int,
        supplementary_groups: tuple[int, ...],
        deadline_monotonic: float,
    ) -> _Reader | None:
        del deadline_monotonic
        self.calls.append((runtime_uid, runtime_gid, supplementary_groups))
        if runtime_uid != 10001 or runtime_gid != 10001 or supplementary_groups != self.groups:
            return None
        return self.reader


class _Acl:
    def __init__(self, *, grant_result: bool = True, verify_result: bool = True) -> None:
        self.grants: list[tuple[int, tuple[int, int], _Reader]] = []
        self.verified: list[tuple[int, tuple[int, int], _Reader]] = []
        self.revoked: list[tuple[int, tuple[int, int], _Reader]] = []
        self.grant_result = grant_result
        self.verify_result = verify_result

    def grant_exact(
        self,
        *,
        source_fd: int,
        traversal_fds: tuple[int, int],
        reader: _Reader,
        deadline_monotonic: float,
    ) -> bool:
        del deadline_monotonic
        self.grants.append((source_fd, traversal_fds, reader))
        return self.grant_result

    def verifies_exact(
        self,
        *,
        source_fd: int,
        traversal_fds: tuple[int, int],
        reader: _Reader,
        deadline_monotonic: float,
    ) -> bool:
        del deadline_monotonic
        self.verified.append((source_fd, traversal_fds, reader))
        return self.verify_result

    def revoke_exact(
        self,
        *,
        source_fd: int,
        traversal_fds: tuple[int, int],
        reader: _Reader,
        deadline_monotonic: float,
    ) -> bool:
        del deadline_monotonic
        self.revoked.append((source_fd, traversal_fds, reader))
        return True

    def grant_leaf_exact(self, **kwargs):  # type: ignore[no-untyped-def]
        return self.grant_exact(
            source_fd=kwargs["source_fd"],
            traversal_fds=(kwargs["attempt_fd"], kwargs["attempt_fd"]),
            reader=kwargs["reader"],
            deadline_monotonic=kwargs["deadline_monotonic"],
        )

    def revoke_leaf_exact(self, **kwargs):  # type: ignore[no-untyped-def]
        return True

    def verifies_private_directory(self, **kwargs):  # type: ignore[no-untyped-def]
        return True

    def retire_private_directory(self, **kwargs):  # type: ignore[no-untyped-def]
        return True

    def retire_recovered_leaf_acl(self, **kwargs):  # type: ignore[no-untyped-def]
        return True


class _ModeChangingAcl(_Acl):
    """Synthetic ACL port: a named-user ACL mask appears as group-class mode bits."""

    def __init__(self, mode: int) -> None:
        super().__init__()
        self.mode = mode

    def grant_exact(
        self,
        *,
        source_fd: int,
        traversal_fds: tuple[int, int],
        reader: _Reader,
        deadline_monotonic: float,
    ) -> bool:
        os.fchmod(source_fd, self.mode)
        return super().grant_exact(
            source_fd=source_fd,
            traversal_fds=traversal_fds,
            reader=reader,
            deadline_monotonic=deadline_monotonic,
        )


def _staging(tmp_path: Path) -> tuple[Any, _Acl]:
    spec = importlib.util.find_spec("ksi_processing_controller.external_inspector_staging")
    assert spec is not None
    module = importlib.import_module("ksi_processing_controller.external_inspector_staging")
    acl = _Acl()
    return module.FileSystemInputStaging(
        private_root=tmp_path / "private", reader_mapping=_Mapping(_Reader()), acl=acl
    ), acl


def test_seal_rechecks_exact_bytes_and_prepares_only_a_fixed_read_only_bind(tmp_path: Path) -> None:
    """A mutable byte stream must become one private, retained, exact-read capability."""
    staging, acl = _staging(tmp_path)
    payload = b"sealed input bytes"
    mutable = staging.begin(maximum_bytes=len(payload), deadline_monotonic=time.monotonic() + 1.0)
    mutable.write(payload)
    sealed = mutable.seal_for_reader(
        expected_sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
        expected_size_bytes=len(payload),
        reader=_Reader(),
        supplementary_groups=(),
        deadline_monotonic=time.monotonic() + 1.0,
    )

    bind = sealed.prepare_read_only_bind(deadline_monotonic=time.monotonic() + 1.0)

    assert bind.target_path == "/input/artifact.tif"
    assert bind.read_only is True
    assert (
        bind.source.read_at(
            offset=0, maximum_bytes=len(payload), deadline_monotonic=time.monotonic() + 1.0
        )
        == payload
    )
    assert (
        bind.source.consume_fd(
            lambda descriptor: os.pread(descriptor, len(payload), 0),
            deadline_monotonic=time.monotonic() + 1.0,
        )
        == payload
    )
    assert bind.observed_sha256 == "sha256:" + hashlib.sha256(payload).hexdigest()
    assert bind.observed_size_bytes == len(payload)
    assert bind.reader_mapping_witness == "synthetic-reader-map-v1"
    assert len(acl.grants) == len(acl.verified) == 1
    assert acl.grants[0][0] == acl.verified[0][0]
    assert bind.source_link_count == 1
    assert len(acl.verified[0][1]) == 2

    sealed.abort()
    with pytest.raises(Exception, match="no longer live"):
        bind.source.read_at(offset=0, maximum_bytes=1, deadline_monotonic=time.monotonic() + 1.0)


@pytest.mark.parametrize(("acl_mode", "should_bind"), [(0o640, True), (0o644, False)])
def test_acl_mask_mode_is_allowed_only_when_the_exact_fd_acl_proof_remains_private(
    tmp_path: Path, acl_mode: int, should_bind: bool
) -> None:
    """A real named ACL may yield 0640; group/world exposure beyond it still fails closed."""
    module = importlib.import_module("ksi_processing_controller.external_inspector_staging")
    acl = _ModeChangingAcl(acl_mode)
    staging = module.FileSystemInputStaging(
        private_root=tmp_path / "private", reader_mapping=_Mapping(_Reader()), acl=acl
    )
    payload = b"bound"
    mutable = staging.begin(maximum_bytes=len(payload), deadline_monotonic=time.monotonic() + 1.0)
    mutable.write(payload)
    sealed = mutable.seal_for_reader(
        expected_sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
        expected_size_bytes=len(payload),
        reader=_Reader(),
        supplementary_groups=(),
        deadline_monotonic=time.monotonic() + 1.0,
    )

    if should_bind:
        bind = sealed.prepare_read_only_bind(deadline_monotonic=time.monotonic() + 1.0)
        assert (
            bind.source.read_at(
                offset=0, maximum_bytes=len(payload), deadline_monotonic=time.monotonic() + 1.0
            )
            == payload
        )
    else:
        with pytest.raises(Exception, match="group or world"):
            sealed.prepare_read_only_bind(deadline_monotonic=time.monotonic() + 1.0)
    sealed.abort()


def test_seal_rejects_a_hardlink_before_any_runtime_bind(tmp_path: Path) -> None:
    """A second name could replace the observed bytes after inspection, so sealing fails."""
    staging, _ = _staging(tmp_path)
    payload = b"bound"
    mutable = staging.begin(maximum_bytes=len(payload), deadline_monotonic=time.monotonic() + 1.0)
    mutable.write(payload)
    source_path = next((tmp_path / "private").glob("*/artifact"))
    os.link(source_path, tmp_path / "linked-artifact")

    with pytest.raises(Exception, match="hardlink|link"):
        mutable.seal_for_reader(
            expected_sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
            expected_size_bytes=len(payload),
            reader=_Reader(),
            supplementary_groups=(),
            deadline_monotonic=time.monotonic() + 1.0,
        )
    assert not list((tmp_path / "private").glob("*/artifact"))


@pytest.mark.parametrize("root_kind", ("symlink", "fifo"))
def test_staging_rejects_symlink_or_nonregular_private_root(
    tmp_path: Path,
    root_kind: str,
) -> None:
    """The private root cannot be redirected to a symlink or non-directory inode."""
    module = importlib.import_module("ksi_processing_controller.external_inspector_staging")
    private_root = tmp_path / "private"
    if root_kind == "symlink":
        target = tmp_path / "target"
        target.mkdir(mode=0o700)
        private_root.symlink_to(target, target_is_directory=True)
    else:
        os.mkfifo(private_root, mode=0o600)
    staging = module.FileSystemInputStaging(
        private_root=private_root,
        reader_mapping=_Mapping(_Reader()),
        acl=_Acl(),
    )

    with pytest.raises(Exception, match="private|unavailable"):
        staging.begin(maximum_bytes=10, deadline_monotonic=time.monotonic() + 1.0)


def test_staging_rejects_a_private_root_owned_by_another_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A private root is tied to the launcher identity; UID guessing cannot substitute it."""
    module = importlib.import_module("ksi_processing_controller.external_inspector_staging")
    private_root = tmp_path / "private"
    private_root.mkdir(mode=0o700)
    actual_uid = os.geteuid()
    monkeypatch.setattr(module.os, "geteuid", lambda: actual_uid + 1)
    staging = module.FileSystemInputStaging(
        private_root=private_root,
        reader_mapping=_Mapping(_Reader()),
        acl=_Acl(),
    )

    with pytest.raises(Exception, match="private"):
        staging.begin(maximum_bytes=10, deadline_monotonic=time.monotonic() + 1.0)


def test_bind_uses_the_sealed_descriptor_after_path_replacement(tmp_path: Path) -> None:
    """A renamed private directory plus an evil replacement cannot alter the capability."""
    staging, _ = _staging(tmp_path)
    payload = b"bound"
    mutable = staging.begin(maximum_bytes=len(payload), deadline_monotonic=time.monotonic() + 1.0)
    mutable.write(payload)
    sealed = mutable.seal_for_reader(
        expected_sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
        expected_size_bytes=len(payload),
        reader=_Reader(),
        supplementary_groups=(),
        deadline_monotonic=time.monotonic() + 1.0,
    )
    source_path = next((tmp_path / "private").glob("*/artifact"))
    original_parent = source_path.parent
    moved_parent = original_parent.with_name(original_parent.name + "-moved")
    original_parent.rename(moved_parent)
    original_parent.mkdir(mode=0o700)
    (original_parent / "artifact").write_bytes(b"evil!")

    bind = sealed.prepare_read_only_bind(deadline_monotonic=time.monotonic() + 1.0)

    assert (
        bind.source.read_at(
            offset=0, maximum_bytes=len(payload), deadline_monotonic=time.monotonic() + 1.0
        )
        == payload
    )
    sealed.abort()


def test_bind_source_remains_the_retained_inode_after_its_private_path_moves(
    tmp_path: Path,
) -> None:
    """The runtime bind source must not be an absolute pathname that can be substituted later."""
    staging, _ = _staging(tmp_path)
    payload = b"bound"
    mutable = staging.begin(maximum_bytes=len(payload), deadline_monotonic=time.monotonic() + 1.0)
    mutable.write(payload)
    sealed = mutable.seal_for_reader(
        expected_sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
        expected_size_bytes=len(payload),
        reader=_Reader(),
        supplementary_groups=(),
        deadline_monotonic=time.monotonic() + 1.0,
    )
    source_path = next((tmp_path / "private").glob("*/artifact"))
    moved_parent = source_path.parent.with_name(source_path.parent.name + "-moved")
    source_path.parent.rename(moved_parent)

    bind = sealed.prepare_read_only_bind(deadline_monotonic=time.monotonic() + 1.0)

    assert (
        bind.source.read_at(
            offset=0, maximum_bytes=len(payload), deadline_monotonic=time.monotonic() + 1.0
        )
        == payload
    )
    sealed.abort()


def test_abort_is_idempotent_and_never_closes_a_reused_descriptor(tmp_path: Path) -> None:
    """Repeated cleanup cannot close a file descriptor subsequently reused by the process."""
    staging, _ = _staging(tmp_path)
    payload = b"bound"
    mutable = staging.begin(maximum_bytes=len(payload), deadline_monotonic=time.monotonic() + 1.0)
    mutable.write(payload)
    sealed = mutable.seal_for_reader(
        expected_sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
        expected_size_bytes=len(payload),
        reader=_Reader(),
        supplementary_groups=(),
        deadline_monotonic=time.monotonic() + 1.0,
    )
    bind = sealed.prepare_read_only_bind(deadline_monotonic=time.monotonic() + 1.0)
    sealed.abort()
    replacement = os.open(tmp_path / "replacement", os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        # Descriptor recycling is normal; this specifically proves the stale
        # capability cannot close an unrelated later owner of that number.
        sealed.abort()
        os.fstat(replacement)
    finally:
        os.close(replacement)
    with pytest.raises(Exception, match="no longer live"):
        bind.source.read_at(offset=0, maximum_bytes=1, deadline_monotonic=time.monotonic() + 1.0)


def test_seal_failure_retires_all_owned_descriptors_before_a_later_abort(tmp_path: Path) -> None:
    """A failed sealing path cannot leave stale FD numbers for a later cleanup call to close."""
    staging, _ = _staging(tmp_path)
    mutable = staging.begin(maximum_bytes=5, deadline_monotonic=time.monotonic() + 1.0)
    mutable.write(b"bound")

    with pytest.raises(Exception, match="digest"):
        mutable.seal_for_reader(
            expected_sha256="sha256:" + hashlib.sha256(b"other").hexdigest(),
            expected_size_bytes=5,
            reader=_Reader(),
            supplementary_groups=(),
            deadline_monotonic=time.monotonic() + 1.0,
        )

    replacement = os.open(tmp_path / "replacement-after-failure", os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        mutable.abort()
        os.fstat(replacement)
    finally:
        os.close(replacement)


def test_bind_rechecks_the_signed_supplementary_group_mapping(tmp_path: Path) -> None:
    """A fixed UID mapping witness must retain the signed supplementary group set."""
    module = importlib.import_module("ksi_processing_controller.external_inspector_staging")
    mapping = _Mapping(_Reader(), groups=(77,))
    staging = module.FileSystemInputStaging(
        private_root=tmp_path / "private",
        reader_mapping=mapping,
        acl=_Acl(),
    )
    payload = b"bound"
    mutable = staging.begin(maximum_bytes=len(payload), deadline_monotonic=time.monotonic() + 1.0)
    mutable.write(payload)
    sealed = mutable.seal_for_reader(
        expected_sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
        expected_size_bytes=len(payload),
        reader=_Reader(),
        supplementary_groups=(77,),
        deadline_monotonic=time.monotonic() + 1.0,
    )

    sealed.prepare_read_only_bind(deadline_monotonic=time.monotonic() + 1.0)

    assert mapping.calls[-1] == (10001, 10001, (77,))
    sealed.abort()


@pytest.mark.parametrize(
    ("expected_size", "expected_digest"),
    [
        (4, "sha256:" + hashlib.sha256(b"bound").hexdigest()),
        (5, "sha256:" + hashlib.sha256(b"other").hexdigest()),
    ],
)
def test_seal_rejects_short_or_hash_mismatched_stream_before_backend_binding(
    tmp_path: Path,
    expected_size: int,
    expected_digest: str,
) -> None:
    """The sealed binding validates both count and digest before a capability exists."""
    staging, _ = _staging(tmp_path)
    mutable = staging.begin(maximum_bytes=5, deadline_monotonic=time.monotonic() + 1.0)
    mutable.write(b"bound")

    with pytest.raises(Exception, match="count|digest|sealed"):
        mutable.seal_for_reader(
            expected_sha256=expected_digest,
            expected_size_bytes=expected_size,
            reader=_Reader(),
            supplementary_groups=(),
            deadline_monotonic=time.monotonic() + 1.0,
        )


@pytest.mark.parametrize(
    ("mapping_reader", "acl"),
    [
        (None, _Acl()),
        (_Reader(mapping_witness="stale"), _Acl()),
        (_Reader(), _Acl(verify_result=False)),
    ],
)
def test_bind_requires_current_exact_mapping_and_acl(
    tmp_path: Path,
    mapping_reader: _Reader | None,
    acl: _Acl,
) -> None:
    """Missing, stale, or revoked reader access is a typed unavailable condition."""
    module = importlib.import_module("ksi_processing_controller.external_inspector_staging")
    mapping = _Mapping(_Reader())
    staging = module.FileSystemInputStaging(
        private_root=tmp_path / "private",
        reader_mapping=mapping,
        acl=acl,
    )
    payload = b"bound"
    mutable = staging.begin(maximum_bytes=len(payload), deadline_monotonic=time.monotonic() + 1.0)
    mutable.write(payload)
    sealed = mutable.seal_for_reader(
        expected_sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
        expected_size_bytes=len(payload),
        reader=_Reader(),
        supplementary_groups=(),
        deadline_monotonic=time.monotonic() + 1.0,
    )
    mapping.reader = mapping_reader

    with pytest.raises(Exception, match="mapping|ACL|stale|unavailable"):
        sealed.prepare_read_only_bind(deadline_monotonic=time.monotonic() + 1.0)

    sealed.abort()
