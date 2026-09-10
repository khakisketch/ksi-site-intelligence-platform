"""Concrete V2 Docker grammar remains separate from the V1 inspector backend."""

from __future__ import annotations

import dataclasses
from hashlib import sha256
from types import SimpleNamespace
from typing import Any, cast

import pytest
from ksi_processing_controller.external_inspector_attempts import PrivateStagingRootV1
from ksi_processing_controller.external_inspector_container_protocol import (
    FixedContainerConfigurationV1,
    FixedInputMountV1,
)
from ksi_processing_controller.external_inspector_launcher import InspectorEffectiveLimitsV1
from ksi_processing_controller.external_inspector_protocol import ProtocolDeadline
from ksi_processing_controller.external_inspector_runtime import (
    CpuCounterUnitV1,
    FixedRuntimeMeasurementV1,
    RuntimeControlDispositionV1,
)
from ksi_processing_controller.external_measurement_attempts import (
    MeasurementRuntimeParentReceiptV2,
    new_measurement_attempt_binding,
)
from ksi_processing_controller.external_measurement_container_protocol import (
    MeasurementContainerFrameLimitsV2,
    build_completed_frame_v2,
    build_failed_frame_v2,
    build_prepare_frame_v2,
    build_primary_mount_verified_frame,
    build_secondary_staged_frame,
    decode_measurement_container_frame,
    encode_measurement_container_frame,
)
from ksi_processing_controller.external_measurement_docker_backend import (
    DockerMeasurementActiveV2,
    DockerMeasurementBackend,
    DockerMeasurementBackendUnavailable,
    _AttachedMeasurementReaderV2,
    _require_exact_control,
    _SecondarySinkV2,
)
from test_external_measurement_protocol import measurement_manifest_request


class _PrimarySource:
    def read_at(self, **_kwargs: object) -> bytes:
        return b""

    def consume_fd(self, consumer, **_kwargs: object):  # type: ignore[no-untyped-def]
        return consumer(9)


def _request_with_secondary_bytes():  # type: ignore[no-untyped-def]
    manifest, request = measurement_manifest_request()
    secondary_bytes = b"current-raster"
    current = request.volume_request.current.model_copy(
        update={
            "observed_sha256": "sha256:" + sha256(secondary_bytes).hexdigest(),
            "observed_size_bytes": len(secondary_bytes),
        }
    )
    volume = request.volume_request.model_copy(
        update={"current": current, "request_digest": None}
    ).sealed()
    secondary = request.inputs[1].model_copy(
        update={
            "observed_sha256": current.observed_sha256,
            "observed_size_bytes": current.observed_size_bytes,
        }
    )
    return (
        manifest,
        request.model_copy(
            update={
                "inputs": (request.inputs[0], secondary),
                "volume_request": volume,
                "canonical_input_digest": None,
            }
        ).sealed(),
        secondary_bytes,
    )


def _configuration(request, manifest):  # type: ignore[no-untyped-def]
    envelope = request.validation_policy.resource_envelope
    assert envelope is not None
    hard = manifest.body.hard_ceilings
    return FixedContainerConfigurationV1(
        image_manifest_digest=manifest.body.image_identity.oci_manifest_digest,
        image_config_digest=manifest.body.image_identity.oci_config_digest,
        runtime_uid=manifest.body.runtime_uid,
        runtime_gid=manifest.body.runtime_gid,
        supplementary_groups=(),
        runtime_environment=manifest.body.runtime_environment,
        allowed_grid_digests=manifest.body.allowed_grid_digests,
        input_mount=FixedInputMountV1(
            source=_PrimarySource(),
            target_path="/input/artifact.tif",
            read_only=True,
            observed_sha256=request.inputs[0].observed_sha256,
            observed_size_bytes=request.inputs[0].observed_size_bytes,
            source_device=1,
            source_inode=2,
            reader_mapping_witness="measurement-primary-v2",
        ),
        memory_bytes=min(envelope.max_memory_bytes, hard.max_memory_bytes),
        tmpfs_bytes=min(envelope.max_workspace_bytes, hard.max_tmpfs_bytes),
        swap_bytes=0,
        pids=hard.max_pids,
        cpu_period_micros=hard.cpu_period_micros,
        cpu_quota_micros=hard.cpu_quota_micros,
        wall_time_millis=hard.max_wall_time_millis,
        log_bytes=hard.max_log_bytes,
        output_bytes=hard.max_output_bytes,
        cpu_counter_unit=CpuCounterUnitV1.CPU_USEC,
        cpu_budget_counter=1_000_000,
    )


def _effective_limits(configuration):  # type: ignore[no-untyped-def]
    return InspectorEffectiveLimitsV1(
        max_input_bytes=1_000,
        max_memory_bytes=configuration.memory_bytes,
        max_workspace_bytes=configuration.tmpfs_bytes,
        max_output_bytes=configuration.output_bytes,
        max_wall_time_millis=configuration.wall_time_millis,
        max_pids=configuration.pids,
        cpu_period_micros=configuration.cpu_period_micros,
        cpu_quota_micros=configuration.cpu_quota_micros,
        max_log_bytes=configuration.log_bytes,
        max_cpu_seconds=1.0,
    )


def _measurement(runtime_id: str) -> FixedRuntimeMeasurementV1:
    return FixedRuntimeMeasurementV1(
        runtime_id=runtime_id,
        counter_unit=CpuCounterUnitV1.CPU_USEC,
        baseline_counter=10,
        final_counter=15,
        consumed_counter=5,
        budget_counter=1_000_000,
        threshold_exceeded=False,
        disposition=RuntimeControlDispositionV1.COMPLETED,
        kill_latency_seconds=None,
    )


def test_v2_backend_orders_two_input_grammar_half_close_and_host_proof() -> None:
    """Only a durable created ID may reach the V2 attached/started grammar."""

    manifest, request, secondary_bytes = _request_with_secondary_bytes()
    configuration = _configuration(request, manifest)
    binding = new_measurement_attempt_binding(
        request=request,
        manifest=manifest,
        root=PrivateStagingRootV1(1, 2, 0o700, 1000, 1000),
        systemd_base_slice="ksi-measurement.slice",
        cpu_budget_counter=configuration.cpu_budget_counter,
        allocation_nonce="allocation-v2",
    )
    runtime_parent = MeasurementRuntimeParentReceiptV2(
        unit_name=binding.systemd_slice_name,
        object_path="/org/freedesktop/systemd1/unit/measurement",
        description="ksi-external-measurement-attempt.v2:" + binding.digest,
        slice_name=binding.systemd_base_slice,
        control_group="/ksi-measurement.slice/" + binding.systemd_slice_name,
        invocation_id="a" * 32,
        device=1,
        inode=2,
        controllers=("cpu", "memory", "pids"),
        cpu_counter_unit="CPU_USEC",
        baseline_cpu_counter=10,
        cpu_budget_counter=configuration.cpu_budget_counter,
    )
    events: list[str] = []
    frame_limits = MeasurementContainerFrameLimitsV2(maximum_frame_bytes=128_000)

    class _Session:
        def __init__(self) -> None:
            self.writes: list[bytes] = []
            self.finished = False
            self.reads = 0

        def send_stdin(self, payload: bytes, *, deadline_monotonic: float) -> None:
            assert deadline_monotonic == 10.0
            assert self.finished is False
            self.writes.append(payload)
            if len(self.writes) < 3:
                events.append("control")
            elif payload == secondary_bytes:
                events.append("secondary")
            else:
                events.append("execute")

        def finish_stdin(self, *, deadline_monotonic: float) -> None:
            assert deadline_monotonic == 10.0
            assert self.finished is False
            self.finished = True
            events.append("finish-stdin")

        def read_frame(self, **_kwargs: object):  # type: ignore[no-untyped-def]
            self.reads += 1
            prepare = decode_measurement_container_frame(self.writes[0], limits=frame_limits)
            if self.reads == 1:
                assert self.writes[1] == encode_measurement_container_frame(
                    {
                        "protocolVersion": "external-measurement-container.v2",
                        "frame": "SECONDARY_BEGIN",
                        "attemptNonce": request.attempt_nonce,
                        "outerCanonicalInputDigest": request.canonical_input_digest,
                        "prepareDigest": prepare["prepareDigest"],
                        "role": request.inputs[1].role,
                        "artifactId": request.inputs[1].artifact_id,
                        "expectedSizeBytes": request.inputs[1].observed_size_bytes,
                        "expectedSha256": request.inputs[1].observed_sha256,
                    },
                    limits=frame_limits,
                )
                return 1, encode_measurement_container_frame(
                    build_secondary_staged_frame(
                        prepare=prepare,
                        actual_size_bytes=len(secondary_bytes),
                        actual_sha256="sha256:" + sha256(secondary_bytes).hexdigest(),
                    ),
                    limits=frame_limits,
                )
            if self.reads == 2:
                return 1, encode_measurement_container_frame(
                    build_primary_mount_verified_frame(
                        prepare=prepare,
                        actual_size_bytes=request.inputs[0].observed_size_bytes,
                        actual_sha256=request.inputs[0].observed_sha256,
                    ),
                    limits=frame_limits,
                )
            if self.reads == 3:
                assert self.finished is True
                bindings = [
                    {
                        "role": item.role,
                        "artifactId": item.artifact_id,
                        "observedSha256": item.observed_sha256,
                        "observedSizeBytes": item.observed_size_bytes,
                    }
                    for item in request.inputs
                ]
                aggregate = {
                    "metricType": "RELATIVE_VOLUME_AGGREGATE_V2",
                    "zoneId": request.volume_request.zone_snapshot.work_area_id,
                    "metrics": {
                        "zoneCellCount": 4,
                        "commonValidCellCount": 4,
                        "zoneAreaM2": 4.0,
                        "measuredAreaM2": 4.0,
                        "commonValidFraction": 1.0,
                        "cutM3": 1.0,
                        "fillM3": 5.0,
                        "netM3": 4.0,
                        "thresholdM": request.volume_execution_policy.threshold_m,
                        "uncertaintyM3": None,
                        "uncertaintyNote": (
                            "Independent checkpoint RMSE is unavailable for one or both epochs."
                        ),
                    },
                }
                return 1, encode_measurement_container_frame(
                    build_completed_frame_v2(
                        prepare=prepare,
                        input_bindings=bindings,
                        aggregate=aggregate,
                    ),
                    limits=frame_limits,
                )
            return None

        def close(self) -> None:
            events.append("session-close")

    session = _Session()

    class _Runtime:
        def create_exact(self, **_kwargs: object) -> str:
            events.append("create")
            return "runtime-v2"

        def attach_exact(self, runtime_id: str, *, deadline_monotonic: float) -> _Session:
            assert runtime_id == "runtime-v2" and deadline_monotonic == 10.0
            events.append("attach")
            return session

        def start_after_container_bound(self, **_kwargs: object) -> None:
            assert len(session.writes) == 2
            events.append("start")

        def wait_exact(self, runtime_id: str, *, deadline_monotonic: float) -> dict[str, int]:
            assert runtime_id == "runtime-v2" and deadline_monotonic == 10.0
            events.append("wait")
            return {"StatusCode": 0}

    class _Scope:
        def verify_exact(self, **_kwargs: object) -> None:
            assert events[-1] == "start"
            events.append("scope")

    class _ActiveMeasurement:
        def finalized_measurement(self) -> FixedRuntimeMeasurementV1:
            events.append("final-proof")
            return _measurement("runtime-v2")

        def close(self) -> None:
            events.append("measurement-close")

    class _Measurements:
        def start(self, **_kwargs: object) -> _ActiveMeasurement:
            assert events[-1] == "scope"
            events.append("measurement-start")
            return _ActiveMeasurement()

    backend = DockerMeasurementBackend(
        runtime=cast(Any, _Runtime()),
        started_runtime=_Scope(),
        measurements=_Measurements(),
        frame_limits=frame_limits,
        monotonic=lambda: 0.0,
    )
    created = backend.create(
        request=request,
        binding=binding,
        manifest=manifest,
        configuration=configuration,
        staged_input=SimpleNamespace(),
        deadline_monotonic=10.0,
    )
    assert created.runtime_id == "runtime-v2"
    active = backend.open_started(
        request=request,
        binding=binding,
        manifest=manifest,
        configuration=configuration,
        staged_input=SimpleNamespace(),
        runtime_id=created.runtime_id,
        effective_limits=_effective_limits(configuration),
        runtime_parent=runtime_parent,
        monitor_termination=lambda _reason: 0.0,
        is_cancelled=lambda: False,
        deadline_monotonic=10.0,
    )
    active.secondary_sink.write_chunk(
        secondary_bytes,
        deadline=ProtocolDeadline.at_expires_at(10.0, monotonic=lambda: 0.0),
        wait_is_current=lambda: True,
        heartbeat_interval_millis=50,
    )
    completed = active.complete()
    active.close()

    assert completed.runtime_measurement == _measurement("runtime-v2")
    assert completed.terminal["frame"] == "COMPLETED"
    assert events == [
        "create",
        "attach",
        "control",
        "control",
        "start",
        "scope",
        "measurement-start",
        "secondary",
        "execute",
        "finish-stdin",
        "wait",
        "final-proof",
        "session-close",
    ]


def test_v2_backend_rejects_nonintegral_cpu_seconds_before_attach() -> None:
    """The cgroup counter budget cannot silently truncate a signed CPU ceiling."""

    manifest, request, _secondary_bytes = _request_with_secondary_bytes()
    configuration = _configuration(request, manifest)
    binding = new_measurement_attempt_binding(
        request=request,
        manifest=manifest,
        root=PrivateStagingRootV1(1, 2, 0o700, 1000, 1000),
        systemd_base_slice="ksi-measurement.slice",
        cpu_budget_counter=configuration.cpu_budget_counter,
        allocation_nonce="allocation-v2",
    )

    class _Runtime:
        def attach_exact(self, **_kwargs: object) -> object:
            raise AssertionError("invalid CPU budget must fail before Docker attach")

    backend = DockerMeasurementBackend(
        runtime=cast(Any, _Runtime()),
        started_runtime=SimpleNamespace(),
        measurements=SimpleNamespace(),
        frame_limits=MeasurementContainerFrameLimitsV2(maximum_frame_bytes=128_000),
        monotonic=lambda: 0.0,
    )
    with pytest.raises(DockerMeasurementBackendUnavailable, match="CPU limit"):
        backend.open_started(
            request=request,
            binding=binding,
            manifest=manifest,
            configuration=configuration,
            staged_input=SimpleNamespace(),
            runtime_id="runtime-v2",
            effective_limits=_effective_limits(configuration).model_copy(
                update={"max_cpu_seconds": 0.9999999}
            ),
            runtime_parent=cast(Any, SimpleNamespace()),
            monitor_termination=lambda _reason: 0.0,
            is_cancelled=lambda: False,
            deadline_monotonic=10.0,
        )


@pytest.mark.parametrize("effect_path", ("create", "open_started"))
@pytest.mark.parametrize("mismatch", ("attempt_nonce", "worker_owner"))
def test_v2_backend_rejects_mismatched_attempt_or_owner_before_runtime_effect(
    effect_path: str, mismatch: str
) -> None:
    """The sealed request nonce and fence owner bind both Docker effect paths."""

    manifest, request, _secondary_bytes = _request_with_secondary_bytes()
    configuration = _configuration(request, manifest)
    binding = new_measurement_attempt_binding(
        request=request,
        manifest=manifest,
        root=PrivateStagingRootV1(1, 2, 0o700, 1000, 1000),
        systemd_base_slice="ksi-measurement.slice",
        cpu_budget_counter=configuration.cpu_budget_counter,
        allocation_nonce="allocation-v2",
    )
    if mismatch == "attempt_nonce":
        replacement_nonce = "other-attempt"
        stable = sha256(replacement_nonce.encode("utf-8")).hexdigest()[:32]
        binding = dataclasses.replace(
            binding,
            attempt_nonce=replacement_nonce,
            container_name="external-measurement-" + stable,
            systemd_slice_name="ksi-measurement-a" + stable + ".slice",
            staging=dataclasses.replace(
                binding.staging,
                attempt_nonce=replacement_nonce,
                staging_name="measurement-" + stable,
            ),
        )
    else:
        binding = dataclasses.replace(
            binding,
            owner="other-worker",
            staging=dataclasses.replace(binding.staging, owner="other-worker"),
        )

    effects: list[str] = []

    class _Runtime:
        def create_exact(self, **_kwargs: object) -> str:
            effects.append("create")
            return "runtime-v2"

        def attach_exact(self, **_kwargs: object) -> object:
            effects.append("attach")
            return SimpleNamespace()

    backend = DockerMeasurementBackend(
        runtime=cast(Any, _Runtime()),
        started_runtime=SimpleNamespace(),
        measurements=SimpleNamespace(),
        frame_limits=MeasurementContainerFrameLimitsV2(maximum_frame_bytes=128_000),
        monotonic=lambda: 0.0,
    )

    with pytest.raises(DockerMeasurementBackendUnavailable, match="request, binding"):
        if effect_path == "create":
            backend.create(
                request=request,
                binding=binding,
                manifest=manifest,
                configuration=configuration,
                staged_input=SimpleNamespace(),
                deadline_monotonic=10.0,
            )
        else:
            backend.open_started(
                request=request,
                binding=binding,
                manifest=manifest,
                configuration=configuration,
                staged_input=SimpleNamespace(),
                runtime_id="runtime-v2",
                effective_limits=_effective_limits(configuration),
                runtime_parent=cast(Any, SimpleNamespace()),
                monitor_termination=lambda _reason: 0.0,
                is_cancelled=lambda: False,
                deadline_monotonic=10.0,
            )
    assert effects == []


@pytest.mark.parametrize("effect_path", ("create", "open_started"))
def test_v2_backend_rejects_oversigned_memory_before_runtime_effect(effect_path: str) -> None:
    """Caller-consistent fixed/effective limits cannot exceed signed ceilings."""

    manifest, request, _secondary_bytes = _request_with_secondary_bytes()
    configuration = _configuration(request, manifest)
    binding = new_measurement_attempt_binding(
        request=request,
        manifest=manifest,
        root=PrivateStagingRootV1(1, 2, 0o700, 1000, 1000),
        systemd_base_slice="ksi-measurement.slice",
        cpu_budget_counter=configuration.cpu_budget_counter,
        allocation_nonce="allocation-v2",
    )
    oversigned = dataclasses.replace(
        configuration,
        memory_bytes=manifest.body.hard_ceilings.max_memory_bytes * 2,
    )
    effects: list[str] = []

    class _Runtime:
        def create_exact(self, **_kwargs: object) -> str:
            effects.append("create")
            return "runtime-v2"

        def attach_exact(self, **_kwargs: object) -> object:
            effects.append("attach")
            return SimpleNamespace()

    backend = DockerMeasurementBackend(
        runtime=cast(Any, _Runtime()),
        started_runtime=SimpleNamespace(),
        measurements=SimpleNamespace(),
        frame_limits=MeasurementContainerFrameLimitsV2(maximum_frame_bytes=128_000),
        monotonic=lambda: 0.0,
    )

    with pytest.raises(DockerMeasurementBackendUnavailable, match="signed resource"):
        if effect_path == "create":
            backend.create(
                request=request,
                binding=binding,
                manifest=manifest,
                configuration=oversigned,
                staged_input=SimpleNamespace(),
                deadline_monotonic=10.0,
            )
        else:
            backend.open_started(
                request=request,
                binding=binding,
                manifest=manifest,
                configuration=oversigned,
                staged_input=SimpleNamespace(),
                runtime_id="runtime-v2",
                effective_limits=_effective_limits(oversigned),
                runtime_parent=cast(Any, SimpleNamespace()),
                monitor_termination=lambda _reason: 0.0,
                is_cancelled=lambda: False,
                deadline_monotonic=10.0,
            )
    assert effects == []


@pytest.mark.parametrize(("deadline", "clock"), [(10.0, 10.0), (True, 0.0)])
def test_v2_backend_rejects_an_expired_or_invalid_deadline_before_docker_create(
    deadline: object, clock: float
) -> None:
    """No Docker side effect is permitted after the shared request deadline elapsed."""

    manifest, request, _secondary_bytes = _request_with_secondary_bytes()
    configuration = _configuration(request, manifest)
    binding = new_measurement_attempt_binding(
        request=request,
        manifest=manifest,
        root=PrivateStagingRootV1(1, 2, 0o700, 1000, 1000),
        systemd_base_slice="ksi-measurement.slice",
        cpu_budget_counter=configuration.cpu_budget_counter,
        allocation_nonce="allocation-v2",
    )

    class _Runtime:
        def create_exact(self, **_kwargs: object) -> str:
            raise AssertionError("expired deadline must fail before Docker create")

    backend = DockerMeasurementBackend(
        runtime=cast(Any, _Runtime()),
        started_runtime=SimpleNamespace(),
        measurements=SimpleNamespace(),
        frame_limits=MeasurementContainerFrameLimitsV2(maximum_frame_bytes=128_000),
        monotonic=lambda: clock,
    )

    with pytest.raises(DockerMeasurementBackendUnavailable, match="deadline"):
        backend.create(
            request=request,
            binding=binding,
            manifest=manifest,
            configuration=configuration,
            staged_input=SimpleNamespace(),
            deadline_monotonic=deadline,  # type: ignore[arg-type]
        )


def test_v2_backend_does_not_expose_a_completion_deadline_override() -> None:
    """The started runtime retains its one request-wide deadline and authority callback."""

    manifest, request, secondary_bytes = _request_with_secondary_bytes()
    configuration = _configuration(request, manifest)
    binding = new_measurement_attempt_binding(
        request=request,
        manifest=manifest,
        root=PrivateStagingRootV1(1, 2, 0o700, 1000, 1000),
        systemd_base_slice="ksi-measurement.slice",
        cpu_budget_counter=configuration.cpu_budget_counter,
        allocation_nonce="allocation-v2",
    )

    class _Session:
        def send_stdin(self, _payload: bytes, *, deadline_monotonic: float) -> None:
            assert deadline_monotonic == 10.0

        def finish_stdin(self, *, deadline_monotonic: float) -> None:
            raise AssertionError("extended deadline must fail before stdin half-close")

        def read_frame(self, **_kwargs: object) -> object:
            raise AssertionError("extended deadline must fail before Docker reads")

        def close(self) -> None:
            pass

    class _Runtime:
        def attach_exact(self, _runtime_id: str, *, deadline_monotonic: float) -> _Session:
            assert deadline_monotonic == 10.0
            return _Session()

        def start_after_container_bound(self, **_kwargs: object) -> None:
            pass

    class _Measurement:
        def finalized_measurement(self) -> FixedRuntimeMeasurementV1:
            raise AssertionError("extended deadline must not finalize host evidence")

        def close(self) -> None:
            pass

    backend = DockerMeasurementBackend(
        runtime=cast(Any, _Runtime()),
        started_runtime=SimpleNamespace(verify_exact=lambda **_kwargs: None),
        measurements=SimpleNamespace(start=lambda **_kwargs: _Measurement()),
        frame_limits=MeasurementContainerFrameLimitsV2(maximum_frame_bytes=128_000),
        monotonic=lambda: 0.0,
    )
    active = backend.open_started(
        request=request,
        binding=binding,
        manifest=manifest,
        configuration=configuration,
        staged_input=SimpleNamespace(),
        runtime_id="runtime-v2",
        effective_limits=_effective_limits(configuration),
        runtime_parent=cast(Any, SimpleNamespace()),
        monitor_termination=lambda _reason: 0.0,
        is_cancelled=lambda: False,
        deadline_monotonic=10.0,
    )
    active.secondary_sink.write_chunk(
        secondary_bytes,
        deadline=ProtocolDeadline.at_expires_at(10.0, monotonic=lambda: 0.0),
        wait_is_current=lambda: True,
        heartbeat_interval_millis=50,
    )

    with pytest.raises(TypeError):
        active.complete(deadline_monotonic=11.0, is_cancelled=lambda: False)  # type: ignore[call-arg]
    active.close()


def test_v2_backend_closes_local_handles_when_secondary_is_not_exact() -> None:
    """A short or rehashed second input cannot leave an attached monitor running."""

    manifest, request, _secondary_bytes = _request_with_secondary_bytes()
    configuration = _configuration(request, manifest)
    binding = new_measurement_attempt_binding(
        request=request,
        manifest=manifest,
        root=PrivateStagingRootV1(1, 2, 0o700, 1000, 1000),
        systemd_base_slice="ksi-measurement.slice",
        cpu_budget_counter=configuration.cpu_budget_counter,
        allocation_nonce="allocation-v2",
    )
    closed: list[str] = []

    class _Session:
        def send_stdin(self, _payload: bytes, *, deadline_monotonic: float) -> None:
            assert deadline_monotonic == 10.0

        def close(self) -> None:
            closed.append("session")

    class _Runtime:
        def attach_exact(self, _runtime_id: str, *, deadline_monotonic: float) -> _Session:
            assert deadline_monotonic == 10.0
            return _Session()

        def start_after_container_bound(self, **_kwargs: object) -> None:
            pass

    class _Measurement:
        def finalized_measurement(self) -> FixedRuntimeMeasurementV1:
            raise AssertionError("inexact secondary input must not finalize host evidence")

        def close(self) -> None:
            closed.append("measurement")

    backend = DockerMeasurementBackend(
        runtime=cast(Any, _Runtime()),
        started_runtime=SimpleNamespace(verify_exact=lambda **_kwargs: None),
        measurements=SimpleNamespace(start=lambda **_kwargs: _Measurement()),
        frame_limits=MeasurementContainerFrameLimitsV2(maximum_frame_bytes=128_000),
        monotonic=lambda: 0.0,
    )
    active = backend.open_started(
        request=request,
        binding=binding,
        manifest=manifest,
        configuration=configuration,
        staged_input=SimpleNamespace(),
        runtime_id="runtime-v2",
        effective_limits=_effective_limits(configuration),
        runtime_parent=cast(Any, SimpleNamespace()),
        monitor_termination=lambda _reason: 0.0,
        is_cancelled=lambda: False,
        deadline_monotonic=10.0,
    )
    active.secondary_sink.write_chunk(
        b"short",
        deadline=ProtocolDeadline.at_expires_at(10.0, monotonic=lambda: 0.0),
        wait_is_current=lambda: True,
        heartbeat_interval_millis=50,
    )

    with pytest.raises(DockerMeasurementBackendUnavailable, match="secondary stream"):
        active.complete()
    assert closed == ["measurement", "session"]


def test_v2_backend_caps_all_container_controls_cumulatively() -> None:
    """Several individually valid controls cannot exceed the signed aggregate output cap."""

    limits = MeasurementContainerFrameLimitsV2(maximum_frame_bytes=128_000)
    first = encode_measurement_container_frame({"frame": "first"}, limits=limits)
    second = encode_measurement_container_frame({"frame": "second"}, limits=limits)

    class _Session:
        def __init__(self) -> None:
            self.frames = [(1, first), (1, second)]

        def read_frame(self, **_kwargs: object):  # type: ignore[no-untyped-def]
            return self.frames.pop(0) if self.frames else None

    reader = _AttachedMeasurementReaderV2(
        _Session(),  # type: ignore[arg-type]
        frame_limits=limits,
        maximum_control_bytes=len(first) + len(second) - 1,
    )
    assert reader.read_control(deadline_monotonic=10.0) == {"frame": "first"}
    with pytest.raises(DockerMeasurementBackendUnavailable, match="cumulative"):
        reader.read_control(deadline_monotonic=10.0)


def test_v2_backend_allows_eof_at_exact_control_cap_but_rejects_one_more_byte() -> None:
    """The exact cap is inclusive only when the next attach read is clean EOF."""

    limits = MeasurementContainerFrameLimitsV2(maximum_frame_bytes=128_000)
    control = encode_measurement_container_frame({"frame": "control"}, limits=limits)

    class _Session:
        def __init__(self, trailing: bytes | None) -> None:
            self.frames: list[tuple[int, bytes]] = [(1, control)]
            if trailing is not None:
                self.frames.append((1, trailing))

        def read_frame(self, **_kwargs: object):  # type: ignore[no-untyped-def]
            return self.frames.pop(0) if self.frames else None

    exact = _AttachedMeasurementReaderV2(
        _Session(None),  # type: ignore[arg-type]
        frame_limits=limits,
        maximum_control_bytes=len(control),
    )
    assert exact.read_control(deadline_monotonic=10.0) == {"frame": "control"}
    exact.require_eof(deadline_monotonic=10.0)

    trailing = _AttachedMeasurementReaderV2(
        _Session(b"x"),  # type: ignore[arg-type]
        frame_limits=limits,
        maximum_control_bytes=len(control),
    )
    assert trailing.read_control(deadline_monotonic=10.0) == {"frame": "control"}
    with pytest.raises(DockerMeasurementBackendUnavailable, match="cumulative"):
        trailing.require_eof(deadline_monotonic=10.0)


def test_v2_backend_requires_type_exact_control_echoes() -> None:
    """JSON booleans cannot compare equal to size integers at the inner authority boundary."""

    with pytest.raises(DockerMeasurementBackendUnavailable, match="echo"):
        _require_exact_control({"actualSizeBytes": True}, {"actualSizeBytes": 1})


@pytest.mark.parametrize(("status_code", "is_accepted"), [(0, True), (0.0, False), (True, False)])
def test_v2_backend_returns_only_a_validated_typed_failure_after_host_proof(
    status_code: object, is_accepted: bool
) -> None:
    """A container's typed failure has no metrics but still needs clean EOF, wait, and CPU proof."""

    manifest, request, secondary_bytes = _request_with_secondary_bytes()
    limits = MeasurementContainerFrameLimitsV2(maximum_frame_bytes=128_000)
    prepare = build_prepare_frame_v2(request=request, manifest=manifest)
    events: list[str] = []

    class _Session:
        def send_stdin(self, payload: bytes, *, deadline_monotonic: float) -> None:
            assert deadline_monotonic == 10.0
            events.append("secondary" if payload == secondary_bytes else "execute")

        def finish_stdin(self, *, deadline_monotonic: float) -> None:
            assert deadline_monotonic == 10.0
            events.append("finish-stdin")

        def close(self) -> None:
            events.append("session-close")

    class _Reader:
        def __init__(self) -> None:
            self.frames = [
                build_secondary_staged_frame(
                    prepare=prepare,
                    actual_size_bytes=len(secondary_bytes),
                    actual_sha256="sha256:" + sha256(secondary_bytes).hexdigest(),
                ),
                build_primary_mount_verified_frame(
                    prepare=prepare,
                    actual_size_bytes=request.inputs[0].observed_size_bytes,
                    actual_sha256=request.inputs[0].observed_sha256,
                ),
                build_failed_frame_v2(prepare=prepare, reason="RESOURCE_LIMIT_EXCEEDED"),
            ]

        def read_control(self, *, deadline_monotonic: float) -> dict[str, object]:
            assert deadline_monotonic == 10.0
            return self.frames.pop(0)

        def require_eof(self, *, deadline_monotonic: float) -> None:
            assert deadline_monotonic == 10.0
            events.append("eof")

    class _Measurement:
        def finalized_measurement(self) -> FixedRuntimeMeasurementV1:
            events.append("final-proof")
            return _measurement("runtime-v2")

        def close(self) -> None:
            events.append("measurement-close")

    class _Runtime:
        def wait_exact(self, runtime_id: str, *, deadline_monotonic: float) -> dict[str, object]:
            assert runtime_id == "runtime-v2" and deadline_monotonic == 10.0
            events.append("wait")
            return {"StatusCode": status_code}

    session = _Session()
    active = DockerMeasurementActiveV2(
        session=session,  # type: ignore[arg-type]
        reader=_Reader(),  # type: ignore[arg-type]
        measurement=_Measurement(),
        secondary_sink=_SecondarySinkV2(
            session,  # type: ignore[arg-type]
            expected_size_bytes=len(secondary_bytes),
            expected_sha256="sha256:" + sha256(secondary_bytes).hexdigest(),
            deadline_monotonic=10.0,
            is_cancelled=lambda: False,
        ),
        prepare=prepare,
        request=request,
        runtime=_Runtime(),  # type: ignore[arg-type]
        runtime_id="runtime-v2",
        frame_limits=limits,
        deadline_monotonic=10.0,
        is_cancelled=lambda: False,
    )
    active.secondary_sink.write_chunk(
        secondary_bytes,
        deadline=ProtocolDeadline.at_expires_at(10.0, monotonic=lambda: 0.0),
        wait_is_current=lambda: True,
        heartbeat_interval_millis=50,
    )
    if is_accepted:
        completed = active.complete()
        active.close()
        assert completed.terminal == build_failed_frame_v2(
            prepare=prepare, reason="RESOURCE_LIMIT_EXCEEDED"
        )
        assert "aggregate" not in completed.terminal
        assert events == [
            "secondary",
            "execute",
            "finish-stdin",
            "eof",
            "wait",
            "final-proof",
            "session-close",
        ]
    else:
        with pytest.raises(DockerMeasurementBackendUnavailable, match="exited"):
            active.complete()
        assert "final-proof" not in events


@pytest.mark.parametrize(
    ("failure_after_secondary", "reason"),
    (
        (False, "SECONDARY_SPOOL_DIGEST_MISMATCH"),
        (True, "PRIMARY_DSM_REJECTED"),
    ),
)
def test_v2_backend_finalizes_actual_preexecute_failure_transcript(
    failure_after_secondary: bool, reason: str
) -> None:
    """A real V2 framed failure before EXECUTE still requires EOF, wait, and CPU proof."""

    manifest, request, secondary_bytes = _request_with_secondary_bytes()
    limits = MeasurementContainerFrameLimitsV2(maximum_frame_bytes=128_000)
    prepare = build_prepare_frame_v2(request=request, manifest=manifest)
    events: list[str] = []
    secondary_staged = build_secondary_staged_frame(
        prepare=prepare,
        actual_size_bytes=len(secondary_bytes),
        actual_sha256="sha256:" + sha256(secondary_bytes).hexdigest(),
    )
    failure = build_failed_frame_v2(prepare=prepare, reason=reason)

    class _Session:
        def __init__(self) -> None:
            controls = [failure]
            if failure_after_secondary:
                controls.insert(0, secondary_staged)
            self.frames = [
                (1, encode_measurement_container_frame(control, limits=limits))
                for control in controls
            ]

        def send_stdin(self, payload: bytes, *, deadline_monotonic: float) -> None:
            assert deadline_monotonic == 10.0
            assert payload == secondary_bytes
            events.append("secondary")

        def finish_stdin(self, **_kwargs: object) -> None:
            raise AssertionError("a pre-EXECUTE failure must not half-close or execute")

        def read_frame(self, **_kwargs: object):  # type: ignore[no-untyped-def]
            if self.frames:
                return self.frames.pop(0)
            events.append("eof")
            return None

        def close(self) -> None:
            events.append("session-close")

    class _Measurement:
        def finalized_measurement(self) -> FixedRuntimeMeasurementV1:
            events.append("final-proof")
            return _measurement("runtime-v2")

        def close(self) -> None:
            events.append("measurement-close")

    class _Runtime:
        def wait_exact(self, runtime_id: str, *, deadline_monotonic: float) -> dict[str, int]:
            assert runtime_id == "runtime-v2" and deadline_monotonic == 10.0
            events.append("wait")
            return {"StatusCode": 0}

    session = _Session()
    sink = _SecondarySinkV2(
        session,
        expected_size_bytes=len(secondary_bytes),
        expected_sha256="sha256:" + sha256(secondary_bytes).hexdigest(),
        deadline_monotonic=10.0,
        is_cancelled=lambda: False,
    )
    active = DockerMeasurementActiveV2(
        session=session,
        reader=_AttachedMeasurementReaderV2(
            session,
            frame_limits=limits,
            maximum_control_bytes=128_000,
        ),
        measurement=_Measurement(),
        secondary_sink=sink,
        prepare=prepare,
        request=request,
        runtime=_Runtime(),  # type: ignore[arg-type]
        runtime_id="runtime-v2",
        frame_limits=limits,
        deadline_monotonic=10.0,
        is_cancelled=lambda: False,
    )
    sink.write_chunk(
        secondary_bytes,
        deadline=ProtocolDeadline.at_expires_at(10.0, monotonic=lambda: 0.0),
        wait_is_current=lambda: True,
        heartbeat_interval_millis=50,
    )

    completed = active.complete()
    active.close()

    assert completed.terminal == failure
    assert "aggregate" not in completed.terminal
    assert events == ["secondary", "eof", "wait", "final-proof", "session-close"]
