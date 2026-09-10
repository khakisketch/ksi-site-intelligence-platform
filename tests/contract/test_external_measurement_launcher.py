"""Public V2 launcher admission and shared recovery fail closed before bytes."""

import os
import socket

import pytest
from ksi_processing_controller.external_attempt_lifecycle import InspectorSandboxUnavailable
from ksi_processing_controller.external_measurement_launcher import ExternalMeasurementLauncher
from test_external_measurement_protocol import limits


class Recovery:
    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail

    def recover_startup(self):
        self.calls += 1
        if self.fail:
            raise RuntimeError("private recovery detail")


def launcher(recovery, uid=None, **overrides):
    args = dict(
        required_worker_uid=os.getuid() if uid is None else uid,
        catalog=None,
        verifier=None,
        accounting=None,
        input_staging=None,
        reader_mapping=None,
        attempt_journal=None,
        attempt_recovery=recovery,
        runtime_parent=None,
        runtime_cleanup=None,
        backend=None,
        protocol_limits=limits(),
        systemd_base_slice="ksi-measurement.slice",
    )
    args.update(overrides)
    return ExternalMeasurementLauncher(**args)


def test_failed_startup_recovery_never_constructs_admitting_launcher():
    recovery = Recovery(True)
    with pytest.raises(InspectorSandboxUnavailable):
        launcher(recovery)
    assert recovery.calls == 1


def test_wrong_peer_closes_before_reading_header_or_catalog():
    recovery = Recovery()
    value = launcher(recovery, uid=os.getuid() + 1)
    client, server = socket.socketpair()
    try:
        value.handle_connection(server)
        assert client.recv(1) == b""
        assert recovery.calls == 1
    finally:
        client.close()
        server.close()


def test_malformed_header_closes_without_runtime_effects():
    value = launcher(Recovery())
    client, server = socket.socketpair()
    try:
        client.sendall(b"\0\0\0\2{}")
        client.shutdown(socket.SHUT_WR)
        value.handle_connection(server)
        assert client.recv(1) == b""
    finally:
        client.close()
        server.close()


@pytest.mark.parametrize(
    "failure,real_staging,backend_kind",
    [
        (value, False, "port")
        for value in (
            None,
            "parent",
            "create",
            "open",
            "secondary",
            "complete",
            "revoked",
            "remove",
            "primary_hash",
            "revoked_parent",
            "revoked_create",
        )
    ]
    + [
        (None, True, "port"),
        (None, True, "docker"),
        (None, True, "docker_completed"),
        ("revoked_before_execute", True, "docker_completed"),
        ("revoked_secondary", True, "docker_completed"),
        ("revoked_race", True, "docker_completed"),
    ],
)
def test_full_v2_sequence_uses_one_host_allocation_and_publishes_after_durable_cleaned(
    tmp_path, failure, real_staging, backend_kind
):
    import hashlib
    import struct
    from types import SimpleNamespace

    from ksi_processing_controller.external_inspector_runtime import (
        FixedRuntimeMeasurementV1,
        RuntimeControlDispositionV1,
    )
    from ksi_processing_controller.external_measurement_attempts import MeasurementAttemptJournalV2
    from ksi_processing_controller.external_measurement_container_protocol import (
        build_failed_frame_v2,
        build_prepare_frame_v2,
    )
    from ksi_processing_controller.external_measurement_result import decode_measurement_result
    from test_external_inspector_launcher import (
        _Accounting,
        _InputStaging,
        _ReaderMapping,
        _RuntimeCleanup,
        _RuntimeParent,
    )
    from test_external_measurement_attempt_journal import parent_receipt
    from test_external_measurement_catalog_admission import Catalog, Verifier
    from test_external_measurement_protocol import measurement_manifest_request

    primary = b"primary opaque sealed bytes"
    secondary = b"secondary opaque sealed bytes"
    manifest, request = measurement_manifest_request()
    inputs = tuple(
        value.model_copy(
            update={
                "observed_sha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
                "observed_size_bytes": len(payload),
            }
        )
        for value, payload in zip(request.inputs, (primary, secondary), strict=True)
    )
    volume = request.volume_request.model_copy(
        update={
            "baseline": request.volume_request.baseline.model_copy(
                update={
                    "observed_sha256": inputs[0].observed_sha256,
                    "observed_size_bytes": len(primary),
                }
            ),
            "current": request.volume_request.current.model_copy(
                update={
                    "observed_sha256": inputs[1].observed_sha256,
                    "observed_size_bytes": len(secondary),
                }
            ),
            "request_digest": None,
        }
    ).sealed()
    request = request.model_copy(
        update={"inputs": inputs, "volume_request": volume, "canonical_input_digest": None}
    ).sealed()
    journal = MeasurementAttemptJournalV2(tmp_path / "attempts.jsonl")
    staging = _InputStaging()
    if real_staging:
        from ksi_processing_controller.external_inspector_access import LibaclNamedReaderAcl
        from ksi_processing_controller.external_inspector_staging import FileSystemInputStaging

        concrete = FileSystemInputStaging(
            private_root=tmp_path / "private",
            reader_mapping=_ReaderMapping(),
            acl=LibaclNamedReaderAcl(),
        )

        class TrackedStaging(_InputStaging):
            def private_root_identity(self):
                return concrete.private_root_identity()

            def begin_registered(self, **kwargs):
                mutable, receipt = concrete.begin_registered(**kwargs)
                self.mutable.append(mutable)
                seal = mutable.seal_for_reader

                def tracked_seal(**values):
                    sealed = seal(**values)
                    self.sealed.append(sealed)
                    return sealed

                mutable.seal_for_reader = tracked_seal
                return mutable, receipt

            def finalize_registered_cleanup(self, **kwargs):
                concrete.finalize_registered_cleanup(**kwargs)
                self.finalized.append((kwargs["plan"], kwargs["receipt"]))

        staging = TrackedStaging()
    accounting = _Accounting()
    events = []
    import threading

    class ConcurrentCatalog(Catalog):
        armed = False
        monitor_callback = None

        def is_revoked(self, selected_manifest):
            if threading.current_thread().name == "fixture-authority-monitor":
                return True
            if self.armed:
                self.armed = False

                def observe_loss():
                    assert self.monitor_callback() is True
                    events.append("monitor-cancelled")

                thread = threading.Thread(target=observe_loss, name="fixture-authority-monitor")
                thread.start()
                thread.join(1)
                assert not thread.is_alive()
            return super().is_revoked(selected_manifest)

    catalog = ConcurrentCatalog(manifest)

    class Parent(_RuntimeParent):
        def bind_before_create(self, *, binding, configuration):
            assert journal.phase_of(binding.attempt_nonce).value == "RUNTIME_PARENT_CREATING"
            if failure == "parent":
                raise RuntimeError("unknown parent create")
            if failure == "revoked_parent":
                catalog.revoked = True
            return parent_receipt(binding)

    class Sink:
        def __init__(self):
            self.value = bytearray()

        def write_chunk(self, chunk, *, deadline, wait_is_current, heartbeat_interval_millis):
            deadline.remaining()
            assert wait_is_current()
            if failure == "secondary":
                raise RuntimeError("secondary write failed")
            self.value.extend(chunk)
            events.append("secondary")

    class Backend:
        def create(self, **kwargs):
            assert journal.phase_of(request.attempt_nonce).value == "CONTAINER_CREATING"
            assert len(staging.mutable) == 1
            if real_staging:
                bind = kwargs["staged_input"].prepare_read_only_bind(
                    deadline_monotonic=kwargs["deadline_monotonic"]
                )
                assert (
                    bind.source.verify_readback(
                        deadline_monotonic=kwargs["deadline_monotonic"]
                    ).sha256
                    == request.inputs[0].observed_sha256
                )
            else:
                assert staging.sealed[0].payload == primary
            if failure == "create":
                raise RuntimeError("unknown create")
            events.append("create")
            if failure == "revoked_create":
                catalog.revoked = True
            return SimpleNamespace(runtime_id="a" * 64)

        def open_started(self, **kwargs):
            assert journal.phase_of(request.attempt_nonce).value == "CONTAINER_BOUND"
            if failure == "open":
                raise RuntimeError("start failed")
            events.append("start")
            configuration = kwargs["configuration"]

            class Active:
                secondary_sink = Sink()

                def complete(self, **ignored):
                    assert bytes(self.secondary_sink.value) == secondary
                    if failure == "complete":
                        raise RuntimeError("terminal failed")
                    if failure == "revoked":
                        catalog.revoked = True
                    events.append("complete")
                    return SimpleNamespace(
                        terminal=build_failed_frame_v2(
                            prepare=build_prepare_frame_v2(request=request, manifest=manifest),
                            reason="INSUFFICIENT_COMMON_VALID_COVERAGE",
                        ),
                        runtime_measurement=FixedRuntimeMeasurementV1(
                            runtime_id="a" * 64,
                            counter_unit=configuration.cpu_counter_unit,
                            baseline_counter=0,
                            final_counter=1,
                            consumed_counter=1,
                            budget_counter=configuration.cpu_budget_counter,
                            threshold_exceeded=False,
                            disposition=RuntimeControlDispositionV1.COMPLETED,
                            kill_latency_seconds=None,
                        ),
                    )

                def close(self):
                    events.append("close")

            return Active()

    runtime = _RuntimeCleanup(removed=failure != "remove")
    value = launcher(
        Recovery(),
        catalog=catalog,
        verifier=Verifier(),
        accounting=accounting,
        input_staging=staging,
        reader_mapping=_ReaderMapping(),
        attempt_journal=journal,
        runtime_parent=Parent(),
        runtime_cleanup=runtime,
        backend=Backend()
        if backend_kind == "port"
        else _concrete_backend(
            request,
            manifest,
            journal,
            events,
            catalog=catalog,
            failure=failure,
            completed=backend_kind == "docker_completed",
        ),
    )
    client, server = socket.socketpair()
    try:
        header = request.canonical_bytes()
        client.sendall(
            struct.pack(">I", len(header))
            + header
            + (b"x" * len(primary) if failure == "primary_hash" else primary)
            + secondary
        )
        client.shutdown(socket.SHUT_WR)
        value.handle_connection(server)
        data = b""
        try:
            while chunk := client.recv(65536):
                data += chunk
        except ConnectionResetError:
            assert failure is not None
        if failure is not None:
            assert not data
            if failure in {"revoked_before_execute", "revoked_secondary", "revoked_race"}:
                assert "execute" not in events and "half-close" not in events
            if failure == "revoked_race":
                assert "monitor-cancelled" in events
            if failure in {"revoked_parent", "revoked_create"}:
                assert "start" not in events
            assert len(staging.mutable) == 1
            retained = failure in {"parent", "create", "remove"}
            if retained:
                assert not value._available()
                assert staging.sealed[0].relinquished and not staging.sealed[0].aborted
                assert not accounting.reservations[0].released
                assert journal.phase_of(request.attempt_nonce).value == "CLEANUP_FAILED"
            else:
                assert journal.phase_of(request.attempt_nonce).value == "CLEANED"
                assert accounting.reservations[0].released
            return
        assert data, events
        assert journal.phase_of(request.attempt_nonce).value == "CLEANED"
        size = struct.unpack(">I", data[:4])[0]
        assert len(data) == size + 4
        decoded = decode_measurement_result(
            data[4:], request=request, manifest=manifest, limits=limits()
        )
        if backend_kind == "docker_completed":
            assert decoded.status == "COMPLETED"
            assert decoded.aggregate.metrics.cut_m3 == 1.0
            assert decoded.aggregate.metrics.fill_m3 == 5.0
            assert decoded.aggregate.metrics.net_m3 == 4.0
            assert "execute" in events and "half-close" in events
        else:
            assert decoded.status == "FAILED" and decoded.aggregate is None
        assert events[:2] == ["create", "start"] and events[-1] == "close"
        assert len(staging.mutable) == 1 and len(staging.finalized) == 1
        if real_staging:
            assert not tuple((tmp_path / "private").iterdir())
        else:
            assert staging.sealed[0].aborted
        assert accounting.calls == [(1, 1, len(primary))] and accounting.reservations[0].released
        assert runtime.runtime_ids == ["a" * 64]
    finally:
        client.close()
        server.close()
        journal.close()


def _concrete_backend(request, manifest, journal, events, *, catalog, failure, completed):
    """Real backend grammar, synthetic Engine/scope/counters; no container claim."""
    from collections import deque

    from ksi_processing_controller.external_inspector_runtime import (
        FixedRuntimeMeasurementV1,
        RuntimeControlDispositionV1,
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
        DockerMeasurementBackend,
    )

    caps = MeasurementContainerFrameLimitsV2(maximum_frame_bytes=128000)
    prepare = build_prepare_frame_v2(request=request, manifest=manifest)
    terminal = build_failed_frame_v2(prepare=prepare, reason="PRIMARY_DSM_REJECTED")
    if completed:
        terminal = build_completed_frame_v2(
            prepare=prepare,
            input_bindings=[item.model_dump(by_alias=True, mode="json") for item in request.inputs],
            aggregate={
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
            },
        )
    controls = [
        build_secondary_staged_frame(
            prepare=prepare,
            actual_size_bytes=request.inputs[1].observed_size_bytes,
            actual_sha256=request.inputs[1].observed_sha256,
        )
    ]
    if completed:
        controls.append(
            build_primary_mount_verified_frame(
                prepare=prepare,
                actual_size_bytes=request.inputs[0].observed_size_bytes,
                actual_sha256=request.inputs[0].observed_sha256,
            )
        )
    controls.append(terminal)
    frames = deque(encode_measurement_container_frame(frame, limits=caps) for frame in controls)

    class Session:
        def __init__(self):
            self.writes = []
            self.finished = False

        def send_stdin(self, payload, *, deadline_monotonic):
            assert not self.finished
            self.writes.append(payload)
            if len(self.writes) > 2:
                assert "cpu-monitor" in events
            if len(self.writes) > 3:
                events.append("execute")
            elif len(self.writes) == 3 and failure == "revoked_secondary":
                catalog.revoked = True

        def finish_stdin(self, *, deadline_monotonic):
            self.finished = True
            events.append("half-close")

        def read_frame(self, **kwargs):
            assert len(self.writes) >= 3
            assert decode_measurement_container_frame(self.writes[0], limits=caps) == prepare
            assert (
                decode_measurement_container_frame(self.writes[1], limits=caps)["frame"]
                == "SECONDARY_BEGIN"
            )
            if frames:
                frame = frames.popleft()
                if (
                    decode_measurement_container_frame(frame, limits=caps)["frame"]
                    == "PRIMARY_MOUNT_VERIFIED"
                    and failure == "revoked_before_execute"
                ):
                    catalog.revoked = True
                if (
                    decode_measurement_container_frame(frame, limits=caps)["frame"]
                    == "PRIMARY_MOUNT_VERIFIED"
                    and failure == "revoked_race"
                ):
                    catalog.armed = True
                return 1, frame
            # An early typed failure exits before EXECUTE and stdin half-close.
            assert self.finished is completed
            return None

        def close(self):
            events.append("close")

    session = Session()

    class Runtime:
        def create_exact(self, **kwargs):
            assert journal.phase_of(request.attempt_nonce).value == "CONTAINER_CREATING"
            events.append("create")
            return "a" * 64

        def attach_exact(self, runtime_id, *, deadline_monotonic):
            assert journal.phase_of(request.attempt_nonce).value == "CONTAINER_BOUND"
            return session

        def start_after_container_bound(self, **kwargs):
            assert len(session.writes) == 2
            events.append("start")

        def wait_exact(self, runtime_id, *, deadline_monotonic):
            assert session.finished is completed
            return {"StatusCode": 0}

    class Scope:
        def verify_exact(self, **kwargs):
            assert events[-1] == "start"
            events.append("scope")

    class Measurements:
        def start(self, **kwargs):
            assert events[-1] == "scope"
            events.append("cpu-monitor")
            catalog.monitor_callback = kwargs["is_cancelled"]
            configuration = kwargs["configuration"]

            class Active:
                def finalized_measurement(self):
                    return FixedRuntimeMeasurementV1(
                        runtime_id="a" * 64,
                        counter_unit=configuration.cpu_counter_unit,
                        baseline_counter=0,
                        final_counter=1,
                        consumed_counter=1,
                        budget_counter=configuration.cpu_budget_counter,
                        threshold_exceeded=False,
                        disposition=RuntimeControlDispositionV1.COMPLETED,
                        kill_latency_seconds=None,
                    )

                def close(self):
                    pass

            return Active()

    return DockerMeasurementBackend(
        runtime=Runtime(), started_runtime=Scope(), measurements=Measurements(), frame_limits=caps
    )
