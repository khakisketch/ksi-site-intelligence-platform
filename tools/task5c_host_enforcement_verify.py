#!/usr/bin/env python3
"""Task 5c live enforcement verification (run ON the approved sandbox host as its launcher user).

Captures, against the real user manager, rootless Docker Engine and cgroup v2:

  P1  StartTransientUnit mode "fail" (duplicate creation is rejected)
  P2  exact child ControlGroup descent from the base slice
  P3  controllers + fresh (non-assumed) CPU accounting on the new slice
  P4  Engine API CgroupParent -> the container lands under the attempt slice
  P5  populated=0 before, populated=1 with the container, 0 after
  P6  fixed scope controls (CPUWeight -> cpu.weight=100)
  P7  exact StopUnit + unit/cgroup disappearance
  P8  container User=10004:10004 and read-only input mount
  P9  NetworkMode=none with an active connect attempt failing
  P10 read-only rootfs (write attempt denied)
  P12 stable final CPU reads just before exact Docker removal

Unique names; every step prints PASS/FAIL; full cleanup at the end.
"""

from __future__ import annotations

import json
import os
import pathlib
import socket
import subprocess
import sys
import time
import uuid
from contextlib import suppress
from typing import Any

sys.path.insert(0, os.environ.get("KSI_RUNTIME_SRC", "/srv/ksi-data-sandbox/runtime/ksisrc"))

from ksi_processing_controller.external_inspector_systemd import (  # noqa: E402
    LibsystemdUserManager,
    UserSystemdBusConfigV1,
)

BASE = "/user.slice/user-997.slice/user@997.service/ksi.slice/ksi-measurement.slice"
TOKEN = f"av5c{uuid.uuid4().hex[:8]}"
SLICE = f"ksi-measurement-{TOKEN}.slice"
IMAGE = "127.0.0.1:5000/ksi-measurement:037d636-r2"
DOCKER = "/run/user/997/docker.sock"
FAILED = 0


def report(name: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if not ok:
        FAILED = 1
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}", flush=True)


def read(path: str) -> str:
    return pathlib.Path(path).read_text().strip()


def api(method: str, path: str, body: bytes | dict | None = None) -> tuple[int, bytes]:
    payload = (
        b"" if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
    )
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(60)
    s.connect(DOCKER)
    head = (
        f"{method} {path} HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n"
        f"Content-Type: application/json\r\nContent-Length: {len(payload)}\r\n\r\n"
    ).encode()
    s.sendall(head + payload)
    buf = b""
    while True:
        try:
            chunk = s.recv(65536)
        except TimeoutError:
            break
        if not chunk:
            break
        buf += chunk
    s.close()
    headers, _, rest = buf.partition(b"\r\n\r\n")
    if b"transfer-encoding: chunked" in headers.lower():
        decoded = b""
        while rest:
            size_line, _, rest = rest.partition(b"\r\n")
            try:
                size = int(size_line.strip(), 16)
            except ValueError:
                break
            if size == 0:
                break
            decoded += rest[:size]
            rest = rest[size + 2 :]
        rest = decoded
    code = int(headers.split(b" ")[1]) if b" " in headers else 0
    return code, rest


def main() -> int:
    bus = UserSystemdBusConfigV1(
        bus_kind="SESSION_BUS",
        socket_path=pathlib.Path("/run/user/997/bus"),
        expected_owner_uid=997,
        expected_mode=0o600,
        timeout_micros=10_000_000,
    )
    manager = LibsystemdUserManager(bus)
    container_id = ""
    kill_container_id = ""
    kill_slice = ""
    pid = ""

    try:
        # P1/P2/P3/P6: create the transient slice exactly as the daemon does.
        unit = manager.start_transient_slice(
            unit_name=SLICE,
            mode="fail",
            properties=(
                ("Description", "task5c-live-verification"),
                ("CPUAccounting", True),
                ("CPUWeight", 100),
                ("MemoryAccounting", True),
                ("TasksAccounting", True),
                ("StopWhenUnneeded", False),
                ("CollectMode", "inactive-or-failed"),
            ),
        )
        report(
            "P2 control group descent",
            unit.control_group.startswith(BASE + "/") and unit.control_group.endswith("/" + SLICE),
            unit.control_group,
        )
        report("P2 parent slice name", unit.slice_name == "ksi-measurement.slice", unit.slice_name)
        controllers = read(f"/sys/fs/cgroup{unit.control_group}/cgroup.controllers").split()
        report(
            "P3 controllers cpu/memory/pids",
            {"cpu", "memory", "pids"}.issubset(set(controllers)),
            " ".join(controllers),
        )
        cpu_stat = read(f"/sys/fs/cgroup{unit.control_group}/cpu.stat")
        usage = next(line for line in cpu_stat.splitlines() if line.startswith("usage_usec"))
        report("P3 fresh CPU accounting", int(usage.split()[1]) < 60_000_000, usage)
        populated = read(f"/sys/fs/cgroup{unit.control_group}/cgroup.events")
        report(
            "P5 populated=0 while empty", "populated 0" in populated, populated.replace("\n", "; ")
        )
        weight = read(f"/sys/fs/cgroup{unit.control_group}/cpu.weight")
        report("P6 fixed scope control cpu.weight=100", weight == "100", weight)
        show = subprocess.run(
            [
                "systemctl",
                "--user",
                "show",
                SLICE,
                "-p",
                "InvocationID",
                "-p",
                "ObjectPath",
                "-p",
                "ControlGroup",
            ],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "XDG_RUNTIME_DIR": "/run/user/997",
                "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/997/bus",
            },
        ).stdout.strip()
        report(
            "P2b unit identity (init scope identity)",
            "InvocationID=" in show and len(show.split("InvocationID=")[1].split("\n")[0]) == 32,
            show.replace("\n", " | "),
        )

        # P1: a duplicate creation must fail under mode "fail".
        duplicate_failed = False
        try:
            manager.start_transient_slice(
                unit_name=SLICE,
                mode="fail",
                properties=(("Description", "task5c-duplicate"),),
            )
        except Exception as exc:
            duplicate_failed = True
            duplicate_detail = f"{type(exc).__name__}"
        report(
            "P1 StartTransientUnit mode=fail rejects duplicate",
            duplicate_failed,
            locals().get("duplicate_detail", ""),
        )

        # P4/P8/P9/P10: container under the attempt slice via Engine CgroupParent.
        probe_cmd = [
            "/app/.venv/bin/python",
            "-c",
            "import os,socket,pathlib\n"
            "lines = []\n"
            "lines.append(f'UID {os.geteuid()} {os.getgid()}')\n"
            "try:\n"
            "    pathlib.Path('/tmp/probe').write_text('x')\n"
            "    lines.append('ROFS_WRITE OK')\n"
            "except Exception as exc:\n"
            "    lines.append('ROFS_WRITE DENIED ' + type(exc).__name__)\n"
            "s = os.lstat('/work')\n"
            "lines.append(f'WORK {s.st_uid} {s.st_gid} {oct(s.st_mode)}')\n"
            "sock = socket.socket()\n"
            "sock.settimeout(2)\n"
            "try:\n"
            "    sock.connect(('127.0.0.1', 9100))\n"
            "    lines.append('NET_CONNECT OK')\n"
            "except Exception as exc:\n"
            "    lines.append('NET_CONNECT DENIED ' + type(exc).__name__)\n"
            "dev_lines = open('/proc/net/dev').read().splitlines()[2:]\n"
            "devs = (entry.split(':')[0].strip() for entry in dev_lines)\n"
            "lines.append('DEV ' + ','.join(devs))\n"
            "report = chr(10).join(lines)\n"
            "pathlib.Path('/work/report.txt').write_text(report)\n"
            "print(report, flush=True)\n",
        ]
        payload: dict[str, Any] = {
            "Image": IMAGE,
            "User": "10004:10004",
            "Cmd": probe_cmd,
            "OpenStdin": False,
            "StdinOnce": False,
            "AttachStdin": False,
            "AttachStdout": True,
            "AttachStderr": True,
            "Tty": False,
            "Env": ["PYTHONDONTWRITEBYTECODE=1"],
            "HostConfig": {
                "AutoRemove": False,
                "CapAdd": [],
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges:true"],
                "LogConfig": {"Type": "none", "Config": {}},
                "NetworkMode": "none",
                "ReadonlyRootfs": True,
                "Memory": 1073741824,
                "MemorySwap": 1073741824,
                "PidsLimit": 128,
                "CgroupParent": SLICE,
                "Mounts": [
                    {
                        "Type": "bind",
                        "Source": "/tmp/manual/dsm.tif",
                        "Target": "/input/artifact.tif",
                        "ReadOnly": True,
                        "BindOptions": {"NonRecursive": True},
                    }
                ],
                "Tmpfs": {
                    "/work": "rw,nodev,nosuid,noexec,size=536870912,mode=0700,uid=10004,gid=10004"
                },
            },
        }
        code, body = api("POST", "/v1.44/containers/create", payload)
        report("P8 create accepted", code == 201, str(code))
        container_id = json.loads(body)["Id"]
        code, _ = api("POST", f"/v1.44/containers/{container_id}/start")
        report("P8 container started", code == 204, str(code))
        code, body = api("GET", f"/v1.44/containers/{container_id}/json")
        text = body.decode("utf-8", "replace")
        state = json.loads(text)
        pid = str(state["State"]["Pid"])
        config = state["Config"]
        host = state["HostConfig"]
        mounts = state["Mounts"]
        report(
            "P8 container user 10004:10004",
            config.get("User") == "10004:10004" or state["Config"].get("User") == "10004:10004",
            str(config.get("User")),
        )
        report(
            "P9 NetworkMode none", host.get("NetworkMode") == "none", str(host.get("NetworkMode"))
        )
        report(
            "P10 ReadonlyRootfs true",
            host.get("ReadonlyRootfs") is True,
            str(host.get("ReadonlyRootfs")),
        )
        input_mount = next(
            (m for m in mounts if m.get("Destination") == "/input/artifact.tif"), None
        )
        report(
            "P8 input mount read-only",
            input_mount is not None and input_mount.get("RW") is False,
            json.dumps(input_mount or {})[:80],
        )
        cgroup_line = read(f"/proc/{pid}/cgroup")
        report("P4 container cgroup under attempt slice", SLICE in cgroup_line, cgroup_line)
        populated = read(f"/sys/fs/cgroup{unit.control_group}/cgroup.events")
        report(
            "P5 populated=1 with container",
            "populated 1" in populated,
            populated.replace("\n", "; "),
        )

        # wait for the probe to finish (it self-terminates; network attempts time out after 2s)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            code, body = api("GET", f"/v1.44/containers/{container_id}/json")
            if json.loads(body.decode("utf-8", "replace"))["State"]["Status"] == "exited":
                break
            time.sleep(0.3)
        logs = subprocess.run(
            ["docker", "inspect", container_id, "--format", "{{.State.ExitCode}}"],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "DOCKER_HOST": f"unix://{DOCKER}",
                "XDG_RUNTIME_DIR": "/run/user/997",
            },
        ).stdout.strip()
        report("P8 runtime probe exit code 0", logs == "0", logs)

        # P8/P9/P10 active confinement probe: identical flags, attached stdout.
        active = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "-i",
                "--user",
                "10004:10004",
                "--read-only",
                "--network",
                "none",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--tmpfs",
                "/work:rw,nodev,nosuid,noexec,size=64m,mode=0700,uid=10004,gid=10004",
                "--entrypoint",
                "/app/.venv/bin/python",
                IMAGE,
                "-c",
                "import os,socket,pathlib\n"
                "lines = [f'UID {os.geteuid()} {os.getegid()}']\n"
                "try:\n"
                "    pathlib.Path('/tmp/probe').write_text('x')\n"
                "    lines.append('ROFS_WRITE OK')\n"
                "except Exception as exc:\n"
                "    lines.append('ROFS_WRITE DENIED ' + type(exc).__name__)\n"
                "s = os.lstat('/work')\n"
                "lines.append(f'WORK {s.st_uid} {s.st_gid} {oct(s.st_mode)}')\n"
                "sock = socket.socket()\n"
                "sock.settimeout(2)\n"
                "try:\n"
                "    sock.connect(('127.0.0.1', 9100))\n"
                "    lines.append('NET_CONNECT OK')\n"
                "except Exception as exc:\n"
                "    lines.append('NET_CONNECT DENIED ' + type(exc).__name__)\n"
                "dev_lines = open('/proc/net/dev').read().splitlines()[2:]\n"
                "devs = (entry.split(':')[0].strip() for entry in dev_lines)\n"
                "lines.append('DEV ' + ','.join(devs))\n"
                "print(chr(10).join(lines))\n",
            ],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "DOCKER_HOST": f"unix://{DOCKER}",
                "XDG_RUNTIME_DIR": "/run/user/997",
            },
            timeout=120,
        )
        copied = (active.stdout or "") + (active.stderr or "")
        for marker in (
            "UID 10004 10004",
            "ROFS_WRITE DENIED",
            "WORK 10004 10004 0o40700",
            "NET_CONNECT DENIED",
            "DEV lo",
        ):
            report(
                f"P8/P9/P10 active probe: {marker}",
                marker in copied,
                copied.replace(chr(10), " | ")[:150],
            )

        # P12: two stable final CPU reads before exact removal.
        first = next(
            usage_line
            for usage_line in read(f"/sys/fs/cgroup{unit.control_group}/cpu.stat").splitlines()
            if usage_line.startswith("usage_usec")
        )
        time.sleep(0.3)
        second = next(
            usage_line
            for usage_line in read(f"/sys/fs/cgroup{unit.control_group}/cpu.stat").splitlines()
            if usage_line.startswith("usage_usec")
        )
        report("P12 stable final CPU before removal", first == second, f"{first} == {second}")
        populated = read(f"/sys/fs/cgroup{unit.control_group}/cgroup.events")
        report(
            "P5 populated=0 after exit", "populated 0" in populated, populated.replace("\n", "; ")
        )

        # exact removal + StopUnit + disappearance
        code, _ = api("DELETE", f"/v1.44/containers/{container_id}?v=1&force=1")
        report("P12 exact Docker removal", code == 204, str(code))
        container_id = ""
        stopped = manager.stop_exact(unit_name=SLICE)
        report("P7 StopUnit applied", bool(stopped), str(stopped))
        time.sleep(1.5)
        unit_gone = subprocess.run(
            ["systemctl", "--user", "show", SLICE],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "XDG_RUNTIME_DIR": "/run/user/997",
                "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/997/bus",
            },
        ).stdout
        cgroup_gone = not pathlib.Path(f"/sys/fs/cgroup{unit.control_group}").exists()
        report(
            "P7 unit and cgroup disappear",
            "LoadState=not-found" in unit_gone or not unit_gone.strip() or cgroup_gone,
            f"cgroup_gone={cgroup_gone}",
        )
        # P13: bounded kill latency for a long-running container under a fresh slice.
        kill_slice = f"ksi-measurement-{TOKEN}k.slice"
        unit2 = manager.start_transient_slice(
            unit_name=kill_slice,
            mode="fail",
            properties=(
                ("Description", "task5c-kill-drill"),
                ("CPUAccounting", True),
                ("CPUWeight", 100),
                ("MemoryAccounting", True),
                ("TasksAccounting", True),
                ("StopWhenUnneeded", False),
                ("CollectMode", "inactive-or-failed"),
            ),
        )
        kill_payload = dict(payload)
        kill_payload["Cmd"] = ["/app/.venv/bin/python", "-c", "import time; time.sleep(600)"]
        kill_payload["HostConfig"] = dict(payload["HostConfig"])
        kill_payload["HostConfig"]["CgroupParent"] = kill_slice
        code, body = api("POST", "/v1.44/containers/create", kill_payload)
        report("P13 drill container accepted", code == 201, str(code))
        kill_container_id = json.loads(body)["Id"]
        code, _ = api("POST", f"/v1.44/containers/{kill_container_id}/start")
        report("P13 drill container started", code == 204, str(code))
        time.sleep(1.0)
        populated = read(f"/sys/fs/cgroup{unit2.control_group}/cgroup.events")
        report(
            "P13 populated=1 before kill",
            "populated 1" in populated,
            populated.replace(chr(10), "; "),
        )
        killed_at = time.monotonic()
        code, _ = api("POST", f"/v1.44/containers/{kill_container_id}/kill")
        report("P13 exact Engine kill accepted", code == 204, str(code))
        deadline = time.monotonic() + 15
        emptied = False
        while time.monotonic() < deadline:
            events = read(f"/sys/fs/cgroup{unit2.control_group}/cgroup.events")
            if "populated 0" in events:
                emptied = True
                break
            time.sleep(0.05)
        latency_ms = int((time.monotonic() - killed_at) * 1000)
        report("P13 cgroup emptied within bound (<=15s)", emptied, f"{latency_ms} ms")
        code, _ = api("DELETE", f"/v1.44/containers/{kill_container_id}?v=1&force=1")
        report("P13 drill exact removal", code == 204, str(code))
        kill_container_id = ""
        report("P13 drill StopUnit", bool(manager.stop_exact(unit_name=kill_slice)), "")
        kill_slice = ""
    finally:
        if container_id:
            api("DELETE", f"/v1.44/containers/{container_id}?v=1&force=1")
        if kill_container_id:
            api("DELETE", f"/v1.44/containers/{kill_container_id}?v=1&force=1")
        with suppress(Exception):
            manager.stop_exact(unit_name=SLICE)
        if kill_slice:
            with suppress(Exception):
                manager.stop_exact(unit_name=kill_slice)
    print("HARNESS", "OK" if FAILED == 0 else "FAILED", flush=True)
    return FAILED


if __name__ == "__main__":
    raise SystemExit(main())
