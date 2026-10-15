"""Task 5c host enforcement cases — executed against the approved sandbox host.

These cases are the decisive host-backed selection for the external
inspector/measurement rootless profile.  They drive
``tools/task5c_host_enforcement_verify.py`` on the approved host (over SSH as
its launcher user) and assert the recorded proofs: transient-slice lifecycle,
cgroup accounting/controls, Engine ``CgroupParent`` mapping, container
confinement probes, and the exact removal/StopUnit ordering.

Configuration (all optional; absent configuration skips with an explicit
reason instead of fabricating a host result):

  KSI_TASK5C_HOST       ssh target, e.g. ``ubuntu@127.0.0.1:2223``
  KSI_TASK5C_KEY        path to the ssh private key
  KSI_TASK5C_REMOTE_USER  launcher user on the host (default ``ksi-inspector``)
  KSI_TASK5C_REMOTE_UID   its uid (default ``997``)
  KSI_TASK5C_REMOTE_PYTHON  runtime python (default
                        ``/srv/ksi-data-sandbox/runtime/venv/bin/python``)

A skip here is NOT acceptance: the profile's host-enforcement gate passes only
with a recorded run in which every proof line below executes and passes.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

_HOST = os.environ.get("KSI_TASK5C_HOST")
_KEY = os.environ.get("KSI_TASK5C_KEY")
_REMOTE_USER = os.environ.get("KSI_TASK5C_REMOTE_USER", "ksi-inspector")
_REMOTE_UID = os.environ.get("KSI_TASK5C_REMOTE_UID", "997")
_REMOTE_PYTHON = os.environ.get(
    "KSI_TASK5C_REMOTE_PYTHON", "/srv/ksi-data-sandbox/runtime/venv/bin/python"
)
_TOOL = Path(__file__).resolve().parents[2] / "tools" / "task5c_host_enforcement_verify.py"

pytestmark = pytest.mark.skipif(
    not (_HOST and _KEY),
    reason=(
        "approved sandbox host is not configured (KSI_TASK5C_HOST/KSI_TASK5C_KEY); "
        "host enforcement remains NOT_VERIFIED in this environment"
    ),
)


def _ssh_argv(remote_command: str) -> list[str]:
    target, _, port = (_HOST or "").partition(":")
    base = [
        "ssh",
        "-i",
        _KEY or "",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=8",
    ]
    if port:
        base += ["-p", port]
    return [*base, target, remote_command]


@pytest.fixture(scope="module")
def host_report() -> str:
    scp = [
        "scp",
        "-i",
        _KEY or "",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "BatchMode=yes",
    ]
    target, _, port = (_HOST or "").partition(":")
    if port:
        scp += ["-P", port]
    scp += [str(_TOOL), f"{target}:/tmp/task5c_host_enforcement_verify.py"]
    upload = subprocess.run(scp, capture_output=True, text=True, timeout=120)
    assert upload.returncode == 0, upload.stderr[-400:]

    remote = (
        f"sudo -u {_REMOTE_USER} env "
        f"XDG_RUNTIME_DIR=/run/user/{_REMOTE_UID} "
        f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{_REMOTE_UID}/bus "
        f"{_REMOTE_PYTHON} /tmp/task5c_host_enforcement_verify.py"
    )
    run = subprocess.run(_ssh_argv(remote), capture_output=True, text=True, timeout=420)
    combined = run.stdout + run.stderr
    assert "HARNESS OK" in combined, combined[-1200:]
    return combined


def _proof_lines(report: str, prefixes: tuple[str, ...]) -> list[str]:
    return [
        line
        for line in report.splitlines()
        if line.startswith(prefixes)
    ]


def _require_proofs(report: str, prefixes: tuple[str, ...], expected: int) -> None:
    lines = _proof_lines(report, prefixes)
    assert len(lines) >= expected, f"missing proofs for {prefixes}: {lines}"
    failures = [line for line in lines if line.startswith("FAIL")]
    assert not failures, failures
    assert not [line for line in report.splitlines() if line.startswith("FAIL")]


def test_host_transient_slice_lifecycle(host_report: str) -> None:
    """StartTransientUnit(mode=fail), duplicate rejection, unit identity, StopUnit."""
    _require_proofs(
        host_report,
        ("PASS  P1", "PASS  P2", "PASS  P7"),
        4,
    )


def test_host_cgroup_accounting_and_fixed_controls(host_report: str) -> None:
    """Controllers, fresh CPU accounting, cpu.weight and populated transitions."""
    _require_proofs(host_report, ("PASS  P3", "PASS  P5", "PASS  P6"), 5)


def test_host_engine_cgroup_parent_maps_container_under_attempt_slice(
    host_report: str,
) -> None:
    """The Engine places the container's cgroup strictly under the attempt slice."""
    _require_proofs(host_report, ("PASS  P4",), 1)


def test_host_container_confinement_probes(host_report: str) -> None:
    """UID mapping, read-only rootfs denial, no-network denial, workspace ownership."""
    _require_proofs(host_report, ("PASS  P8", "PASS  P9", "PASS  P10"), 10)


def test_host_stable_cpu_before_exact_removal(host_report: str) -> None:
    """Two stable CPU reads precede the exact Docker removal."""
    _require_proofs(host_report, ("PASS  P12",), 2)


def test_host_bounded_kill_latency(host_report: str) -> None:
    """An exact Engine kill empties the attempt-slice cgroup within the bound."""
    _require_proofs(host_report, ("PASS  P13",), 6)
