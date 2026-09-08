"""Fail-closed systemd-activated local launcher assembly.

The daemon owns exactly one inherited AF_UNIX listener.  It creates no listener,
reads no Docker environment, and accepts no worker-selected runtime option.
Task 5 provisions the listener, UID, user manager, rootless Engine, cgroups,
ACL/mapping and private spool roots before this assembly may be started.
"""

from __future__ import annotations

import os
import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from ksi_event_contracts.inspector_execution_manifest import InspectorExecutionManifestVerifier
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind

from ksi_processing_controller.external_geotiff_profile import external_geotiff_profile_digest_v1
from ksi_processing_controller.external_inspector_access import (
    LibaclNamedReaderAcl,
    ProcUserNamespaceReaderMapping,
    UserNamespaceMappingConfigV1,
)
from ksi_processing_controller.external_inspector_attempts import (
    InspectorAttemptJournal,
    InspectorAttemptRecovery,
)
from ksi_processing_controller.external_inspector_catalog import (
    Ed25519InspectorManifestVerifier,
    FileInspectorCatalogConfigV1,
    FileInspectorManifestCatalog,
    InspectorTrustRootV1,
)
from ksi_processing_controller.external_inspector_container_protocol import (
    ContainerInnerFrameLimitsV1,
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
from ksi_processing_controller.external_inspector_docker_backend import DockerInspectorBackend
from ksi_processing_controller.external_inspector_launcher import (
    ExternalInspectorLauncher,
    InspectorAdmissionAccountingPort,
    InspectorAttemptJournalPort,
    InspectorAttemptRecoveryPort,
    InspectorBackendPort,
    InspectorManifestCatalogPort,
    InspectorOperationProfileDecision,
    InspectorOperationProfilePort,
    InspectorRuntimeCleanupPort,
    InspectorRuntimeParentPort,
    InspectorStagingPort,
)
from ksi_processing_controller.external_inspector_protocol import (
    InspectorOperation,
    ProtocolLimitsV1,
)
from ksi_processing_controller.external_inspector_staging import (
    FileSystemInputStaging,
    FileSystemOutputStaging,
    ReaderMappingPort,
    RegisteredInputStagingPort,
)
from ksi_processing_controller.external_inspector_systemd import (
    LibsystemdUserManager,
    SystemdTransientSliceConfigV1,
    SystemdTransientSliceController,
    UserSystemdBusConfigV1,
)


class InspectorDaemonUnavailable(RuntimeError):
    """A required systemd activation or concrete assembly dependency is unavailable."""


@dataclass(frozen=True, slots=True)
class InspectorAdmissionCapacityV1:
    """Required operator capacity for launcher-owned request and private-spool reservations."""

    maximum_request_units: int
    maximum_concurrency_units: int
    maximum_spool_bytes: int

    def __post_init__(self) -> None:
        if any(
            type(value) is not int or value <= 0
            for value in (
                self.maximum_request_units,
                self.maximum_concurrency_units,
                self.maximum_spool_bytes,
            )
        ):
            raise ValueError("all inspector admission capacities are required")


@dataclass(frozen=True, slots=True)
class ProductionInspectorConfigV1:
    """All operator-controlled assembly facts; none is read from ambient environment."""

    required_worker_uid: int
    listener: SystemdActivatedListenerConfigV1
    catalog: FileInspectorCatalogConfigV1
    trust_root: InspectorTrustRootV1
    input_root: Path
    output_root: Path
    reader_mapping: UserNamespaceMappingConfigV1
    journal_path: Path
    docker_socket: RootlessDockerSocketConfigV1
    oci_pairs: FileOciPairResolverConfigV1
    cgroup_root: CgroupV2RootConfigV1
    systemd_bus: UserSystemdBusConfigV1
    systemd_base_slice: str
    recovery_timeout_millis: int
    admission_capacity: InspectorAdmissionCapacityV1
    protocol_limits: ProtocolLimitsV1
    frame_limits: ContainerInnerFrameLimitsV1
    cgroup_measurement: DockerCgroupMeasurementConfigV1

    def __post_init__(self) -> None:
        if type(self.required_worker_uid) is not int or self.required_worker_uid < 0:
            raise ValueError("required worker UID is invalid")
        if not self.input_root.is_absolute() or not self.output_root.is_absolute():
            raise ValueError("private input and output roots are required")
        if not self.journal_path.is_absolute():
            raise ValueError("durable attempt journal path is required")
        if (
            type(self.recovery_timeout_millis) is not int
            or self.recovery_timeout_millis <= 0
            or not self.systemd_base_slice.endswith(".slice")
            or "/" in self.systemd_base_slice
        ):
            raise ValueError("runtime recovery and systemd base slice are required")


class _AdmissionReservation:
    def __init__(
        self,
        owner: BoundedInspectorAdmissionAccounting,
        request_units: int,
        concurrency_units: int,
        spool_bytes: int,
    ) -> None:
        self._owner = owner
        self._values = (request_units, concurrency_units, spool_bytes)
        self._released = False

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        self._owner._release(*self._values)


class BoundedInspectorAdmissionAccounting:
    """Concrete in-process capacity accounting with no unbounded successful path."""

    def __init__(self, capacity: InspectorAdmissionCapacityV1) -> None:
        self._capacity = capacity
        self._lock = threading.Lock()
        self._used_request_units = 0
        self._used_concurrency_units = 0
        self._used_spool_bytes = 0

    def reserve(
        self,
        *,
        request_units: int,
        concurrency_units: int,
        spool_bytes: int,
        deadline_monotonic: float,
    ) -> _AdmissionReservation | None:
        del deadline_monotonic
        values = (request_units, concurrency_units, spool_bytes)
        if any(type(value) is not int or value < 0 for value in values):
            return None
        if values == (0, 0, 0):
            return None
        with self._lock:
            candidate = (
                self._used_request_units + request_units,
                self._used_concurrency_units + concurrency_units,
                self._used_spool_bytes + spool_bytes,
            )
            if any(
                used > capacity
                for used, capacity in zip(
                    candidate,
                    (
                        self._capacity.maximum_request_units,
                        self._capacity.maximum_concurrency_units,
                        self._capacity.maximum_spool_bytes,
                    ),
                    strict=True,
                )
            ):
                return None
            (
                self._used_request_units,
                self._used_concurrency_units,
                self._used_spool_bytes,
            ) = candidate
        return _AdmissionReservation(self, *values)

    def _release(self, request_units: int, concurrency_units: int, spool_bytes: int) -> None:
        with self._lock:
            candidate = (
                self._used_request_units - request_units,
                self._used_concurrency_units - concurrency_units,
                self._used_spool_bytes - spool_bytes,
            )
            if any(value < 0 for value in candidate):
                raise InspectorDaemonUnavailable("inspector admission accounting underflow")
            (
                self._used_request_units,
                self._used_concurrency_units,
                self._used_spool_bytes,
            ) = candidate


class FixedInspectorOperationProfile:
    """The production assembly's closed GeoTIFF operation gate, never a MIME default."""

    def allows(
        self,
        *,
        parser_build_digest: str,
        grammar_digest: str,
        artifact_kind: ProcessingArtifactKind,
        content_type: str,
        operation: InspectorOperation,
    ) -> InspectorOperationProfileDecision:
        if (
            not isinstance(parser_build_digest, str)
            or not parser_build_digest.startswith("sha256:")
            or grammar_digest != external_geotiff_profile_digest_v1()
            or content_type != "image/tiff"
            or artifact_kind not in {ProcessingArtifactKind.ORTHO, ProcessingArtifactKind.DSM}
        ):
            return InspectorOperationProfileDecision.DENY
        if operation is InspectorOperation.INSPECT:
            return InspectorOperationProfileDecision.ALLOW
        if (
            operation is InspectorOperation.SANITIZE
            and artifact_kind is ProcessingArtifactKind.ORTHO
        ):
            return InspectorOperationProfileDecision.ALLOW
        return InspectorOperationProfileDecision.DENY


@dataclass(frozen=True, slots=True)
class SystemdActivatedListenerConfigV1:
    socket_path: Path
    expected_owner_uid: int

    def __post_init__(self) -> None:
        if not self.socket_path.is_absolute():
            raise ValueError("activated inspector listener path must be absolute")
        if type(self.expected_owner_uid) is not int or self.expected_owner_uid < 0:
            raise ValueError("activated inspector listener owner is invalid")


@dataclass(frozen=True, slots=True)
class ExternalInspectorAssemblyV1:
    """Every dependency is explicit; there is no successful test-only fallback."""

    required_worker_uid: int
    catalog: InspectorManifestCatalogPort
    verifier: InspectorExecutionManifestVerifier
    operation_profile: InspectorOperationProfilePort
    accounting: InspectorAdmissionAccountingPort
    input_staging: RegisteredInputStagingPort
    reader_mapping: ReaderMappingPort
    attempt_journal: InspectorAttemptJournalPort
    attempt_recovery: InspectorAttemptRecoveryPort
    runtime_parent: InspectorRuntimeParentPort
    runtime_cleanup: InspectorRuntimeCleanupPort
    backend: InspectorBackendPort
    protocol_limits: ProtocolLimitsV1
    systemd_base_slice: str


def build_production_daemon(
    *,
    config: ProductionInspectorConfigV1,
    host_proof: RootlessDockerHostProofPort,
    environment: dict[str, str] | None = None,
) -> ExternalInspectorSystemdDaemon:
    """Construct the closed production adapter graph from explicit operator facts only.

    The Task 5 host-proof implementation is intentionally required.  Supplying no
    proof cannot produce a daemon that admits an attempt, and this function does
    not create a Docker socket, cgroup, user-manager unit, identity, or listener.
    """
    if host_proof is None:
        raise InspectorDaemonUnavailable("rootless Docker host proof is unavailable")
    mapping = ProcUserNamespaceReaderMapping(config.reader_mapping)
    try:
        acl = LibaclNamedReaderAcl()
        input_staging = FileSystemInputStaging(
            private_root=config.input_root,
            reader_mapping=mapping,
            acl=acl,
        )
        output_staging = FileSystemOutputStaging(private_root=config.output_root)
        journal = InspectorAttemptJournal(config.journal_path)
        cgroups = CgroupV2RootV1(config.cgroup_root)
        manager = LibsystemdUserManager(config.systemd_bus)
    except Exception as exc:
        raise InspectorDaemonUnavailable(
            "concrete inspector local dependencies are unavailable"
        ) from exc
    wire = UnixSocketDockerEngineWire(config.docker_socket)
    client = DockerEngineClientV1(wire)
    proc_cgroups = ProcCgroupReader(maximum_bytes=config.cgroup_root.maximum_control_bytes)
    runtime_parent = SystemdTransientSliceController(
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
    recovery = InspectorAttemptRecovery(
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
    backend = DockerInspectorBackend(
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
    assembly = ExternalInspectorAssemblyV1(
        required_worker_uid=config.required_worker_uid,
        catalog=FileInspectorManifestCatalog(config.catalog),
        verifier=Ed25519InspectorManifestVerifier(config.trust_root),
        operation_profile=FixedInspectorOperationProfile(),
        accounting=BoundedInspectorAdmissionAccounting(config.admission_capacity),
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
    return ExternalInspectorSystemdDaemon.from_systemd_activation(
        listener_config=config.listener,
        assembly=assembly,
        output_staging=output_staging,
        environment=environment,
    )


class ExternalInspectorSystemdDaemon:
    """Concrete one-listener serving loop. Construction completes recovery first."""

    def __init__(
        self,
        *,
        listener: socket.socket,
        launcher: ExternalInspectorLauncher,
    ) -> None:
        self._listener = listener
        self._launcher = launcher

    @classmethod
    def from_systemd_activation(
        cls,
        *,
        listener_config: SystemdActivatedListenerConfigV1,
        assembly: ExternalInspectorAssemblyV1,
        output_staging: InspectorStagingPort | None,
        environment: dict[str, str] | None = None,
    ) -> ExternalInspectorSystemdDaemon:
        """Use exactly one systemd-inherited FD and no caller-created socket.

        `output_staging` is deliberately required even before Task 4B uses it;
        an assembly with no private sanitize spool must not advertise readiness.
        """
        if output_staging is None:
            raise InspectorDaemonUnavailable("private output staging is unavailable")
        values = os.environ if environment is None else environment
        try:
            listen_pid = int(values["LISTEN_PID"])
            listen_fds = int(values["LISTEN_FDS"])
        except (KeyError, ValueError) as exc:
            raise InspectorDaemonUnavailable("systemd activation is unavailable") from exc
        if listen_pid != os.getpid() or listen_fds != 1:
            raise InspectorDaemonUnavailable("exactly one systemd listener is required")
        listener = socket.socket(fileno=os.dup(3))
        try:
            if listener.family != socket.AF_UNIX:
                raise InspectorDaemonUnavailable("activated inspector listener is not AF_UNIX")
            address = listener.getsockname()
            if address != os.fspath(listener_config.socket_path):
                raise InspectorDaemonUnavailable("activated inspector listener path is invalid")
            node = os.lstat(listener_config.socket_path)
            if node.st_uid != listener_config.expected_owner_uid:
                raise InspectorDaemonUnavailable("activated inspector listener owner is invalid")
            launcher = ExternalInspectorLauncher(
                required_worker_uid=assembly.required_worker_uid,
                catalog=assembly.catalog,
                verifier=assembly.verifier,
                operation_profile=assembly.operation_profile,
                accounting=assembly.accounting,
                staging=output_staging,
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
            return cls(listener=listener, launcher=launcher)
        except Exception:
            listener.close()
            raise

    def serve_once(self) -> None:
        connection, _address = self._listener.accept()
        self._launcher.handle_connection(connection)

    def serve_forever(self) -> None:
        while True:
            self.serve_once()

    def close(self) -> None:
        self._listener.close()


def main() -> None:
    """Fail closed until Task 5 injects the complete operator configuration and host proof."""
    raise InspectorDaemonUnavailable(
        "external inspector requires explicit operator configuration and host proof"
    )


__all__ = [
    "BoundedInspectorAdmissionAccounting",
    "ExternalInspectorAssemblyV1",
    "ExternalInspectorSystemdDaemon",
    "FixedInspectorOperationProfile",
    "InspectorDaemonUnavailable",
    "InspectorAdmissionCapacityV1",
    "ProductionInspectorConfigV1",
    "SystemdActivatedListenerConfigV1",
    "build_production_daemon",
    "main",
]
