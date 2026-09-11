"""Executable contract for the private external-runtime application sockets."""

from __future__ import annotations

import os
import pwd
import socket
import struct
import subprocess
import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from ksi_processing_controller.external_listener_peer_probe import respond_to_listener_peer_probe

_ROOT = Path(__file__).resolve().parents[2]
_HELPER = (
    _ROOT
    / "deploy"
    / "external-runtime"
    / "systemd"
    / "bin"
    / "ksi-external-runtime-socket-acl"
)


def _access_acl(path: Path) -> str:
    return subprocess.check_output(
        ["getfacl", "--absolute-names", "--omit-header", "--access", str(path)],
        text=True,
    ).strip()


def _expected_parent_acl() -> str:
    return "user::rwx\nuser:nobody:--x\ngroup::---\nmask::--x\nother::---"


def _expected_pristine_socket_acl() -> str:
    return "user::rw-\ngroup::---\nother::---"


def _expected_active_socket_acl() -> str:
    return "user::rw-\nuser:nobody:rw-\ngroup::---\nmask::rw-\nother::---"


def _candidate(tmp_path: Path) -> tuple[Path, Path, Path, list[socket.socket], dict[str, str]]:
    parent = tmp_path / "launcher"
    parent.mkdir(mode=0o700)
    inspection = parent / "inspection.sock"
    measurement = parent / "measurement.sock"
    listeners = [socket.socket(socket.AF_UNIX), socket.socket(socket.AF_UNIX)]
    listeners[0].bind(os.fspath(inspection))
    listeners[1].bind(os.fspath(measurement))
    inspection.chmod(0o600)
    measurement.chmod(0o600)
    parent.chmod(0o710)
    subprocess.check_call(["setfacl", "--remove-all", str(parent)])
    subprocess.check_call(["setfacl", "--remove-default", str(parent)])
    subprocess.check_call(
        ["setfacl", "--modify", "g::---,u:nobody:--x,m::--x", str(parent)]
    )
    env = {
        **os.environ,
        "KSI_EXTERNAL_RUNTIME_SOCKET_ACL_LIBRARY_ONLY": "1",
        "KSI_EXTERNAL_RUNTIME_SOCKET_ACL_PARENT": str(parent),
        "KSI_EXTERNAL_RUNTIME_SOCKET_ACL_RUNTIME_ROOT": str(tmp_path),
        "KSI_EXTERNAL_RUNTIME_SOCKET_ACL_INSPECTION_SOCKET": str(inspection),
        "KSI_EXTERNAL_RUNTIME_SOCKET_ACL_MEASUREMENT_SOCKET": str(measurement),
        "KSI_EXTERNAL_RUNTIME_SOCKET_ACL_OWNER": pwd.getpwuid(os.getuid()).pw_name,
        "KSI_EXTERNAL_RUNTIME_SOCKET_ACL_VALIDATOR": "nobody",
        "KSI_EXTERNAL_RUNTIME_SOCKET_ACL_TRUSTED_OWNER_UID": str(os.getuid()),
    }
    return parent, inspection, measurement, listeners, env


def _run_acl(env: dict[str, str], shell: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", 'source "$1"; ' + shell, "bash", str(_HELPER)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_acl_activation_grants_only_the_named_validator_the_two_socket_lanes(
    tmp_path: Path,
) -> None:
    """Missing named ACLs or group access must make this exact policy fail."""
    parent, inspection, measurement, listeners, env = _candidate(tmp_path)
    try:
        result = _run_acl(env, "activate_socket_acls; verify_acl_shapes")
    finally:
        for listener in listeners:
            listener.close()

    assert result.returncode == 0, result.stderr
    assert _access_acl(parent) == _expected_parent_acl()
    assert _access_acl(inspection) == _expected_active_socket_acl()
    assert _access_acl(measurement) == _expected_active_socket_acl()
    parent.chmod(0o700)
    subprocess.check_call(["setfacl", "--remove-all", str(parent)])


def test_acl_activation_accepts_a_mixed_recovered_state_and_normalizes_both(tmp_path: Path) -> None:
    """A restart between socket activations must converge, not block deployment forever."""
    _parent, inspection, measurement, listeners, env = _candidate(tmp_path)
    subprocess.check_call(["setfacl", "--modify", "u:nobody:rw-,m::rw-", str(inspection)])
    try:
        result = _run_acl(env, "activate_socket_acls; verify_acl_shapes")
    finally:
        for listener in listeners:
            listener.close()

    assert result.returncode == 0, result.stderr
    assert _access_acl(inspection) == _expected_active_socket_acl()
    assert _access_acl(measurement) == _expected_active_socket_acl()


def test_acl_activation_rejects_a_symlinked_socket_before_freezing_the_parent(
    tmp_path: Path,
) -> None:
    """A substituted path must never be granted the validator ACL."""
    parent, inspection, measurement, listeners, env = _candidate(tmp_path)
    inspection.unlink()
    inspection.symlink_to(measurement)
    try:
        result = _run_acl(env, "if activate_socket_acls; then exit 92; fi")
    finally:
        for listener in listeners:
            listener.close()

    assert result.returncode == 0, result.stderr
    assert _access_acl(parent) == _expected_parent_acl()


def test_access_proof_uses_an_actual_unix_connect_probe(tmp_path: Path) -> None:
    """A permission-bit check cannot substitute for a real socket connection."""
    path = tmp_path / "probe.sock"
    listener = socket.socket(socket.AF_UNIX)
    listener.bind(os.fspath(path))
    listener.listen()
    try:
        result = subprocess.run(
            [
                "bash",
                "-c",
                'source "$1"; run_as() { shift; "$@"; }; connect_as ignored "$2"',
                "bash",
                str(_HELPER),
                str(path),
            ],
            env={
                **os.environ,
                "KSI_EXTERNAL_RUNTIME_SOCKET_ACL_LIBRARY_ONLY": "1",
                "KSI_EXTERNAL_RUNTIME_SOCKET_ACL_PARENT": str(tmp_path),
                "KSI_EXTERNAL_RUNTIME_SOCKET_ACL_RUNTIME_ROOT": str(tmp_path),
                "KSI_EXTERNAL_RUNTIME_SOCKET_ACL_INSPECTION_SOCKET": str(path),
                "KSI_EXTERNAL_RUNTIME_SOCKET_ACL_MEASUREMENT_SOCKET": str(path),
                "KSI_EXTERNAL_RUNTIME_SOCKET_ACL_OWNER": pwd.getpwuid(os.getuid()).pw_name,
                "KSI_EXTERNAL_RUNTIME_SOCKET_ACL_VALIDATOR": "nobody",
                "KSI_EXTERNAL_RUNTIME_SOCKET_ACL_TRUSTED_OWNER_UID": str(os.getuid()),
            },
            text=True,
            capture_output=True,
            check=False,
        )
    finally:
        listener.close()

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(("lane", "socket_index"), [("INSPECTION", 0), ("MEASUREMENT", 1)])
def test_acl_helper_requires_a_fresh_server_peer_credential_receipt(
    tmp_path: Path, lane: str, socket_index: int
) -> None:
    """A successful connect alone is insufficient: both kernel observations must round-trip."""
    parent, inspection, measurement, listeners, env = _candidate(tmp_path)
    probe_socket = (inspection, measurement)[socket_index]
    listeners[socket_index].listen(1)
    listeners[socket_index].settimeout(2)
    errors: list[BaseException] = []

    def serve() -> None:
        try:
            connection, _address = listeners[socket_index].accept()
            with connection:
                assert respond_to_listener_peer_probe(
                    connection,
                    lane=lane,
                    socket_path=probe_socket,
                    expected_worker_uid=os.geteuid(),
                    expected_server_uid=os.geteuid(),
                    expected_server_gid=os.getegid(),
                    deadline_monotonic=time.monotonic() + 1,
                )
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=serve)
    thread.start()
    try:
        result = _run_acl(
            env,
            f'''run_as() {{ shift; "$@"; }}
launcher_uid={os.geteuid()}
launcher_gid={os.getegid()}
require_peer_receipt {lane} "{probe_socket}"''',
        )
    finally:
        for listener in listeners:
            listener.close()
        thread.join(timeout=3)
        assert not thread.is_alive(), "peer fixture thread did not terminate"
        parent.chmod(0o700)
        subprocess.check_call(["setfacl", "--remove-all", str(parent)])

    assert result.returncode == 0, result.stderr
    assert errors == []


def test_acl_access_proof_fails_when_one_of_two_receipts_is_missing_despite_permission_denials(
) -> None:
    """Both exact socket receipts are required; connect permission alone is insufficient."""
    if os.geteuid() != 0:
        pytest.skip("verify_runtime_access requires root to exercise distinct account denials")
    untrusted = next(
        account
        for account in pwd.getpwall()
        if account.pw_uid not in {os.getuid(), pwd.getpwnam("nobody").pw_uid}
    )
    # Never loosen pytest's private root ancestor. Only this owned fixture is traversable.
    with TemporaryDirectory(prefix="ksi-peer-denial-test-", dir="/tmp") as owned:
        fixture = Path(owned)
        fixture.chmod(0o755)
        _assert_missing_peer_receipt(fixture, untrusted.pw_name)


def _assert_missing_peer_receipt(tmp_path: Path, untrusted_account: str) -> None:
    parent, inspection, measurement, listeners, env = _candidate(tmp_path)
    listeners[0].listen(1)
    listeners[0].settimeout(2)
    listeners[1].listen(1)
    errors: list[BaseException] = []

    def inspection_server() -> None:
        try:
            connection, _address = listeners[0].accept()
            with connection:
                assert respond_to_listener_peer_probe(
                    connection,
                    lane="INSPECTION",
                    socket_path=inspection,
                    expected_worker_uid=pwd.getpwnam("nobody").pw_uid,
                    expected_server_uid=os.geteuid(),
                    expected_server_gid=os.getegid(),
                    deadline_monotonic=time.monotonic() + 2,
                )
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=inspection_server)
    thread.start()
    try:
        result = _run_acl(
            env,
            f'''activate_socket_acls
launcher_uid={os.geteuid()}
launcher_gid={os.getegid()}
eval "$(declare -f require_connect_denied | sed '1s/require_connect_denied/record_connect_denied/')"
denial_checks=0
require_connect_denied() {{ record_connect_denied "$@"; denial_checks=$((denial_checks + 1)); }}
if verify_runtime_access {untrusted_account}; then exit 91; fi
[[ "$denial_checks" -ge 2 ]]''',
        )
    finally:
        for listener in listeners:
            listener.close()
        thread.join(timeout=3)
        parent.chmod(0o700)
        subprocess.check_call(["setfacl", "--remove-all", str(parent)])

    assert not thread.is_alive(), "peer fixture thread did not terminate"
    assert result.returncode == 0, result.stderr
    assert errors == []


def test_acl_helper_peer_probe_uses_one_absolute_deadline_when_server_dribbles_response(
    tmp_path: Path,
) -> None:
    """A slow peer cannot reset the helper's one-second response budget per byte."""
    parent, path, _measurement, listeners, env = _candidate(tmp_path)
    listener = listeners[0]
    listener.listen(1)
    listener.settimeout(2)
    errors: list[BaseException] = []

    def server() -> None:
        try:
            connection, address = listener.accept()
            with connection:
                assert isinstance(address, bytes)
                challenge = address[-24:]
                payload = (
                    b"KSI-PEER-RECEIPT-v1\x00"
                    + challenge
                    + struct.pack("3i", os.getpid(), os.geteuid(), os.getegid())
                )
                for byte in payload[:6]:
                    connection.sendall(bytes([byte]))
                    time.sleep(0.24)
                time.sleep(0.65)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=server)
    thread.start()
    started = time.monotonic()
    try:
        result = _run_acl(
            {**env, "PROBE_SOCKET": str(path)},
            f'''run_as() {{ shift; "$@"; }}
launcher_uid={os.geteuid()}
launcher_gid={os.getegid()}
if require_peer_receipt INSPECTION "$PROBE_SOCKET"; then exit 92; fi''',
        )
    finally:
        elapsed = time.monotonic() - started
        for candidate in listeners:
            candidate.close()
        thread.join(timeout=3)
        assert not thread.is_alive(), "peer fixture thread did not terminate"
        parent.chmod(0o700)
        subprocess.check_call(["setfacl", "--remove-all", str(parent)])

    assert result.returncode == 0, result.stderr
    assert elapsed < 1.75
    assert errors == []


@pytest.mark.parametrize("state", ["missing", "refused", "allowed", "denied", "timeout"])
def test_denial_proof_requires_an_actual_permission_error(tmp_path: Path, state: str) -> None:
    """A dead/missing listener or successful connection cannot prove isolation."""
    if state == "denied" and os.geteuid() == 0:
        pytest.skip("root bypasses the fixture's DAC permissions")
    _parent, inspection, _measurement, listeners, env = _candidate(tmp_path)
    pending = None
    try:
        path = inspection
        if state == "missing":
            path = inspection.with_name("absent.sock")
        elif state in ("allowed", "denied"):
            listeners[0].listen()
            if state == "denied":
                inspection.chmod(0)
        elif state == "timeout":
            listeners[0].listen(0)
            pending = socket.socket(socket.AF_UNIX)
            pending.settimeout(1)
            pending.connect(str(inspection))
        env["PROBE_SOCKET"] = str(path)
        result = _run_acl(
            env,
            'run_as() { shift; "$@"; }; require_connect_denied ignored "$PROBE_SOCKET"',
        )
    finally:
        if pending is not None:
            pending.close()
        for listener in listeners:
            listener.close()
    assert (result.returncode == 0) is (state == "denied"), result.stderr


@pytest.mark.parametrize("failure", [1, 13, 124, 127])
def test_probe_execution_failure_is_not_permission_denial(tmp_path: Path, failure: int) -> None:
    """Missing Python/runuser, timeout or bare exit code cannot prove kernel denial."""
    _parent, _inspection, _measurement, listeners, env = _candidate(tmp_path)
    try:
        result = _run_acl(
            env,
            f'run_as() {{ return {failure}; }}; require_connect_denied ignored ignored',
        )
    finally:
        for listener in listeners:
            listener.close()
    assert result.returncode != 0


def test_acl_activation_rolls_back_after_the_second_socket_mutation_fails(tmp_path: Path) -> None:
    """A partial ACL write must restore the exact safe starting state."""
    parent, inspection, measurement, listeners, env = _candidate(tmp_path)
    try:
        result = _run_acl(
            env,
            r'''calls=0
apply_active_acl() {
  calls=$((calls + 1))
  [[ "$calls" -eq 2 ]] && return 71
  /usr/bin/setfacl --modify "u:${validator_account}:rw-,m::rw-" -- "$1"
}
if activate_socket_acls; then exit 90; fi
[[ "$(access_acl "$parent_dir")" == "$(expected_parent_acl)" ]]
[[ "$(access_acl "$inspection_socket")" == "$(expected_pristine_socket_acl)" ]]
[[ "$(access_acl "$measurement_socket")" == "$(expected_pristine_socket_acl)" ]]
''',
        )
    finally:
        for listener in listeners:
            listener.close()

    assert result.returncode == 0, result.stderr
    assert _access_acl(parent) == _expected_parent_acl()
    assert _access_acl(inspection) == _expected_pristine_socket_acl()
    assert _access_acl(measurement) == _expected_pristine_socket_acl()


def test_acl_activation_freezes_the_launcher_before_any_acl_write(tmp_path: Path) -> None:
    """The launcher UID must be unable to replace a socket during mutation."""
    _parent, _inspection, _measurement, listeners, env = _candidate(tmp_path)
    marker = tmp_path / "rename-result"
    env["KSI_EXTERNAL_RUNTIME_SOCKET_ACL_TEST_MARKER"] = str(marker)
    try:
        result = _run_acl(
            env,
            r'''after_parent_frozen() {
  if /usr/bin/mv -- "$measurement_socket" "${measurement_socket}.replaced"; then
    printf 'RENAME_ALLOWED\n' >"$KSI_EXTERNAL_RUNTIME_SOCKET_ACL_TEST_MARKER"
    return 97
  fi
  printf 'RENAME_DENIED\n' >"$KSI_EXTERNAL_RUNTIME_SOCKET_ACL_TEST_MARKER"
}
activate_socket_acls''',
        )
    finally:
        for listener in listeners:
            listener.close()

    assert result.returncode == 0, result.stderr
    assert marker.read_text(encoding="utf-8") == "RENAME_DENIED\n"


def test_acl_activation_detects_a_recreated_socket_and_a_rerun_recovers(tmp_path: Path) -> None:
    """A root-equivalent replacement during the freeze is rejected, then recoverable."""
    parent, inspection, measurement, listeners, env = _candidate(tmp_path)
    marker = tmp_path / "replacement"
    env["KSI_EXTERNAL_RUNTIME_SOCKET_ACL_TEST_MARKER"] = str(marker)
    try:
        result = _run_acl(
            env,
            r'''before_promote_second() {
  /usr/bin/setfacl --modify u::rwx -- "$parent_dir"
  /usr/bin/python3 -c 'import os, sys; os.unlink(sys.argv[1])' "$measurement_socket"
  /usr/bin/python3 -c 'import socket, sys
listener = socket.socket(socket.AF_UNIX)
listener.bind(sys.argv[1])
listener.close()' "$measurement_socket"
  /usr/bin/chmod 0600 -- "$measurement_socket"
  /usr/bin/setfacl --modify u::r-x -- "$parent_dir"
  printf 'REPLACED\n' >"$KSI_EXTERNAL_RUNTIME_SOCKET_ACL_TEST_MARKER"
}
if activate_socket_acls; then exit 91; fi
[[ "$(access_acl "$inspection_socket")" == "$(expected_pristine_socket_acl)" ]]
[[ "$(access_acl "$measurement_socket")" == "$(expected_pristine_socket_acl)" ]]
unset -f before_promote_second
activate_socket_acls; verify_acl_shapes''',
        )
    finally:
        for listener in listeners:
            listener.close()

    assert result.returncode == 0, result.stderr
    assert marker.read_text(encoding="utf-8") == "REPLACED\n"
    assert _access_acl(parent) == _expected_parent_acl()
    assert _access_acl(inspection) == _expected_active_socket_acl()
    assert _access_acl(measurement) == _expected_active_socket_acl()
    parent.chmod(0o700)
    subprocess.check_call(["setfacl", "--remove-all", str(parent)])


def test_acl_reader_normalizes_getfacl_effective_annotations(tmp_path: Path) -> None:
    """A narrower mask must not make an exact production ACL comparison fail."""
    validator = pwd.getpwnam("nobody")
    masked = next(
        account
        for account in pwd.getpwall()
        if account.pw_uid not in {os.getuid(), validator.pw_uid}
    )
    parent = tmp_path / "production-parent"
    parent.mkdir(mode=0o700)
    subprocess.check_call(
        [
            "setfacl",
            "--set",
            f"u::rwx,u:{masked.pw_name}:r-x,u:{validator.pw_name}:--x,g::---,m::--x,o::---",
            str(parent),
        ]
    )

    result = _run_acl(
        {
            **os.environ,
            "KSI_EXTERNAL_RUNTIME_SOCKET_ACL_LIBRARY_ONLY": "1",
            "KSI_EXTERNAL_RUNTIME_SOCKET_ACL_PARENT": str(parent),
            "KSI_EXTERNAL_RUNTIME_SOCKET_ACL_RUNTIME_ROOT": str(tmp_path),
            "KSI_EXTERNAL_RUNTIME_SOCKET_ACL_INSPECTION_SOCKET": str(parent / "inspection.sock"),
            "KSI_EXTERNAL_RUNTIME_SOCKET_ACL_MEASUREMENT_SOCKET": str(parent / "measurement.sock"),
            "KSI_EXTERNAL_RUNTIME_SOCKET_ACL_OWNER": pwd.getpwuid(os.getuid()).pw_name,
            "KSI_EXTERNAL_RUNTIME_SOCKET_ACL_VALIDATOR": "nobody",
            "KSI_EXTERNAL_RUNTIME_SOCKET_ACL_TRUSTED_OWNER_UID": str(os.getuid()),
        },
        f'access_acl "{parent}"',
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == (
        "user::rwx\n"
        f"user:{masked.pw_name}:r-x\n"
        f"user:{validator.pw_name}:--x\n"
        "group::---\n"
        "mask::--x\n"
        "other::---"
    )


def test_acl_activation_revokes_socket_grants_when_parent_restore_fails(tmp_path: Path) -> None:
    """A failed parent restoration must not leave validator socket access granted."""
    parent, inspection, measurement, listeners, env = _candidate(tmp_path)
    try:
        result = _run_acl(
            env,
            r'''restore_parent() { return 73; }
if activate_socket_acls; then exit 90; fi
[[ "$(access_acl "$inspection_socket")" == "$(expected_pristine_socket_acl)" ]]
[[ "$(access_acl "$measurement_socket")" == "$(expected_pristine_socket_acl)" ]]
''',
        )
    finally:
        parent.chmod(0o700)
        subprocess.check_call(["setfacl", "--remove-all", str(parent)])
        for listener in listeners:
            listener.close()

    assert result.returncode == 0, result.stderr
    assert _access_acl(inspection) == _expected_pristine_socket_acl()
    assert _access_acl(measurement) == _expected_pristine_socket_acl()


def test_acl_activation_rolls_back_when_signalled_during_parent_freeze(tmp_path: Path) -> None:
    """A signal in the first mutation window must restore the exact initial ACLs."""
    parent, inspection, measurement, listeners, env = _candidate(tmp_path)
    try:
        result = _run_acl(
            env,
            r'''after_parent_frozen() { kill -TERM $$; }
activate_socket_acls
''',
        )
    finally:
        for listener in listeners:
            listener.close()

    assert result.returncode != 0
    assert _access_acl(parent) == _expected_parent_acl()
    assert _access_acl(inspection) == _expected_pristine_socket_acl()
    assert _access_acl(measurement) == _expected_pristine_socket_acl()


def test_acl_activation_rolls_back_when_final_verification_fails(tmp_path: Path) -> None:
    """The transaction must remain active until the final policy proof succeeds."""
    parent, inspection, measurement, listeners, env = _candidate(tmp_path)
    try:
        result = _run_acl(
            env,
            r'''verify_acl_shapes() { return 74; }
if activate_socket_acls; then exit 90; fi
[[ "$(access_acl "$parent_dir")" == "$(expected_parent_acl)" ]]
[[ "$(access_acl "$inspection_socket")" == "$(expected_pristine_socket_acl)" ]]
[[ "$(access_acl "$measurement_socket")" == "$(expected_pristine_socket_acl)" ]]
''',
        )
    finally:
        for listener in listeners:
            listener.close()

    assert result.returncode == 0, result.stderr
    assert _access_acl(parent) == _expected_parent_acl()
    assert _access_acl(inspection) == _expected_pristine_socket_acl()
    assert _access_acl(measurement) == _expected_pristine_socket_acl()
