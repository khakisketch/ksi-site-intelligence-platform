"""Contract coverage for the private, retryable SANITIZE candidate handoff.

The candidate stays an anonymous local file.  These tests deliberately open no
Core route, object storage transport, or display-artifact receipt.
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from ksi_event_contracts.external_artifact_validation import (
    ExternalArtifactInspectionRequestV1,
    ExternalValidationPolicyV1,
    PolicyStatus,
    ResourceEnvelopeV1,
    SealedExternalSubjectV1,
)
from ksi_processing_controller.external_artifact_inspection_worker import (
    CurrentAuthorityLost,
    FileSystemSanitizedOutputSink,
    PrivateSanitizedCandidateReaderPort,
)
from ksi_processing_controller.external_inspector_protocol import (
    InspectorLaunchRequestV1,
    InspectorLaunchResultV1,
    InspectorOperation,
    LocalLeaseFenceV1,
    ProtocolDeadline,
    ProtocolDeadlineExceeded,
    SealedByteBindingV1,
)


def _digest(marker: str) -> str:
    return "sha256:" + marker * 64


def _bytes_digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _policy() -> ExternalValidationPolicyV1:
    envelope = ResourceEnvelopeV1(
        max_input_bytes=128,
        max_streamed_bytes=128,
        max_tiff_directories=4,
        max_tiff_entries=32,
        max_pixels=1_000,
        max_bands=4,
        max_blocks=64,
        max_decompressed_bytes=1_024,
        max_sample_bytes=1_024,
        max_geometry_vertices=64,
        max_cpu_seconds=2.0,
        max_memory_bytes=1_024,
        max_workspace_bytes=1_024,
        max_output_bytes=1_024,
        max_tenant_concurrency=1,
        max_queue_depth=4,
        max_deadline_seconds=10.0,
        lease_duration_seconds=2.0,
        max_retry_attempts=1,
    ).sealed()
    return ExternalValidationPolicyV1(
        policy_id="synthetic-policy",
        version=1,
        status=PolicyStatus.ACTIVE,
        parser_build_digest=_digest("c"),
        grammar_digest=_digest("d"),
        resource_envelope=envelope,
        resource_envelope_digest=envelope.resource_envelope_digest,
        authority_record_digest=_digest("e"),
        inspection_rule_ids=(),
        evidence_rule_ids=(),
        compatibility_mapping_digests=(),
        synthetic_test_only=True,
    ).sealed()


def _request(policy: ExternalValidationPolicyV1) -> ExternalArtifactInspectionRequestV1:
    assert policy.policy_digest is not None
    return ExternalArtifactInspectionRequestV1(
        request_id="inspection-request-1",
        subject=SealedExternalSubjectV1(
            organization_id="organization-1",
            site_id="site-1",
            work_order_id="work-order-1",
            submission_id="submission-1",
            revision=1,
            submission_digest=_digest("a"),
            manifest_digest=_digest("b"),
        ),
        inspection_policy_id=policy.policy_id,
        inspection_policy_version=policy.version,
        inspection_policy_digest=policy.policy_digest,
        issued_at=datetime(2026, 9, 9, tzinfo=UTC),
        idempotency_key="inspection-key-1",
    )


def _launch_request(
    *, payload: bytes, attempt_nonce: str = "attempt-nonce-1"
) -> InspectorLaunchRequestV1:
    policy = _policy()
    return InspectorLaunchRequestV1.seal(
        operation=InspectorOperation.SANITIZE,
        request=_request(policy),
        fence=LocalLeaseFenceV1(
            worker_instance_id="123e4567-e89b-42d3-a456-426614174000",
            lease_acquisition_id="123e4567-e89b-42d3-a456-426614174002",
            lease_generation=1,
        ),
        subject=_request(policy).subject,
        sealed_byte_binding=SealedByteBindingV1(
            artifact_id="ortho",
            observed_sha256=_bytes_digest(payload),
            observed_size_bytes=len(payload),
        ),
        policy=policy,
        attempt_nonce=attempt_nonce,
    )


def _sealed_candidate(
    tmp_path: Path, *, payload: bytes = b"sanitized-output"
) -> tuple[FileSystemSanitizedOutputSink, InspectorLaunchRequestV1, InspectorLaunchResultV1, Path]:
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    request = _launch_request(payload=b"sealed-input")
    sink = FileSystemSanitizedOutputSink(private_root=root)
    deadline_monotonic = time.monotonic() + 1.0
    transaction = sink.begin(
        request,
        maximum_bytes=1_024,
        deadline_monotonic=deadline_monotonic,
    )
    transaction.write(payload, deadline_monotonic=deadline_monotonic)
    terminal = InspectorLaunchResultV1.completed_sanitized(
        request.attempt_nonce,
        request.canonical_input_digest,
        request.policy.parser_build_digest,
        len(payload),
        _bytes_digest(payload),
    )
    transaction.finish(terminal, deadline_monotonic=deadline_monotonic)
    return sink, request, terminal, root


def _open(
    sink: FileSystemSanitizedOutputSink,
    request: InspectorLaunchRequestV1,
    terminal: InspectorLaunchResultV1,
    *,
    deadline: ProtocolDeadline | None = None,
    wait_is_current: Callable[[], bool] | None = None,
) -> PrivateSanitizedCandidateReaderPort:
    guard: Callable[[], bool] = (lambda: True) if wait_is_current is None else wait_is_current
    return sink.open_private_candidate(
        request,
        terminal,
        deadline=deadline or ProtocolDeadline(1_000, time.monotonic),
        wait_is_current=guard,
        heartbeat_interval_millis=10,
    )


def _read(
    reader: PrivateSanitizedCandidateReaderPort,
    maximum_bytes: int,
    *,
    deadline: ProtocolDeadline | None = None,
    guard: Callable[[], bool] | None = None,
) -> bytes:
    return reader.read_chunk(
        maximum_bytes,
        deadline=deadline or ProtocolDeadline(1_000, time.monotonic),
        wait_is_current=(lambda: True) if guard is None else guard,
        heartbeat_interval_millis=10,
    )


def test_private_candidate_retries_anonymous_bytes_from_offset_zero_without_public_receipt(
    tmp_path: Path,
) -> None:
    sink, request, terminal, root = _sealed_candidate(tmp_path)

    first = _open(sink, request, terminal)
    assert _read(first, 5) == b"sanit"
    assert _read(first, 1_024) == b"ized-output"
    assert _read(first, 1_024) == b""
    first.close()

    retry = _open(sink, request, terminal)
    assert _read(retry, 1_024) == b"sanitized-output"
    retry.close()

    assert list(root.iterdir()) == []
    assert not any(name in dir(retry) for name in ("path", "fd", "receipt"))
    sink.abort_attempt(request)
    assert list(root.iterdir()) == []


def test_private_candidate_refuses_unfinished_mismatched_and_cross_attempt_before_opening_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink, request, terminal, _ = _sealed_candidate(tmp_path)
    candidate = next(iter(sink._sealed.values()))
    opened = False

    def fail_if_opened() -> None:
        nonlocal opened
        opened = True
        raise AssertionError("invalid candidate reached staged reader open")

    monkeypatch.setattr(candidate._staged, "open_sealed_reader", fail_if_opened, raising=False)
    mismatched = InspectorLaunchResultV1.completed_sanitized(
        request.attempt_nonce,
        request.canonical_input_digest,
        request.policy.parser_build_digest,
        terminal.output_size_bytes or 1,
        _digest("f"),
    )
    with pytest.raises(CurrentAuthorityLost, match="terminal"):
        _open(sink, request, mismatched)
    other_request = _launch_request(payload=b"sealed-input", attempt_nonce="attempt-nonce-2")
    with pytest.raises(CurrentAuthorityLost):
        _open(sink, other_request, terminal)
    assert opened is False

    unfinished_root = tmp_path / "unfinished"
    unfinished_root.mkdir(mode=0o700)
    unfinished_root.chmod(0o700)
    unfinished_sink = FileSystemSanitizedOutputSink(private_root=unfinished_root)
    unfinished = _launch_request(payload=b"sealed-input", attempt_nonce="attempt-nonce-3")
    unfinished_sink.begin(
        unfinished,
        maximum_bytes=1_024,
        deadline_monotonic=time.monotonic() + 1.0,
    )
    unfinished_terminal = InspectorLaunchResultV1.completed_sanitized(
        unfinished.attempt_nonce,
        unfinished.canonical_input_digest,
        unfinished.policy.parser_build_digest,
        1,
        _bytes_digest(b"x"),
    )
    with pytest.raises(CurrentAuthorityLost, match="sealed"):
        _open(unfinished_sink, unfinished, unfinished_terminal)
    unfinished_sink.abort_attempt(unfinished)


@pytest.mark.parametrize(
    "update",
    [
        lambda request: {"fence": request.fence.model_copy(update={"lease_generation": 999})},
        lambda request: {"subject": request.subject.model_copy(update={"site_id": "other-site"})},
        lambda request: {
            "sealed_byte_binding": request.sealed_byte_binding.model_copy(
                update={"artifact_id": "other-input"}
            )
        },
    ],
    ids=("stale-fence", "stale-subject", "stale-input-binding"),
)
def test_private_candidate_revalidates_canonical_launch_before_staged_reader_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    update: Callable[[InspectorLaunchRequestV1], dict[str, object]],
) -> None:
    sink, request, terminal, _ = _sealed_candidate(tmp_path)
    candidate = next(iter(sink._sealed.values()))
    opened = False

    def fail_if_opened() -> None:
        nonlocal opened
        opened = True
        raise AssertionError("canonical-invalid launch reached staged reader open")

    monkeypatch.setattr(candidate._staged, "open_sealed_reader", fail_if_opened)
    unsafe = request.model_copy(update=update(request))
    with pytest.raises(ValueError):
        InspectorLaunchRequestV1.model_validate(unsafe.__dict__)
    with pytest.raises(CurrentAuthorityLost, match="launch"):
        _open(sink, unsafe, terminal)
    assert opened is False
    sink.abort_attempt(request)


@pytest.mark.parametrize("unsafe_size", [True, 1.0], ids=("boolean", "float"))
def test_private_candidate_revalidates_terminal_types_before_staged_reader_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unsafe_size: bool | float,
) -> None:
    sink, request, terminal, _ = _sealed_candidate(tmp_path, payload=b"x")
    candidate = next(iter(sink._sealed.values()))
    opened = False

    def fail_if_opened() -> None:
        nonlocal opened
        opened = True
        raise AssertionError("strictly invalid terminal reached staged reader open")

    monkeypatch.setattr(candidate._staged, "open_sealed_reader", fail_if_opened)
    unsafe = terminal.model_copy(update={"output_size_bytes": unsafe_size})
    with pytest.raises(ValueError):
        InspectorLaunchResultV1.model_validate(unsafe.__dict__)
    with pytest.raises(CurrentAuthorityLost, match="terminal"):
        _open(sink, request, unsafe)
    assert opened is False
    sink.abort_attempt(request)


def test_private_candidate_refuses_false_open_guard_and_later_cancellation_before_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink, request, terminal, _ = _sealed_candidate(tmp_path)
    candidate = next(iter(sink._sealed.values()))
    opened = False

    def fail_if_opened() -> None:
        nonlocal opened
        opened = True
        raise AssertionError("false authority reached staged reader open")

    with monkeypatch.context() as scoped:
        scoped.setattr(candidate._staged, "open_sealed_reader", fail_if_opened)
        with pytest.raises(CurrentAuthorityLost, match="authority"):
            _open(sink, request, terminal, wait_is_current=lambda: False)
    assert opened is False

    reader = _open(sink, request, terminal)
    with pytest.raises(CurrentAuthorityLost, match="authority"):
        _read(reader, 1, guard=lambda: False)
    reader.close()


def test_private_reader_retains_open_authority_and_deadline_against_later_caller_values(
    tmp_path: Path,
) -> None:
    sink, request, terminal, _ = _sealed_candidate(tmp_path)
    authority = {"current": True}
    reader = _open(sink, request, terminal, wait_is_current=lambda: authority["current"])
    authority["current"] = False
    with pytest.raises(CurrentAuthorityLost, match="authority"):
        _read(reader, 1, guard=lambda: True)
    reader.close()

    class _Clock:
        value = 10.0

        def __call__(self) -> float:
            return self.value

    clock = _Clock()
    original = ProtocolDeadline(100, clock)
    reader = _open(sink, request, terminal, deadline=original)
    clock.value = 10.2
    with pytest.raises(ProtocolDeadlineExceeded):
        _read(reader, 1, deadline=ProtocolDeadline(1_000, clock))
    reader.close()


def test_private_reader_close_and_sink_abort_close_the_right_lifetimes(tmp_path: Path) -> None:
    sink, request, terminal, root = _sealed_candidate(tmp_path)
    reader = _open(sink, request, terminal)
    reader.close()
    with pytest.raises(CurrentAuthorityLost, match="closed"):
        _read(reader, 1)

    retained = _open(sink, request, terminal)
    sink.abort_attempt(request)
    with pytest.raises(CurrentAuthorityLost, match="retired"):
        _read(retained, 1)
    retained.close()
    assert list(root.iterdir()) == []


def test_private_reader_serializes_abort_with_a_bounded_explicit_offset_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink, request, terminal, root = _sealed_candidate(tmp_path)
    reader = _open(sink, request, terminal)
    candidate = next(iter(sink._sealed.values()))
    staged = candidate._staged
    original_open = staged.open_sealed_reader
    entered = threading.Event()
    release = threading.Event()

    def blocking_open() -> Any:
        handle = original_open()
        original_read = handle.read_at

        def blocking_read_at(**kwargs: object) -> bytes:
            entered.set()
            assert release.wait(timeout=1)
            return original_read(**kwargs)

        monkeypatch.setattr(handle, "read_at", blocking_read_at)
        return handle

    monkeypatch.setattr(staged, "open_sealed_reader", blocking_open)
    reader.close()
    reader = _open(sink, request, terminal)
    observed: list[bytes] = []

    def read_once() -> None:
        observed.append(_read(reader, 1))

    reading = threading.Thread(target=read_once)
    reading.start()
    assert entered.wait(timeout=1)
    aborting = threading.Thread(target=lambda: sink.abort_attempt(request))
    aborting.start()
    release.set()
    reading.join(timeout=1)
    aborting.join(timeout=1)

    assert not reading.is_alive()
    assert not aborting.is_alive()
    assert observed == [b"s"]
    with pytest.raises(CurrentAuthorityLost, match="retired"):
        _read(reader, 1)
    reader.close()
    assert list(root.iterdir()) == []
