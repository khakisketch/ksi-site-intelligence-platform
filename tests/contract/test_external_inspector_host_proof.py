"""Strict local host-proof and operator-bootstrap contract coverage.

These tests use a private synthetic proc tree and AF_UNIX socket.  They prove
the adapter's observable comparison behavior only; they do not constitute a
real rootless Docker, systemd, image-signature, or deployment acceptance.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from ksi_processing_controller.external_inspector_container_protocol import (
    FixedContainerConfigurationV1,
    FixedInputMountV1,
)
from ksi_processing_controller.external_inspector_host_proof import (
    HostProofBlockedCode,
    ProcfsHostProofObserver,
    RootlessDockerHostProofConfigV1,
    RootlessDockerHostProofUnavailable,
    RootlessDockerHostProofV1,
)


class _BorrowedSource:
    def read_at(self, *, offset: int, maximum_bytes: int) -> bytes:
        del offset, maximum_bytes
        return b""

    def consume_fd(self, consumer: object) -> object:
        del consumer
        raise AssertionError("host proof must not consume the source capability")


def _digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _write_proc_fixture(
    *,
    proc_root: Path,
    pid: int,
    uid: int,
    gid: int,
    uid_map: bytes,
    gid_map: bytes,
    cgroup: str,
) -> None:
    process = proc_root / str(pid)
    process.mkdir(parents=True)
    (process / "status").write_text(
        f"Name:\trootlesskit\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\nGid:\t{gid}\t{gid}\t{gid}\t{gid}\n",
        encoding="ascii",
    )
    # The field after state plus eighteen zero fields is /proc stat field 22
    # (starttime).  The observer requires it to remain stable across reads.
    (process / "stat").write_text(
        f"{pid} (rootlesskit) S " + "0 " * 18 + "101 " + "0 " * 8 + "\n",
        encoding="ascii",
    )
    (process / "uid_map").write_bytes(uid_map)
    (process / "gid_map").write_bytes(gid_map)
    (process / "cgroup").write_text(f"0::{cgroup}\n", encoding="ascii")


def _proof_config(
    *,
    tmp_path: Path,
    socket_path: Path,
    uid_map: bytes,
    gid_map: bytes,
    launcher_cgroup: str = "/user.slice/ksi-inspector.slice",
    daemon_cgroup: str = "/user.slice/ksi-inspector.slice",
) -> RootlessDockerHostProofConfigV1:
    uid = os.geteuid()
    gid = os.getegid()
    pid_path = tmp_path / "rootless-daemon.pid"
    pid_path.write_text(f"{os.getpid()}\n", encoding="ascii")
    pid_path.chmod(0o600)
    return RootlessDockerHostProofConfigV1(
        launcher_uid=uid,
        launcher_gid=gid,
        worker_uid=uid + 1,
        rootless_daemon_pid_path=pid_path,
        daemon_uid_map_sha256=_digest(uid_map),
        daemon_gid_map_sha256=_digest(gid_map),
        launcher_cgroup_path=launcher_cgroup,
        daemon_cgroup_path=daemon_cgroup,
        systemd_base_slice="ksi-inspector.slice",
        docker_socket_path=socket_path,
        retained_input_mode=0o600,
    )


def _activated_distinct_worker_listener(
    _tmp_path: Path, worker_uid: int
) -> tuple[socket.socket, Path, Path]:
    root = Path(tempfile.mkdtemp(prefix="lacl-inspector-", dir="/tmp"))
    root.chmod(0o700)
    subprocess.run(("setfacl", "-b", os.fspath(root)), check=True, capture_output=True)
    subprocess.run(("setfacl", "-k", os.fspath(root)), check=True, capture_output=True)
    subprocess.run(
        ("setfacl", "-m", f"u:{worker_uid}:x", os.fspath(root)),
        check=True,
        capture_output=True,
    )
    parent = root / "p"
    parent.mkdir(mode=0o700)
    subprocess.run(("setfacl", "-b", os.fspath(parent)), check=True, capture_output=True)
    subprocess.run(("setfacl", "-k", os.fspath(parent)), check=True, capture_output=True)
    subprocess.run(
        ("setfacl", "-m", f"u:{worker_uid}:x", os.fspath(parent)),
        check=True,
        capture_output=True,
    )
    path = parent / "s"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(os.fspath(path))
    listener.listen(1)
    path.chmod(0o600)
    subprocess.run(("setfacl", "-b", os.fspath(path)), check=True, capture_output=True)
    subprocess.run(
        ("setfacl", "-m", f"u:{worker_uid}:rw", os.fspath(path)),
        check=True,
        capture_output=True,
    )
    return listener, path, root


def _configuration(source_path: Path) -> FixedContainerConfigurationV1:
    node = source_path.stat()
    return FixedContainerConfigurationV1(
        image_manifest_digest="sha256:" + "a" * 64,
        image_config_digest="sha256:" + "b" * 64,
        runtime_uid=101_001,
        runtime_gid=101_001,
        supplementary_groups=(),
        runtime_environment=(),
        allowed_grid_digests=(),
        input_mount=FixedInputMountV1(
            source=_BorrowedSource(),
            target_path="/input/artifact.tif",
            read_only=True,
            observed_sha256="sha256:" + "c" * 64,
            observed_size_bytes=node.st_size,
            source_device=node.st_dev,
            source_inode=node.st_ino,
            reader_mapping_witness="sha256:" + "d" * 64,
        ),
        memory_bytes=1,
        tmpfs_bytes=1,
        swap_bytes=0,
        pids=1,
        cpu_period_micros=1,
        cpu_quota_micros=1,
        wall_time_millis=1,
        log_bytes=1,
        output_bytes=1,
        cpu_budget_counter=1,
    )


def test_production_host_proof_rejects_same_listener_owner_and_worker_uid(tmp_path: Path) -> None:
    """The 0600 owner-only listener fixture is never a production identity profile."""
    proof, _source = _proof_fixture(tmp_path)
    with pytest.raises(ValueError, match="must differ"):
        replace(proof.config, worker_uid=proof.config.launcher_uid)


_LIVE_LISTENERS: dict[Path, tuple[socket.socket, threading.Thread]] = {}


@pytest.fixture(autouse=True)
def _close_live_proof_listeners():
    yield
    for listener, thread in tuple(_LIVE_LISTENERS.values()):
        listener.close()
        thread.join(timeout=1)
        assert not thread.is_alive()
    _LIVE_LISTENERS.clear()


def _proof_fixture(tmp_path: Path) -> tuple[RootlessDockerHostProofV1, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    socket_path = tmp_path / "rootless-docker.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(os.fspath(socket_path))
    listener.listen(16)
    listener.settimeout(0.05)

    def drain() -> None:
        while listener.fileno() >= 0:
            try:
                connection, _ = listener.accept()
                connection.close()
            except TimeoutError:
                continue
            except OSError:
                return

    thread = threading.Thread(target=drain)
    thread.start()
    _LIVE_LISTENERS[socket_path] = (listener, thread)
    socket_path.chmod(0o600)
    uid_map = f"0 {os.geteuid()} 1\n1 100000 65536\n".encode("ascii")
    gid_map = f"0 {os.getegid()} 1\n1 100000 65536\n".encode("ascii")
    proc_root = tmp_path / "proc"
    _write_proc_fixture(
        proc_root=proc_root,
        pid=os.getpid(),
        uid=os.geteuid(),
        gid=os.getegid(),
        uid_map=uid_map,
        gid_map=gid_map,
        cgroup="/user.slice/ksi-inspector.slice",
    )
    proof = RootlessDockerHostProofV1(
        _proof_config(
            tmp_path=tmp_path,
            socket_path=socket_path,
            uid_map=uid_map,
            gid_map=gid_map,
        ),
        startup_timeout_millis=100,
        observer=ProcfsHostProofObserver(proc_root=proc_root),
    )
    source = tmp_path / "sealed-input.tif"
    source.write_bytes(b"sealed fixture")
    source.chmod(0o600)
    return proof, source


def test_concrete_host_proof_rechecks_fixture_proc_socket_slice_and_retained_fd(
    tmp_path: Path,
) -> None:
    proof, source = _proof_fixture(tmp_path)
    configuration = _configuration(source)

    facts = proof.prove(configuration=configuration)
    with source.open("rb") as handle:
        candidate = f"/proc/{os.getpid()}/fd/{handle.fileno()}"
        assert facts.verify_proc_fd(
            fd=handle.fileno(), candidate=candidate, configuration=configuration
        )
    assert facts.verify_slice(binding=SimpleNamespace(systemd_base_slice="ksi-inspector.slice"))


def test_host_proof_rejects_rootful_map_even_when_operator_digest_matches(tmp_path: Path) -> None:
    proof, source = _proof_fixture(tmp_path)
    config = proof.config
    rootful_map = b"0 0 4294967295\n"
    process = tmp_path / "proc" / str(os.getpid())
    (process / "uid_map").write_bytes(rootful_map)
    (process / "gid_map").write_bytes(rootful_map)
    proof = RootlessDockerHostProofV1(
        RootlessDockerHostProofConfigV1(
            launcher_uid=config.launcher_uid,
            launcher_gid=config.launcher_gid,
            worker_uid=config.worker_uid,
            rootless_daemon_pid_path=config.rootless_daemon_pid_path,
            daemon_uid_map_sha256=_digest(rootful_map),
            daemon_gid_map_sha256=_digest(rootful_map),
            launcher_cgroup_path=config.launcher_cgroup_path,
            daemon_cgroup_path=config.daemon_cgroup_path,
            systemd_base_slice=config.systemd_base_slice,
            docker_socket_path=config.docker_socket_path,
            retained_input_mode=config.retained_input_mode,
        ),
        startup_timeout_millis=100,
        observer=ProcfsHostProofObserver(proc_root=tmp_path / "proc"),
    )

    with pytest.raises(RootlessDockerHostProofUnavailable) as raised:
        proof.prove(configuration=_configuration(source))

    assert raised.value.code is HostProofBlockedCode.USER_NAMESPACE


def test_host_proof_rejects_replaced_socket_and_unbound_fd(tmp_path: Path) -> None:
    proof, source = _proof_fixture(tmp_path)
    configuration = _configuration(source)
    proof.verify_startup()
    proof.config.docker_socket_path.chmod(0o640)

    with pytest.raises(RootlessDockerHostProofUnavailable) as raised:
        proof.prove(configuration=configuration)

    assert raised.value.code is HostProofBlockedCode.SOCKET_IDENTITY

    fresh_proof, _ = _proof_fixture(tmp_path / "other")
    facts = fresh_proof.prove(configuration=configuration)
    other = tmp_path / "replacement.tif"
    other.write_bytes(b"different inode")
    other.chmod(0o600)
    with other.open("rb") as handle:
        assert not facts.verify_proc_fd(
            fd=handle.fileno(),
            candidate=f"/proc/{os.getpid()}/fd/{handle.fileno()}",
            configuration=configuration,
        )


@pytest.mark.parametrize(
    ("entry", "contents", "code"),
    [
        ("status", "Name:\twrong\nUid:\t1\t1\t1\t1\nGid:\t1\t1\t1\t1\n", "DAEMON_IDENTITY"),
        ("cgroup", "0::/unrelated.slice\n", "CGROUP_IDENTITY"),
    ],
)
def test_host_proof_rejects_wrong_observed_identity_or_cgroup(
    tmp_path: Path, entry: str, contents: str, code: str
) -> None:
    proof, source = _proof_fixture(tmp_path)
    (tmp_path / "proc" / str(os.getpid()) / entry).write_text(contents, encoding="ascii")

    with pytest.raises(RootlessDockerHostProofUnavailable) as raised:
        proof.prove(configuration=_configuration(source))

    assert raised.value.code.value == code


def test_operator_config_rejects_symlink_unknown_field_and_missing_catalog(tmp_path: Path) -> None:
    from ksi_processing_controller.external_inspector_operator_config import (
        OperatorConfigBlockedCode,
        OperatorConfigUnavailable,
        load_external_inspector_operator_config,
        validate_operator_startup_artifacts,
    )

    config_path = tmp_path / "operator.json"
    config_path.write_text(
        json.dumps(
            {
                "version": "external-inspector-operator-config.v1",
                "unexpected": True,
            }
        ),
        encoding="utf-8",
    )
    config_path.chmod(0o600)
    with pytest.raises(OperatorConfigUnavailable) as unknown:
        load_external_inspector_operator_config(config_path)
    assert unknown.value.code is OperatorConfigBlockedCode.UNKNOWN_FIELD

    linked = tmp_path / "operator-link.json"
    linked.symlink_to(config_path)
    with pytest.raises(OperatorConfigUnavailable) as symlink:
        load_external_inspector_operator_config(linked)
    assert symlink.value.code is OperatorConfigBlockedCode.CONFIG_FILE

    # Startup artifact validation must reject a missing catalog before the
    # daemon builder can initialize a listener, systemd client, or Docker wire.
    from ksi_processing_controller.external_inspector_access import UserNamespaceMappingConfigV1
    from ksi_processing_controller.external_inspector_catalog import (
        FileInspectorCatalogConfigV1,
        InspectorTrustRootV1,
    )
    from ksi_processing_controller.external_inspector_container_protocol import (
        ContainerInnerFrameLimitsV1,
    )
    from ksi_processing_controller.external_inspector_daemon import (
        InspectorAdmissionCapacityV1,
        ProductionInspectorConfigV1,
        SystemdActivatedListenerConfigV1,
    )
    from ksi_processing_controller.external_inspector_docker import (
        CgroupV2RootConfigV1,
        DockerCgroupMeasurementConfigV1,
        FileOciPairResolverConfigV1,
        RootlessDockerSocketConfigV1,
    )
    from ksi_processing_controller.external_inspector_protocol import ProtocolLimitsV1
    from ksi_processing_controller.external_inspector_systemd import UserSystemdBusConfigV1

    proof, _source = _proof_fixture(tmp_path / "startup")
    production = ProductionInspectorConfigV1(
        required_worker_uid=proof.config.worker_uid,
        listener=SystemdActivatedListenerConfigV1(tmp_path / "listener.sock", os.geteuid()),
        catalog=FileInspectorCatalogConfigV1(
            manifest_path=tmp_path / "missing-manifest.json",
            revocation_path=tmp_path / "missing-revocations.json",
            expected_revocation_sha256="sha256:" + "a" * 64,
        ),
        trust_root=InspectorTrustRootV1({"fixture": bytes(32)}),
        input_root=tmp_path / "input",
        output_root=tmp_path / "output",
        reader_mapping=UserNamespaceMappingConfigV1(
            uid_map_path=tmp_path / "uid_map",
            gid_map_path=tmp_path / "gid_map",
            maximum_map_bytes=4096,
        ),
        journal_path=tmp_path / "attempts.jsonl",
        docker_socket=RootlessDockerSocketConfigV1(
            socket_path=proof.config.docker_socket_path,
            expected_owner_uid=os.geteuid(),
            expected_mode=0o600,
            maximum_response_bytes=4096,
        ),
        oci_pairs=FileOciPairResolverConfigV1(
            proof_path=tmp_path / "missing-oci.json",
            expected_sha256="sha256:" + "b" * 64,
        ),
        cgroup_root=CgroupV2RootConfigV1(tmp_path / "cgroup", "/base.slice", 4096),
        systemd_bus=UserSystemdBusConfigV1(
            bus_kind="SESSION_BUS",
            socket_path=tmp_path / "bus",
            expected_owner_uid=os.geteuid(),
            expected_mode=0o600,
            timeout_micros=1_000,
        ),
        systemd_base_slice="ksi-inspector.slice",
        recovery_timeout_millis=1_000,
        admission_capacity=InspectorAdmissionCapacityV1(1, 1, 1),
        protocol_limits=ProtocolLimitsV1(
            max_header_bytes=1,
            max_chunk_bytes=1,
            max_input_bytes=1,
            max_output_bytes=1,
            max_wire_duration_millis=1,
        ),
        frame_limits=ContainerInnerFrameLimitsV1(1, 0),
        cgroup_measurement=DockerCgroupMeasurementConfigV1(1, 2, 1_000),
    )
    from ksi_processing_controller.external_inspector_operator_config import (
        ExternalInspectorOperatorConfigV1,
    )

    with pytest.raises(OperatorConfigUnavailable) as missing:
        validate_operator_startup_artifacts(
            ExternalInspectorOperatorConfigV1(production=production, host_proof=proof.config)
        )
    assert missing.value.code is OperatorConfigBlockedCode.CATALOG


def test_daemon_cli_requires_one_strict_config_path_before_any_assembly(tmp_path: Path) -> None:
    from ksi_processing_controller.external_inspector_daemon import (
        InspectorDaemonUnavailable,
        main,
    )

    with pytest.raises(InspectorDaemonUnavailable, match="operator configuration"):
        main(["--config", os.fspath(tmp_path / "missing.json")])


def _signed_operator_config(
    tmp_path: Path,
    *,
    proof: RootlessDockerHostProofV1,
    listener_path: Path,
) -> Path:
    import base64

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from ksi_event_contracts.inspector_execution_manifest import (
        InspectorExecutionHardCeilingsV1,
        InspectorExecutionManifestBodyV1,
        InspectorExecutionManifestSignatureV1,
        InspectorExecutionManifestV1,
        InspectorImageIdentityV1,
        InspectorSecurityProfileV1,
    )

    private = Ed25519PrivateKey.generate()
    body = InspectorExecutionManifestBodyV1(
        image_identity=InspectorImageIdentityV1(
            oci_manifest_digest="sha256:" + "a" * 64,
            oci_config_digest="sha256:" + "b" * 64,
        ),
        source_tree_digest="sha256:" + "c" * 64,
        build_provenance_digest="sha256:" + "d" * 64,
        sbom_digest="sha256:" + "e" * 64,
        inspector_protocol_digest="sha256:" + "f" * 64,
        backend_profile_digest="sha256:" + "1" * 64,
        security_profile_digest="sha256:" + "2" * 64,
        resource_envelope_digest="sha256:" + "3" * 64,
        backend="DEDICATED_ROOTLESS_DOCKER_V1",
        runtime_uid=101_001,
        runtime_gid=101_001,
        runtime_environment=(
            ("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR"),
            ("GDAL_DRIVER_PATH", "disable"),
            ("GDAL_PAM_ENABLED", "NO"),
            ("PROJ_NETWORK", "OFF"),
            ("PYTHONDONTWRITEBYTECODE", "1"),
        ),
        security_profile=InspectorSecurityProfileV1(),
        hard_ceilings=InspectorExecutionHardCeilingsV1(
            max_input_bytes=10,
            max_memory_bytes=10,
            max_tmpfs_bytes=10,
            max_pids=1,
            cpu_period_micros=1,
            cpu_quota_micros=1,
            max_wall_time_millis=1,
            max_log_bytes=1,
            max_output_bytes=1,
        ),
    )
    manifest = InspectorExecutionManifestV1(
        body=body,
        signature=InspectorExecutionManifestSignatureV1(
            algorithm="Ed25519",
            key_id="fixture-key",
            digest=body.canonical_body_digest(),
            signature=base64.b64encode(private.sign(body.canonical_body_bytes())).decode("ascii"),
        ),
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest.model_dump(by_alias=True, mode="json")), encoding="utf-8"
    )
    revocations = json.dumps(
        {"version": "external-inspector-revocations.v1", "revokedManifestDigests": []},
        separators=(",", ":"),
    ).encode("utf-8")
    revocation_path = tmp_path / "revocations.json"
    revocation_path.write_bytes(revocations)
    pairs = json.dumps(
        {
            "version": "external-inspector-oci-pairs.v1",
            "pairs": [
                {
                    "ociManifestDigest": manifest.body.image_identity.oci_manifest_digest,
                    "ociConfigDigest": manifest.body.image_identity.oci_config_digest,
                    "dockerImageId": manifest.body.image_identity.oci_config_digest,
                }
            ],
        },
        separators=(",", ":"),
    ).encode("utf-8")
    pairs_path = tmp_path / "oci-pairs.json"
    pairs_path.write_bytes(pairs)
    for artifact_path in (manifest_path, revocation_path, pairs_path):
        artifact_path.chmod(0o600)
    uid_map_path = tmp_path / "reader-uid-map"
    gid_map_path = tmp_path / "reader-gid-map"
    uid_map_path.write_text("0 1000 1\n", encoding="ascii")
    gid_map_path.write_text("0 1000 1\n", encoding="ascii")
    public_key = base64.b64encode(private.public_key().public_bytes_raw()).decode("ascii")
    payload = {
        "version": "external-inspector-operator-config.v1",
        "production": {
            "requiredWorkerUid": proof.config.worker_uid,
            "listener": {
                "socketPath": os.fspath(listener_path),
                "expectedOwnerUid": proof.config.launcher_uid,
            },
            "catalog": {
                "manifestPath": os.fspath(manifest_path),
                "revocationPath": os.fspath(revocation_path),
                "expectedRevocationSha256": _digest(revocations),
            },
            "trustRoot": {"publicKeys": {"fixture-key": public_key}},
            "inputRoot": os.fspath(tmp_path / "input"),
            "outputRoot": os.fspath(tmp_path / "output"),
            "readerMapping": {
                "uidMapPath": os.fspath(uid_map_path),
                "gidMapPath": os.fspath(gid_map_path),
                "maximumMapBytes": 4096,
            },
            "journalPath": os.fspath(tmp_path / "attempts.jsonl"),
            "dockerSocket": {
                "socketPath": os.fspath(proof.config.docker_socket_path),
                "expectedOwnerUid": proof.config.launcher_uid,
                "expectedMode": 0o600,
                "maximumResponseBytes": 4096,
            },
            "ociPairs": {"proofPath": os.fspath(pairs_path), "expectedSha256": _digest(pairs)},
            "cgroupRoot": {
                "root": os.fspath(tmp_path / "cgroup"),
                "baseControlGroup": "/base.slice/ksi-inspector.slice",
                "maximumControlBytes": 4096,
            },
            "systemdBus": {
                "busKind": "SESSION_BUS",
                "socketPath": os.fspath(tmp_path / "bus"),
                "expectedOwnerUid": proof.config.launcher_uid,
                "expectedMode": 0o600,
                "timeoutMicros": 1_000,
            },
            "systemdBaseSlice": proof.config.systemd_base_slice,
            "recoveryTimeoutMillis": 1_000,
            "admissionCapacity": {
                "maximumRequestUnits": 1,
                "maximumConcurrencyUnits": 1,
                "maximumSpoolBytes": 10,
            },
            "protocolLimits": {
                "maxHeaderBytes": 10,
                "maxChunkBytes": 10,
                "maxInputBytes": 10,
                "maxOutputBytes": 10,
                "maxWireDurationMillis": 10,
            },
            "frameLimits": {"maximumFrameBytes": 10, "maximumStderrBytes": 0},
            "cgroupMeasurement": {
                "monitorIntervalMillis": 1,
                "stableFinalSamples": 2,
                "cleanupTimeoutMillis": 1_000,
            },
        },
        "hostProof": {
            "launcherUid": proof.config.launcher_uid,
            "launcherGid": proof.config.launcher_gid,
            "workerUid": proof.config.worker_uid,
            "rootlessDaemonPidPath": os.fspath(proof.config.rootless_daemon_pid_path),
            "daemonUidMapSha256": proof.config.daemon_uid_map_sha256,
            "daemonGidMapSha256": proof.config.daemon_gid_map_sha256,
            "launcherCgroupPath": proof.config.launcher_cgroup_path,
            "daemonCgroupPath": proof.config.daemon_cgroup_path,
            "systemdBaseSlice": proof.config.systemd_base_slice,
            "dockerSocketPath": os.fspath(proof.config.docker_socket_path),
            "retainedInputMode": proof.config.retained_input_mode,
        },
    }
    config_path = tmp_path / "operator.json"
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    config_path.chmod(0o600)
    return config_path


def test_strict_config_preflights_signed_artifacts_and_injected_assembly(tmp_path: Path) -> None:
    from ksi_processing_controller.external_inspector_daemon import (
        build_daemon_from_operator_config,
    )
    from ksi_processing_controller.external_inspector_operator_config import (
        load_external_inspector_operator_config,
    )

    proof, _source = _proof_fixture(tmp_path / "proof")
    listener, listener_path, root = _activated_distinct_worker_listener(
        tmp_path, proof.config.worker_uid
    )
    config = load_external_inspector_operator_config(
        _signed_operator_config(tmp_path, proof=proof, listener_path=listener_path)
    )
    received: list[object] = []

    class _StartupProof:
        def __init__(self) -> None:
            self.started = False

        def verify_startup(self) -> None:
            self.started = True

        def prove(self, **kwargs: object) -> object:
            del kwargs
            raise AssertionError("injected builder must not create a runtime")

    startup_proof = _StartupProof()
    sentinel = object()

    def builder(**kwargs: object) -> object:
        received.append(kwargs)
        kwargs["activated_listener"].close()
        return sentinel

    try:
        original_fd3 = os.dup(3)
    except OSError:
        original_fd3 = -1
    try:
        os.dup2(listener.fileno(), 3)
        assembled = build_daemon_from_operator_config(
            config,
            host_proof=startup_proof,  # type: ignore[arg-type]
            daemon_builder=builder,  # type: ignore[arg-type]
            environment={"LISTEN_PID": str(os.getpid()), "LISTEN_FDS": "1"},
        )
    finally:
        if original_fd3 >= 0:
            os.dup2(original_fd3, 3)
            os.close(original_fd3)
        else:
            os.close(3)
        listener.close()
        shutil.rmtree(root)

    assert assembled is sentinel
    assert startup_proof.started is True
    assert len(received) == 1


def test_strict_config_rejects_nested_unknown_field_and_unsafe_bus_mode(tmp_path: Path) -> None:
    from ksi_processing_controller.external_inspector_operator_config import (
        OperatorConfigBlockedCode,
        OperatorConfigUnavailable,
        load_external_inspector_operator_config,
    )

    proof, _source = _proof_fixture(tmp_path / "proof")
    config_path = _signed_operator_config(
        tmp_path,
        proof=proof,
        listener_path=tmp_path / "listener.sock",
    )
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["production"]["systemdBus"]["unexpected"] = "value"
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    config_path.chmod(0o600)
    with pytest.raises(OperatorConfigUnavailable) as unknown:
        load_external_inspector_operator_config(config_path)
    assert unknown.value.code is OperatorConfigBlockedCode.UNKNOWN_FIELD

    del payload["production"]["systemdBus"]["unexpected"]
    payload["production"]["systemdBus"]["expectedMode"] = 0o666
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    config_path.chmod(0o600)
    with pytest.raises(OperatorConfigUnavailable) as unsafe:
        load_external_inspector_operator_config(config_path)
    assert unsafe.value.code is OperatorConfigBlockedCode.CONFIG_VALUE


def test_host_proof_rejects_stale_closed_docker_socket(tmp_path: Path) -> None:
    proof, _ = _proof_fixture(tmp_path)
    listener, thread = _LIVE_LISTENERS[proof.config.docker_socket_path]
    listener.close()
    thread.join(timeout=1)
    # The socket node persists but its listener is closed.
    with pytest.raises(RootlessDockerHostProofUnavailable):
        proof.verify_startup()


def test_host_proof_rejects_live_peer_with_wrong_daemon_pid(tmp_path: Path) -> None:
    proof, _ = _proof_fixture(tmp_path)
    configured_pid = os.getpid() + 100_000
    proc_root = tmp_path / "proc"
    original = proc_root / str(os.getpid())
    _write_proc_fixture(
        proc_root=proc_root,
        pid=configured_pid,
        uid=os.geteuid(),
        gid=os.getegid(),
        uid_map=(original / "uid_map").read_bytes(),
        gid_map=(original / "gid_map").read_bytes(),
        cgroup=proof.config.daemon_cgroup_path,
    )
    proof.config.rootless_daemon_pid_path.write_text(str(configured_pid))
    with pytest.raises(RootlessDockerHostProofUnavailable):
        proof.verify_startup()


def test_connected_peer_rechecks_pinned_start_time(tmp_path: Path) -> None:
    import time

    proof, _ = _proof_fixture(tmp_path)
    proof.verify_startup()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.connect(str(proof.config.docker_socket_path))
        proof.verify_connected(connection, deadline_monotonic=time.monotonic() + 1)
        path = tmp_path / "proc" / str(os.getpid()) / "stat"
        path.write_text(path.read_text().replace("101 ", "102 "))
        with pytest.raises(RootlessDockerHostProofUnavailable):
            proof.verify_connected(connection, deadline_monotonic=time.monotonic() + 1)
