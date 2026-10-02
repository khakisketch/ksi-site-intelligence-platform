"""Protected local launch configuration for the independent Analysis worker."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest


def _wire() -> dict[str, Any]:
    digest = "sha256:" + "0" * 64
    return {
        "version": "analysis-worker-config.v1",
        "core": {
            "baseUrl": "http://127.0.0.1:8080/core",
            "maximumResponseBytes": 262_144,
            "requestTimeoutSeconds": 5.0,
        },
        "worker": {"instanceId": "local-analysis-worker"},
        "runtime": {
            "workerExecutableDigest": digest,
            "workerBuildDigest": digest,
            "runtimeImageVersion": "local-test",
            "runtimeImageOciDigest": digest,
            "dependencyLockDigest": digest,
        },
        "objectTransport": {
            "endpoints": [{"origin": "http://127.0.0.1:8081", "addresses": ["127.0.0.1"]}],
            "maxHeaderBytes": 4096,
            "maxObjectBytes": 1_048_576,
            "maxChunkBytes": 65_536,
        },
        "runner": {"pollIntervalSeconds": 1.0},
    }


def _write(path: Path, wire: object | None = None, *, raw: bytes | None = None) -> Path:
    path.write_bytes(raw if raw is not None else json.dumps(wire or _wire()).encode())
    path.chmod(0o600)
    return path


def test_load_analysis_worker_config_builds_closed_runtime_and_transport(tmp_path: Path) -> None:
    from ksi_processing_controller.external_analysis_worker_config import (
        load_analysis_worker_config,
    )

    config = load_analysis_worker_config(str(_write(tmp_path / "worker.json")))

    assert config.core_base_url == "http://127.0.0.1:8080/core"
    assert config.worker_instance_id == "local-analysis-worker"
    assert config.runtime.runtime_image_version == "local-test"
    assert config.object_transport.endpoints[0].addresses == ("127.0.0.1",)
    assert config.poll_interval_seconds == 1.0


@pytest.mark.parametrize(
    "mutate",
    (
        lambda wire: wire.update(extra=True),
        lambda wire: wire["worker"].update(extra=True),
        lambda wire: wire["objectTransport"].update(maxChunkBytes=2_000_000),
        lambda wire: wire["core"].update(maximumResponseBytes=4_194_305),
        lambda wire: wire["runtime"].update(workerBuildDigest="not-a-digest"),
        lambda wire: wire["core"].update(baseUrl="https://core.example.test"),
        lambda wire: wire["runner"].update(pollIntervalSeconds=float("inf")),
        lambda wire: wire["core"].update(requestTimeoutSeconds=10**400),
        lambda wire: wire["runner"].update(pollIntervalSeconds=10**400),
        lambda wire: wire["objectTransport"]["endpoints"][0].update(
            origin="http://objects.example.test"
        ),
        lambda wire: wire["objectTransport"]["endpoints"][0].update(
            addresses=["object.example.test"]
        ),
    ),
)
def test_invalid_analysis_worker_config_fails_closed(tmp_path: Path, mutate: Any) -> None:
    from ksi_processing_controller.external_analysis_worker_config import (
        AnalysisWorkerConfigUnavailable,
        load_analysis_worker_config,
    )

    wire = _wire()
    mutate(wire)
    with pytest.raises(AnalysisWorkerConfigUnavailable):
        load_analysis_worker_config(str(_write(tmp_path / "worker.json", wire)))


def test_config_rejects_symlink_wrong_mode_and_non_absolute_path(tmp_path: Path) -> None:
    from ksi_processing_controller.external_analysis_worker_config import (
        AnalysisWorkerConfigUnavailable,
        load_analysis_worker_config,
    )

    actual = _write(tmp_path / "actual.json")
    link = tmp_path / "link.json"
    link.symlink_to(actual)
    with pytest.raises(AnalysisWorkerConfigUnavailable):
        load_analysis_worker_config(str(link))

    actual.chmod(0o640)
    with pytest.raises(AnalysisWorkerConfigUnavailable):
        load_analysis_worker_config(str(actual))
    with pytest.raises(AnalysisWorkerConfigUnavailable):
        load_analysis_worker_config("relative.json")

    writable_parent = tmp_path / "writable"
    writable_parent.mkdir(mode=0o777)
    writable_parent.chmod(0o777)
    unsafe = _write(writable_parent / "worker.json")
    with pytest.raises(AnalysisWorkerConfigUnavailable):
        load_analysis_worker_config(str(unsafe))


def test_config_rejects_oversize_and_duplicate_json_keys(tmp_path: Path) -> None:
    from ksi_processing_controller.external_analysis_worker_config import (
        AnalysisWorkerConfigUnavailable,
        load_analysis_worker_config,
    )

    oversized = _write(tmp_path / "oversized.json", raw=b" " * (64 * 1024 + 1))
    duplicate = _write(tmp_path / "duplicate.json", raw=b'{"version":"a","version":"b"}')
    for path in (oversized, duplicate):
        with pytest.raises(AnalysisWorkerConfigUnavailable):
            load_analysis_worker_config(str(path))


def test_config_rejects_wrong_owner_or_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ksi_processing_controller.external_analysis_worker_config import (
        AnalysisWorkerConfigUnavailable,
        load_analysis_worker_config,
    )

    path = _write(tmp_path / "worker.json")
    real_geteuid = os.geteuid
    monkeypatch.setattr(os, "geteuid", lambda: real_geteuid() + 1)
    with pytest.raises(AnalysisWorkerConfigUnavailable):
        load_analysis_worker_config(str(path))


def test_config_rejects_wrong_group(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ksi_processing_controller.external_analysis_worker_config import (
        AnalysisWorkerConfigUnavailable,
        load_analysis_worker_config,
    )

    path = _write(tmp_path / "worker.json")
    real_getegid = os.getegid
    monkeypatch.setattr(os, "getegid", lambda: real_getegid() + 1)
    with pytest.raises(AnalysisWorkerConfigUnavailable):
        load_analysis_worker_config(str(path))


def test_config_rejects_hard_link(tmp_path: Path) -> None:
    from ksi_processing_controller.external_analysis_worker_config import (
        AnalysisWorkerConfigUnavailable,
        load_analysis_worker_config,
    )

    path = _write(tmp_path / "worker.json")
    (tmp_path / "alias.json").hardlink_to(path)
    with pytest.raises(AnalysisWorkerConfigUnavailable):
        load_analysis_worker_config(str(path))


def test_runner_config_validation_precedes_client_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ksi_processing_controller.external_analysis_runner as runner

    path = _write(tmp_path / "invalid.json", {**_wire(), "unexpected": True})
    token = _write(tmp_path / "token", raw=b"worker-secret\n")
    constructed: list[object] = []
    token_reads: list[object] = []
    monkeypatch.setattr(
        runner,
        "ExternalAnalysisCoreClient",
        lambda **kwargs: constructed.append(kwargs),
    )
    monkeypatch.setattr(runner, "_worker_token_file", lambda value: token_reads.append(value))

    assert runner.main(("--config", str(path), "--worker-token-file", str(token), "--once")) == 2
    assert constructed == []
    assert token_reads == []


def test_analysis_runner_rejects_symlinked_token_parent(tmp_path: Path) -> None:
    import ksi_processing_controller.external_analysis_runner as runner

    actual_parent = tmp_path / "protected"
    actual_parent.mkdir(mode=0o700)
    token_path = _write(actual_parent / "token", raw=b"local-worker-token\n")
    linked_parent = tmp_path / "linked"
    linked_parent.symlink_to(actual_parent, target_is_directory=True)

    with pytest.raises(ValueError, match="^worker token file is invalid$"):
        runner._worker_token_file(str(linked_parent / token_path.name))


def test_analysis_runner_rejects_writable_token_parent(tmp_path: Path) -> None:
    import ksi_processing_controller.external_analysis_runner as runner

    writable_parent = tmp_path / "writable"
    writable_parent.mkdir(mode=0o700)
    writable_parent.chmod(0o777)
    token_path = _write(writable_parent / "token", raw=b"local-worker-token\n")

    with pytest.raises(ValueError, match="^worker token file is invalid$"):
        runner._worker_token_file(str(token_path))


@pytest.mark.parametrize("identity", ("uid", "gid"))
def test_analysis_runner_rejects_token_file_with_wrong_owner_or_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, identity: str
) -> None:
    import ksi_processing_controller.external_analysis_runner as runner

    token_path = _write(tmp_path / "token", raw=b"local-worker-token\n")
    real_identity = os.geteuid if identity == "uid" else os.getegid
    name = "geteuid" if identity == "uid" else "getegid"
    monkeypatch.setattr(os, name, lambda: real_identity() + 1)

    with pytest.raises(ValueError, match="^worker token file is invalid$"):
        runner._worker_token_file(str(token_path))


def test_analysis_runner_rejects_hard_linked_token_file(tmp_path: Path) -> None:
    import ksi_processing_controller.external_analysis_runner as runner

    token_path = _write(tmp_path / "token", raw=b"local-worker-token\n")
    (tmp_path / "token-alias").hardlink_to(token_path)

    with pytest.raises(ValueError, match="^worker token file is invalid$"):
        runner._worker_token_file(str(token_path))


def test_runner_huge_timeout_rejects_without_client_or_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ksi_processing_controller.external_analysis_runner as runner

    wire = _wire()
    wire["core"]["requestTimeoutSeconds"] = 10**400
    path = _write(tmp_path / "huge-timeout.json", wire)
    token = _write(tmp_path / "token", raw=b"worker-secret\n")
    constructed: list[object] = []
    monkeypatch.setattr(
        runner,
        "ExternalAnalysisCoreClient",
        lambda **kwargs: constructed.append(kwargs),
    )

    assert runner.main(("--config", str(path), "--worker-token-file", str(token), "--once")) == 2
    assert constructed == []


def test_runner_config_uses_separate_private_token_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ksi_processing_controller.external_analysis_runner as runner

    path = _write(tmp_path / "worker.json")
    token_path = _write(tmp_path / "token", raw=b"separate-worker-token\n")
    captured: dict[str, object] = {}

    class Client:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def __enter__(self) -> Client:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(runner, "ExternalAnalysisCoreClient", Client)
    monkeypatch.setattr(runner, "run_once", lambda *_args: True)

    assert (
        runner.main(("--config", str(path), "--worker-token-file", str(token_path), "--once")) == 0
    )
    assert captured["worker_token"] == "separate-worker-token"
    assert captured["base_url"] == "http://127.0.0.1:8080/core"
    assert "worker_token" not in json.loads(path.read_text())
