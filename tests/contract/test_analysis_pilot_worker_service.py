"""Static contract for the opt-in dedicated Analysis system service candidate."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UNIT_PATH = ROOT / "deploy/analysis-pilot/systemd/ksi-analysis-worker.service"
README_PATH = ROOT / "deploy/analysis-pilot/README.md"


def _unit() -> str:
    return UNIT_PATH.read_text(encoding="utf-8")


def test_analysis_worker_service_uses_dedicated_identity_and_protected_cli() -> None:
    unit = _unit()

    assert "Type=exec" in unit
    assert "User=ksi-analysis" in unit
    assert "Group=ksi-analysis" in unit
    assert "SupplementaryGroups=" not in unit
    assert (
        "ExecStart=/opt/ksi-analysis/venv/bin/ksi-external-analysis-worker "
        "--config /etc/ksi-analysis/config.json "
        "--worker-token-file /etc/ksi-analysis/worker.token"
    ) in unit
    assert "UMask=0077" in unit
    assert "EnvironmentFile=" not in unit
    assert "worker.token" not in " ".join(
        line for line in unit.splitlines() if line.startswith("Environment=")
    )


def test_analysis_worker_service_is_read_only_except_private_measurement_tmp() -> None:
    unit = _unit()

    for directive in (
        "NoNewPrivileges=yes",
        "ProtectSystem=strict",
        "ProtectHome=yes",
        "PrivateTmp=yes",
        "PrivateDevices=yes",
        "ProtectKernelTunables=yes",
        "ProtectKernelModules=yes",
        "ProtectControlGroups=yes",
        "ProtectKernelLogs=yes",
        "ProtectClock=yes",
        "ProtectHostname=yes",
        "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6",
        "CapabilityBoundingSet=",
        "AmbientCapabilities=",
        "LockPersonality=yes",
        "MemoryDenyWriteExecute=yes",
        "RestrictNamespaces=yes",
        "RestrictRealtime=yes",
        "RestrictSUIDSGID=yes",
        "SystemCallArchitectures=native",
        "SystemCallFilter=@system-service",
        "ReadOnlyPaths=/opt/ksi-analysis",
        "/etc/ksi-analysis/config.json",
        "/etc/ksi-analysis/worker.token",
    ):
        assert directive in unit

    assert "ReadWritePaths=" not in unit
    assert "StateDirectory=" not in unit
    assert "RuntimeDirectory=" not in unit
    assert "IPAddressDeny=any" in unit
    assert "IPAddressAllow=127.0.0.1/32 ::1/128" in unit


def test_analysis_worker_service_has_no_listener_or_public_network_allowance() -> None:
    unit = _unit()

    assert not any(line.startswith("Listen") for line in unit.splitlines())
    assert "IPAddressAllow=any" not in unit
    assert "0.0.0.0" not in unit
    assert "::/0" not in unit
    assert "RestartPreventExitStatus=2" in unit


def test_analysis_pilot_readme_documents_host_checks_and_non_deployment_status() -> None:
    readme = README_PATH.read_text(encoding="utf-8")

    for expected in (
        "PREPARATION CANDIDATE; NOT DEPLOYED",
        "ksi-analysis",
        "docker",
        "immutable",
        "runtime image digest",
        "AnalysisActivationV1",
        "restart",
        "journalctl",
        "backup",
        "rollback",
        "Tailnet",
        "customer OIDC",
        "public listener",
        "every parent path component",
    ):
        assert expected.casefold() in readme.casefold()
