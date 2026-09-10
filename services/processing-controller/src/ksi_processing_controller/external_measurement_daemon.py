"""Fail-closed V2 systemd-activated measurement daemon assembly.

The concrete V2 Docker backend is deliberately imported only after strict
operator preflight and listener proof.  This module never provisions a user,
listener, rootless daemon, OCI image, cgroup, or systemd unit.
"""

from __future__ import annotations

import importlib
import sys
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from ksi_event_contracts.inspector_execution_manifest import InspectorExecutionManifestVerifier

from ksi_processing_controller.external_inspector_access import (
    LibaclNamedReaderAcl,
    ProcUserNamespaceReaderMapping,
    UserNamespaceMappingConfigV1,
)
from ksi_processing_controller.external_inspector_catalog import (
    Ed25519InspectorManifestVerifier,
    FileInspectorCatalogConfigV1,
    FileInspectorManifestCatalog,
    InspectorTrustRootV1,
)
from ksi_processing_controller.external_inspector_daemon import (
    ActivatedListenerReceipt,
    InspectorDaemonUnavailable,
    SystemdActivatedListenerConfigV1,
    verify_systemd_activated_listener,
)
from ksi_processing_controller.external_inspector_docker import (
    CgroupV2RootConfigV1,
    CgroupV2RootV1,
    DockerCgroupMeasurementConfigV1,
    DockerCgroupRuntimeMeasurement,
    DockerEngineClientV1,
    DockerExactRuntimeRegistry,
    DockerStartedScopeVerifier,
    FileLocalOciPairResolver,
    FileOciPairResolverConfigV1,
    ProcCgroupReader,
    RootlessDockerHostProofPort,
    RootlessDockerRuntimeAdapter,
    RootlessDockerSocketConfigV1,
    UnixSocketDockerEngineWire,
)
from ksi_processing_controller.external_inspector_launcher import InspectorAdmissionAccountingPort
from ksi_processing_controller.external_inspector_protocol import ProtocolLimitsV1
from ksi_processing_controller.external_inspector_staging import (
    FileSystemInputStaging,
    ReaderMappingPort,
    RegisteredInputStagingPort,
)
from ksi_processing_controller.external_inspector_systemd import (
    LibsystemdUserManager,
    SystemdTransientSliceConfigV1,
    UserSystemdBusConfigV1,
)
from ksi_processing_controller.external_measurement_attempts import (
    MeasurementAttemptJournalV2,
    MeasurementAttemptRecoveryV2,
)
from ksi_processing_controller.external_measurement_container_protocol import (
    MeasurementContainerFrameLimitsV2,
)
from ksi_processing_controller.external_measurement_launcher import ExternalMeasurementLauncher
from ksi_processing_controller.external_measurement_systemd import (
    MeasurementSystemdTransientSliceController,
)

if TYPE_CHECKING:
    from ksi_processing_controller.external_measurement_docker_backend import (
        DockerMeasurementBackend,
    )

_FIXED_BASE_SLICE = "ksi-measurement.slice"


class MeasurementDaemonUnavailable(RuntimeError):
    """A required V2 preflight, activated listener, or runtime graph fact is unavailable."""


class _OperatorConfiguredHostProofPort(RootlessDockerHostProofPort, Protocol):
    def verify_startup(self) -> None: ...


class _ProductionMeasurementDaemonBuilderPort(Protocol):
    def __call__(
        self,
        *,
        config: ProductionMeasurementConfigV2,
        host_proof: RootlessDockerHostProofPort,
        environment: dict[str, str] | None = None,
        activated_listener: ActivatedListenerReceipt | None = None,
    ) -> ExternalMeasurementSystemdDaemon: ...


@dataclass(frozen=True, slots=True)
class MeasurementAdmissionCapacityV2:
    """The V2 daemon reserves one request, one run, and only primary host staging."""

    maximum_request_units: int
    maximum_concurrency_units: int
    maximum_primary_staging_bytes: int

    def __post_init__(self) -> None:
        if any(
            type(value) is not int or value <= 0
            for value in (
                self.maximum_request_units,
                self.maximum_concurrency_units,
                self.maximum_primary_staging_bytes,
            )
        ):
            raise ValueError("all V2 measurement admission capacities are required")
        if self.maximum_concurrency_units != 1:
            raise ValueError("the synchronous V2 measurement daemon permits exactly one run")


@dataclass(frozen=True, slots=True)
class ProductionMeasurementConfigV2:
    """All fixed V2 local facts; there is no secondary/output host allocation."""

    required_worker_uid: int
    listener: SystemdActivatedListenerConfigV1
    catalog: FileInspectorCatalogConfigV1
    trust_root: InspectorTrustRootV1
    primary_root: Path
    reader_mapping: UserNamespaceMappingConfigV1
    journal_path: Path
    docker_socket: RootlessDockerSocketConfigV1
    oci_pairs: FileOciPairResolverConfigV1
    cgroup_root: CgroupV2RootConfigV1
    systemd_bus: UserSystemdBusConfigV1
    systemd_base_slice: str
    recovery_timeout_millis: int
    admission_capacity: MeasurementAdmissionCapacityV2
    protocol_limits: ProtocolLimitsV1
    frame_limits: MeasurementContainerFrameLimitsV2
    cgroup_measurement: DockerCgroupMeasurementConfigV1

    def __post_init__(self) -> None:
        if type(self.required_worker_uid) is not int or self.required_worker_uid < 0:
            raise ValueError("measurement worker UID is invalid")
        if not self.primary_root.is_absolute() or not self.journal_path.is_absolute():
            raise ValueError("private primary root and durable journal are required")
        if (
            type(self.recovery_timeout_millis) is not int
            or self.recovery_timeout_millis <= 0
            or self.systemd_base_slice != _FIXED_BASE_SLICE
            or self.admission_capacity.maximum_primary_staging_bytes
            > self.protocol_limits.max_input_bytes
            or self.frame_limits.maximum_frame_bytes > self.protocol_limits.max_output_bytes
        ):
            raise ValueError("fixed V2 measurement runtime limits are invalid")


class _MeasurementAdmissionReservation:
    def __init__(
        self,
        owner: _MeasurementAdmissionAccounting,
        request_units: int,
        concurrency_units: int,
        primary_staging_bytes: int,
    ) -> None:
        self._owner = owner
        self._values = (request_units, concurrency_units, primary_staging_bytes)
        self._released = False

    def release(self) -> None:
        if not self._released:
            self._released = True
            self._owner._release(*self._values)


class _MeasurementAdmissionAccounting:
    """Concrete V2 accounting names and bounds only primary host staging."""

    def __init__(self, capacity: MeasurementAdmissionCapacityV2) -> None:
        self._capacity = capacity
        self._lock = threading.Lock()
        self._used = (0, 0, 0)

    def reserve(
        self,
        *,
        request_units: int,
        concurrency_units: int,
        spool_bytes: int,
        deadline_monotonic: float,
    ) -> _MeasurementAdmissionReservation | None:
        del deadline_monotonic
        values = (request_units, concurrency_units, spool_bytes)
        if any(type(value) is not int or value < 0 for value in values) or values == (0, 0, 0):
            return None
        with self._lock:
            candidate = (
                self._used[0] + request_units,
                self._used[1] + concurrency_units,
                self._used[2] + spool_bytes,
            )
            limits = (
                self._capacity.maximum_request_units,
                self._capacity.maximum_concurrency_units,
                self._capacity.maximum_primary_staging_bytes,
            )
            if any(value > limit for value, limit in zip(candidate, limits, strict=True)):
                return None
            self._used = candidate
        return _MeasurementAdmissionReservation(self, *values)

    def _release(self, request_units: int, concurrency_units: int, spool_bytes: int) -> None:
        with self._lock:
            candidate = (
                self._used[0] - request_units,
                self._used[1] - concurrency_units,
                self._used[2] - spool_bytes,
            )
            if any(value < 0 for value in candidate):
                raise MeasurementDaemonUnavailable("measurement admission accounting underflow")
            self._used = candidate


@dataclass(frozen=True, slots=True)
class ExternalMeasurementAssemblyV2:
    required_worker_uid: int
    catalog: FileInspectorManifestCatalog
    verifier: InspectorExecutionManifestVerifier
    accounting: InspectorAdmissionAccountingPort
    input_staging: RegisteredInputStagingPort
    reader_mapping: ReaderMappingPort
    attempt_journal: MeasurementAttemptJournalV2
    attempt_recovery: MeasurementAttemptRecoveryV2
    runtime_parent: MeasurementSystemdTransientSliceController
    runtime_cleanup: DockerExactRuntimeRegistry
    backend: DockerMeasurementBackend
    protocol_limits: ProtocolLimitsV1
    systemd_base_slice: str


@dataclass(frozen=True, slots=True)
class MeasurementDaemonBoundaryPorts:
    """Explicit constructed-host boundaries for graph tests and production wiring."""

    cgroups: Any
    systemd_manager: Any
    engine_client: Any
    proc_cgroups: Any
    journal_factory: Callable[[Path], MeasurementAttemptJournalV2] = MeasurementAttemptJournalV2


def _close_owned_resources(resources: tuple[object, ...]) -> None:
    """Best-effort cleanup must not replace the graph failure being propagated."""

    for resource in reversed(resources):
        close = getattr(resource, "close", None)
        if callable(close):
            with suppress(BaseException):
                close()


def _production_boundary_ports(
    config: ProductionMeasurementConfigV2,
    host_proof: RootlessDockerHostProofPort,
) -> MeasurementDaemonBoundaryPorts:
    cgroups: CgroupV2RootV1 | None = None
    manager: LibsystemdUserManager | None = None
    try:
        cgroups = CgroupV2RootV1(config.cgroup_root)
        manager = LibsystemdUserManager(config.systemd_bus)
        wire = UnixSocketDockerEngineWire(config.docker_socket, peer_verifier=host_proof)
        client = DockerEngineClientV1(wire)
        return MeasurementDaemonBoundaryPorts(
            cgroups=cgroups,
            systemd_manager=manager,
            engine_client=client,
            proc_cgroups=ProcCgroupReader(maximum_bytes=config.cgroup_root.maximum_control_bytes),
        )
    except BaseException:
        _close_owned_resources((cgroups, manager))
        raise


def build_production_measurement_daemon(
    *,
    config: ProductionMeasurementConfigV2,
    host_proof: RootlessDockerHostProofPort,
    environment: dict[str, str] | None = None,
    activated_listener: ActivatedListenerReceipt | None = None,
    boundary_ports: MeasurementDaemonBoundaryPorts | None = None,
) -> ExternalMeasurementSystemdDaemon:
    """Construct only the fixed V2 graph after all strict preflight succeeds."""

    if host_proof is None:
        raise MeasurementDaemonUnavailable("rootless Docker host proof is unavailable")
    try:
        backend_module = importlib.import_module(
            "ksi_processing_controller.external_measurement_docker_backend"
        )
        backend_type = backend_module.DockerMeasurementBackend
    except (ImportError, AttributeError) as exc:
        raise MeasurementDaemonUnavailable("V2 measurement backend is unavailable") from exc

    journal: MeasurementAttemptJournalV2 | None = None
    daemon_transferred = False
    listener_transferred = False
    owned_boundary_resources: tuple[object, ...] = ()
    try:
        if boundary_ports is None:
            boundary_ports = _production_boundary_ports(config, host_proof)
            owned_boundary_resources = (
                boundary_ports.cgroups,
                boundary_ports.systemd_manager,
            )
        mapping = ProcUserNamespaceReaderMapping(config.reader_mapping)
        input_staging = FileSystemInputStaging(
            private_root=config.primary_root,
            reader_mapping=mapping,
            acl=LibaclNamedReaderAcl(),
        )
        journal = boundary_ports.journal_factory(config.journal_path)
        cgroups = boundary_ports.cgroups
        manager = boundary_ports.systemd_manager
        client = boundary_ports.engine_client
        proc_cgroups = boundary_ports.proc_cgroups
        runtime_parent = MeasurementSystemdTransientSliceController(
            manager=manager,
            cgroups=cgroups,
            runtime_lifecycle=client,
            proc_cgroups=proc_cgroups,
            config=SystemdTransientSliceConfigV1(
                base_slice_name=config.systemd_base_slice,
                stable_final_samples=config.cgroup_measurement.stable_final_samples,
                cleanup_timeout_millis=config.cgroup_measurement.cleanup_timeout_millis,
            ),
        )
        registry = DockerExactRuntimeRegistry(
            client=client,
            recovery_timeout_millis=config.recovery_timeout_millis,
            monotonic=time.monotonic,
        )
        recovery = MeasurementAttemptRecoveryV2(
            journal=journal,
            staging=input_staging,
            runtime_registry=registry,
            runtime_parent=runtime_parent,
        )
        runtime = RootlessDockerRuntimeAdapter(
            client=client,
            host_proof=host_proof,
            images=FileLocalOciPairResolver(config.oci_pairs),
        )
        backend = backend_type(
            runtime=runtime,
            started_runtime=DockerStartedScopeVerifier(
                client=client,
                cgroups=cgroups,
                proc_cgroups=proc_cgroups,
            ),
            measurements=DockerCgroupRuntimeMeasurement(
                client=client,
                cgroups=cgroups,
                config=config.cgroup_measurement,
            ),
            frame_limits=config.frame_limits,
        )
        assembly = ExternalMeasurementAssemblyV2(
            required_worker_uid=config.required_worker_uid,
            catalog=FileInspectorManifestCatalog(config.catalog),
            verifier=Ed25519InspectorManifestVerifier(config.trust_root),
            accounting=_MeasurementAdmissionAccounting(config.admission_capacity),
            input_staging=input_staging,
            reader_mapping=mapping,
            attempt_journal=journal,
            attempt_recovery=recovery,
            runtime_parent=runtime_parent,
            runtime_cleanup=registry,
            backend=backend,
            protocol_limits=config.protocol_limits,
            systemd_base_slice=config.systemd_base_slice,
        )
        daemon = ExternalMeasurementSystemdDaemon.from_systemd_activation(
            listener_config=config.listener,
            assembly=assembly,
            environment=environment,
            activated_listener=activated_listener,
            owned_resources=(journal, *owned_boundary_resources),
        )
        daemon_transferred = True
        listener_transferred = True
        return daemon
    except MeasurementDaemonUnavailable:
        raise
    except Exception as exc:
        raise MeasurementDaemonUnavailable(
            "concrete V2 measurement dependencies are unavailable"
        ) from exc
    finally:
        # Transfer occurs only after a daemon object is returned to the caller.
        if not daemon_transferred:
            _close_owned_resources((journal, *owned_boundary_resources))
        if activated_listener is not None and not listener_transferred:
            activated_listener.close()


def build_daemon_from_measurement_operator_config(
    config: object,
    *,
    host_proof: _OperatorConfiguredHostProofPort,
    daemon_builder: _ProductionMeasurementDaemonBuilderPort = build_production_measurement_daemon,
    environment: dict[str, str] | None = None,
) -> ExternalMeasurementSystemdDaemon:
    """Preflight fixed config first, retaining the inherited listener only for the graph."""

    from ksi_processing_controller.external_measurement_operator_config import (
        ExternalMeasurementOperatorConfigV2,
        validate_measurement_operator_startup_artifacts,
    )

    if not isinstance(config, ExternalMeasurementOperatorConfigV2):
        raise MeasurementDaemonUnavailable("measurement operator configuration is invalid")
    if host_proof is None or not callable(getattr(host_proof, "verify_startup", None)):
        raise MeasurementDaemonUnavailable("rootless Docker host proof is unavailable")
    try:
        host_proof.verify_startup()
        validate_measurement_operator_startup_artifacts(config)
    except Exception as exc:
        raise MeasurementDaemonUnavailable("measurement startup preflight is unavailable") from exc
    try:
        receipt = verify_systemd_activated_listener(
            config.production.listener,
            required_worker_uid=config.production.required_worker_uid,
            environment=environment,
            deadline_monotonic=time.monotonic() + config.production.recovery_timeout_millis / 1000,
        )
    except InspectorDaemonUnavailable as exc:
        raise MeasurementDaemonUnavailable("measurement systemd listener is unavailable") from exc
    try:
        return daemon_builder(
            config=config.production,
            host_proof=host_proof,
            environment=environment,
            activated_listener=receipt,
        )
    except BaseException:
        receipt.close()
        raise


class ExternalMeasurementSystemdDaemon:
    """One V2 inherited local listener; no listener creation or V1 inheritance."""

    def __init__(
        self,
        *,
        listener: Any,
        launcher: ExternalMeasurementLauncher,
        preaccepted: deque[Any] | None = None,
        owned_resources: tuple[object, ...] = (),
        activated_listener: ActivatedListenerReceipt | None = None,
        proof_timeout_millis: int = 1_000,
    ) -> None:
        self._listener = listener
        self._launcher = launcher
        self._preaccepted = deque() if preaccepted is None else preaccepted
        self._closed = False
        self._lock = threading.Lock()
        self._owned_resources = owned_resources
        self._activated_listener = activated_listener
        self._proof_timeout_millis = proof_timeout_millis

    @classmethod
    def from_systemd_activation(
        cls,
        *,
        listener_config: SystemdActivatedListenerConfigV1,
        assembly: ExternalMeasurementAssemblyV2,
        environment: dict[str, str] | None = None,
        activated_listener: ActivatedListenerReceipt | None = None,
        owned_resources: tuple[object, ...] = (),
    ) -> ExternalMeasurementSystemdDaemon:
        receipt = activated_listener
        if receipt is None:
            try:
                receipt = verify_systemd_activated_listener(
                    listener_config,
                    required_worker_uid=assembly.required_worker_uid,
                    environment=environment,
                    deadline_monotonic=time.monotonic()
                    + assembly.protocol_limits.max_wire_duration_millis / 1000,
                )
            except InspectorDaemonUnavailable as exc:
                raise MeasurementDaemonUnavailable(
                    "measurement systemd listener is unavailable"
                ) from exc
        try:
            launcher = ExternalMeasurementLauncher(
                required_worker_uid=assembly.required_worker_uid,
                catalog=assembly.catalog,
                verifier=assembly.verifier,
                accounting=assembly.accounting,
                input_staging=assembly.input_staging,
                reader_mapping=assembly.reader_mapping,
                attempt_journal=assembly.attempt_journal,
                attempt_recovery=assembly.attempt_recovery,
                runtime_parent=assembly.runtime_parent,
                runtime_cleanup=assembly.runtime_cleanup,
                backend=assembly.backend,
                protocol_limits=assembly.protocol_limits,
                systemd_base_slice=assembly.systemd_base_slice,
            )
            return cls(
                listener=receipt.listener,
                launcher=launcher,
                preaccepted=receipt.preaccepted,
                owned_resources=owned_resources,
                activated_listener=receipt,
                proof_timeout_millis=assembly.protocol_limits.max_wire_duration_millis,
            )
        except BaseException:
            receipt.close()
            raise

    def serve_once(self) -> None:
        with self._lock:
            if self._closed:
                raise MeasurementDaemonUnavailable("measurement daemon is closed")
            connection = self._preaccepted.popleft() if self._preaccepted else None
        if connection is None:
            connection, _address = self._listener.accept()
        try:
            if (
                self._activated_listener is None
                or self._activated_listener.access_receipt is None
            ):
                raise MeasurementDaemonUnavailable(
                    "measurement listener access receipt is unavailable"
                )
            self._activated_listener.access_receipt.reprove(
                self._listener,
                deadline_monotonic=time.monotonic() + self._proof_timeout_millis / 1000,
                pending=self._preaccepted,
            )
        except BaseException:
            with suppress(OSError):
                connection.close()
            with suppress(BaseException):
                self.close()
            raise
        self._launcher.handle_connection(connection)

    def serve_forever(self) -> None:
        while True:
            self.serve_once()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            listener = self._listener
            activated_listener, self._activated_listener = self._activated_listener, None
            preaccepted = tuple(self._preaccepted)
            self._preaccepted.clear()
            owned_resources, self._owned_resources = self._owned_resources, ()
        try:
            if activated_listener is not None:
                activated_listener.close()
            else:
                listener.close()
        finally:
            try:
                for connection in preaccepted:
                    connection.close()
            finally:
                _close_owned_resources(owned_resources)


def main(argv: Sequence[str] | None = None) -> None:
    """Run V2 only from `--config <absolute-path>` and observed host proof."""

    values = tuple(sys.argv[1:] if argv is None else argv)
    if len(values) != 2 or values[0] != "--config" or not Path(values[1]).is_absolute():
        raise MeasurementDaemonUnavailable("external measurement requires --config <absolute-path>")
    from ksi_processing_controller.external_inspector_host_proof import RootlessDockerHostProofV1
    from ksi_processing_controller.external_measurement_operator_config import (
        MeasurementOperatorConfigUnavailable,
        load_external_measurement_operator_config,
    )

    try:
        config = load_external_measurement_operator_config(Path(values[1]))
        daemon = build_daemon_from_measurement_operator_config(
            config,
            host_proof=RootlessDockerHostProofV1(
                config.host_proof,
                startup_timeout_millis=config.production.recovery_timeout_millis,
            ),
        )
    except MeasurementOperatorConfigUnavailable as exc:
        raise MeasurementDaemonUnavailable(
            "external measurement operator configuration is unavailable"
        ) from exc
    try:
        daemon.serve_forever()
    finally:
        daemon.close()


__all__ = [
    "ExternalMeasurementAssemblyV2",
    "ExternalMeasurementSystemdDaemon",
    "MeasurementAdmissionCapacityV2",
    "MeasurementDaemonBoundaryPorts",
    "MeasurementDaemonUnavailable",
    "ProductionMeasurementConfigV2",
    "build_daemon_from_measurement_operator_config",
    "build_production_measurement_daemon",
    "main",
]
