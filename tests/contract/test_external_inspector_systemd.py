"""Local-only systemd transient-slice receipt conformance."""

from __future__ import annotations

import ctypes
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from ksi_processing_controller.external_inspector_attempts import AttemptBindingV1
from ksi_processing_controller.external_inspector_container_protocol import (
    FixedContainerConfigurationV1,
)
from ksi_processing_controller.external_inspector_docker import (
    CgroupV2RootConfigV1,
    CgroupV2RootV1,
    DockerRuntimeUnavailable,
)
from ksi_processing_controller.external_inspector_systemd import (
    LibsystemdUserManager,
    SystemdRuntimeUnavailable,
    SystemdTransientSliceConfigV1,
    SystemdTransientSliceController,
    SystemdTransientUnitV1,
    UserSystemdBusConfigV1,
    _JobRemovedWatch,
)
from test_external_inspector_docker import _binding, _configuration, _UnreachableSource


class _Lifecycle:
    def __init__(self, *, status: str = "created", pid: int = 0) -> None:
        self._status = status
        self._pid = pid

    def inspect_exact(self, runtime_id: str, *, deadline_monotonic: float) -> dict[str, object]:
        assert runtime_id
        assert deadline_monotonic > 0.0
        return {
            "State": {
                "Running": self._status == "running",
                "Status": self._status,
                "Pid": self._pid,
            }
        }


class _ProcCgroups:
    def read_cgroup_path(self, pid: int) -> str:
        assert pid > 0
        return "/base.slice/ksi-inspector-a0123456789abcdef.slice/docker-runtime-a.scope"


def test_transient_slice_receipt_precedes_docker_create_and_binds_actual_baseline(
    tmp_path: Path,
) -> None:
    root = tmp_path / "cgroup2"
    control_group = "/base.slice/ksi-inspector-a0123456789abcdef.slice"
    directory = root / control_group.removeprefix("/")
    directory.mkdir(parents=True)
    (directory / "cgroup.controllers").write_text("cpu memory pids\n", encoding="ascii")
    (directory / "cpu.stat").write_text("usage_usec 73\n", encoding="ascii")
    (directory / "cpu.max").write_text("1000 1000\n", encoding="ascii")
    (directory / "memory.max").write_text("1000\n", encoding="ascii")
    (directory / "memory.swap.max").write_text("0\n", encoding="ascii")
    (directory / "pids.max").write_text("10\n", encoding="ascii")
    (directory / "cgroup.events").write_text("populated 0\n", encoding="ascii")

    class _Manager:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, tuple[tuple[str, object], ...]]] = []

        def start_transient_slice(
            self, *, unit_name: str, mode: str, properties: tuple[tuple[str, object], ...]
        ) -> SystemdTransientUnitV1:
            self.calls.append((unit_name, mode, properties))
            return SystemdTransientUnitV1(
                unit_name=unit_name,
                object_path="/org/freedesktop/systemd1/unit/ksi_2dinspector_2da.slice",
                control_group=control_group,
                description="ksi-external-inspector-attempt.v1:" + _binding().digest,
                slice_name="ksi-inspector.slice",
                invocation_id="a" * 32,
            )

        def stop_exact(self, *, unit_name: str) -> bool:
            del unit_name
            return True

        def inspect_exact(self, *, unit_name: str) -> None:
            del unit_name
            return None

    manager = _Manager()
    controller = SystemdTransientSliceController(
        manager=manager,
        cgroups=CgroupV2RootV1(
            CgroupV2RootConfigV1(
                root=root, base_control_group="/base.slice", maximum_control_bytes=4096
            )
        ),
        runtime_lifecycle=_Lifecycle(status="exited"),
        proc_cgroups=_ProcCgroups(),
        config=SystemdTransientSliceConfigV1(
            base_slice_name="ksi-inspector.slice",
            stable_final_samples=2,
            cleanup_timeout_millis=100,
        ),
    )
    binding: AttemptBindingV1 = _binding()
    configuration: FixedContainerConfigurationV1 = _configuration(_UnreachableSource())

    receipt = controller.bind_before_create(binding=binding, configuration=configuration)

    assert receipt.unit_name == binding.systemd_slice_name
    assert receipt.control_group == control_group
    assert receipt.controllers == ("cpu", "memory", "pids")
    assert receipt.baseline_cpu_counter == 73
    assert receipt.cpu_budget_counter == configuration.cpu_budget_counter
    assert manager.calls == [
        (
            binding.systemd_slice_name,
            "fail",
            (
                ("Description", "ksi-external-inspector-attempt.v1:" + binding.digest),
                ("CPUAccounting", True),
                ("CPUWeight", 100),
                ("MemoryAccounting", True),
                ("TasksAccounting", True),
                ("StopWhenUnneeded", False),
                ("CollectMode", "inactive-or-failed"),
            ),
        )
    ]


def test_append_properties_uses_explicit_struct_signature_and_omits_slice() -> None:
    """libsystemd needs the 'sv' struct signature, and Slice= is refused on slice units."""
    from ksi_processing_controller.external_inspector_systemd import LibsystemdUserManager

    manager = object.__new__(LibsystemdUserManager)
    opens: list[tuple[int, bytes | None]] = []
    strings: list[str] = []

    class _FakeLibrary:
        def sd_bus_message_append_basic(
            self, message: object, type_code: int, pointer: object
        ) -> int:
            return 0

    manager._library = _FakeLibrary()  # type: ignore[assignment]
    manager._check = lambda result: None  # type: ignore[method-assign]
    manager._open = lambda message, type_code, contents: opens.append((type_code, contents))  # type: ignore[method-assign]
    manager._close = lambda message: None  # type: ignore[method-assign]
    manager._append_string = lambda message, value: strings.append(value)  # type: ignore[method-assign]

    manager._append_properties(
        None,
        (
            ("Description", "probe"),
            ("CPUAccounting", True),
            ("CPUWeight", 100),
            ("CollectMode", "inactive-or-failed"),
        ),
    )

    assert opens[0] == (ord("a"), b"(sv)")
    assert [entry for entry in opens if entry[0] == ord("r")] == [
        (ord("r"), b"sv"),
        (ord("r"), b"sv"),
        (ord("r"), b"sv"),
        (ord("r"), b"sv"),
    ]
    assert [entry for entry in opens if entry[0] == ord("v")] == [
        (ord("v"), b"s"),
        (ord("v"), b"b"),
        (ord("v"), b"t"),
        (ord("v"), b"s"),
    ]
    assert strings == [
        "Description",
        "probe",
        "CPUAccounting",
        "CPUWeight",
        "CollectMode",
        "inactive-or-failed",
    ]


def test_stop_exact_rechecks_the_durable_binding_description_before_stopping(
    tmp_path: Path,
) -> None:
    """A reused slice name cannot be adopted or stopped from its pathname alone."""
    root = tmp_path / "cgroup2"
    control_group = "/base.slice/ksi-inspector-a0123456789abcdef.slice"
    directory = root / control_group.removeprefix("/")
    directory.mkdir(parents=True)
    (directory / "cgroup.controllers").write_text("cpu memory pids\n", encoding="ascii")
    (directory / "cpu.stat").write_text("usage_usec 73\n", encoding="ascii")
    (directory / "cpu.max").write_text("1000 1000\n", encoding="ascii")
    (directory / "memory.max").write_text("1000\n", encoding="ascii")
    (directory / "memory.swap.max").write_text("0\n", encoding="ascii")
    (directory / "pids.max").write_text("10\n", encoding="ascii")
    (directory / "cgroup.events").write_text("populated 0\n", encoding="ascii")
    binding = _binding()

    class _Manager:
        def start_transient_slice(self, **kwargs: object) -> SystemdTransientUnitV1:
            del kwargs
            raise AssertionError("cleanup must not create a slice")

        def inspect_exact(self, *, unit_name: str) -> SystemdTransientUnitV1:
            return SystemdTransientUnitV1(
                unit_name=unit_name,
                object_path="/org/freedesktop/systemd1/unit/ksi_2dinspector_2da.slice",
                control_group=control_group,
                description="unrelated binding",
                slice_name="ksi-inspector.slice",
                invocation_id="a" * 32,
            )

        def stop_exact(self, *, unit_name: str) -> bool:
            del unit_name
            raise AssertionError("unbound slice must not be stopped")

    controller = SystemdTransientSliceController(
        manager=_Manager(),
        cgroups=CgroupV2RootV1(
            CgroupV2RootConfigV1(
                root=root, base_control_group="/base.slice", maximum_control_bytes=4096
            )
        ),
        runtime_lifecycle=_Lifecycle(status="exited"),
        proc_cgroups=_ProcCgroups(),
        config=SystemdTransientSliceConfigV1(
            base_slice_name="ksi-inspector.slice",
            stable_final_samples=2,
            cleanup_timeout_millis=100,
        ),
    )
    from ksi_processing_controller.external_inspector_attempts import RuntimeParentReceiptV1

    recorded = RuntimeParentReceiptV1(
        unit_name=binding.systemd_slice_name,
        object_path="/org/freedesktop/systemd1/unit/ksi_2dinspector_2da.slice",
        description="ksi-external-inspector-attempt.v1:" + binding.digest,
        slice_name=binding.systemd_base_slice,
        control_group=control_group,
        invocation_id="a" * 32,
        device=directory.stat().st_dev,
        inode=directory.stat().st_ino,
        controllers=("cpu", "memory", "pids"),
        cpu_counter_unit="CPU_USEC",
        baseline_cpu_counter=73,
        cpu_budget_counter=1_000,
    )
    assert controller.stop_exact(binding=binding, receipt=recorded) is False


def test_final_parent_proof_requires_identity_unpopulated_and_stable_cpu_before_remove(
    tmp_path: Path,
) -> None:
    """Container removal is gated on the persisted parent, not a cgroup pathname."""
    root = tmp_path / "cgroup2"
    control_group = "/base.slice/ksi-inspector-a0123456789abcdef.slice"
    directory = root / control_group.removeprefix("/")
    directory.mkdir(parents=True)
    (directory / "cgroup.controllers").write_text("cpu memory pids\n", encoding="ascii")
    (directory / "cpu.stat").write_text("usage_usec 73\n", encoding="ascii")
    (directory / "cpu.max").write_text("1000 1000\n", encoding="ascii")
    (directory / "memory.max").write_text("1000\n", encoding="ascii")
    (directory / "memory.swap.max").write_text("0\n", encoding="ascii")
    (directory / "pids.max").write_text("10\n", encoding="ascii")
    populated = directory / "cgroup.events"
    populated.write_text("populated 0\n", encoding="ascii")
    (directory / "docker-runtime-a.scope").mkdir()
    binding = _binding()
    receipt = SystemdTransientUnitV1(
        unit_name=binding.systemd_slice_name,
        object_path="/org/freedesktop/systemd1/unit/ksi_2dinspector_2da.slice",
        control_group=control_group,
        description="ksi-external-inspector-attempt.v1:" + binding.digest,
        slice_name=binding.systemd_base_slice,
        invocation_id="a" * 32,
    )

    class _Manager:
        def inspect_exact(self, *, unit_name: str) -> SystemdTransientUnitV1:
            assert unit_name == binding.systemd_slice_name
            return receipt

        def start_transient_slice(self, **kwargs: object) -> SystemdTransientUnitV1:
            del kwargs
            raise AssertionError("final proof must not create a unit")

        def stop_exact(self, **kwargs: object) -> bool:
            del kwargs
            raise AssertionError("final proof must not stop a unit")

    controller = SystemdTransientSliceController(
        manager=_Manager(),
        cgroups=CgroupV2RootV1(
            CgroupV2RootConfigV1(
                root=root, base_control_group="/base.slice", maximum_control_bytes=4096
            )
        ),
        runtime_lifecycle=_Lifecycle(status="exited"),
        proc_cgroups=_ProcCgroups(),
        config=SystemdTransientSliceConfigV1(
            base_slice_name="ksi-inspector.slice",
            stable_final_samples=2,
            cleanup_timeout_millis=100,
        ),
    )
    from ksi_processing_controller.external_inspector_attempts import RuntimeParentReceiptV1

    recorded = RuntimeParentReceiptV1(
        unit_name=receipt.unit_name,
        object_path=receipt.object_path,
        description=receipt.description,
        slice_name=receipt.slice_name,
        control_group=receipt.control_group,
        invocation_id=receipt.invocation_id,
        device=directory.stat().st_dev,
        inode=directory.stat().st_ino,
        controllers=("cpu", "memory", "pids"),
        cpu_counter_unit="CPU_USEC",
        baseline_cpu_counter=1,
        cpu_budget_counter=1_000,
    )
    assert (
        controller.verify_before_quiesce(binding=binding, receipt=recorded, runtime_id="runtime-a")
        is True
    )
    assert (
        controller.verify_final_before_remove(
            binding=binding, receipt=recorded, runtime_id="runtime-a"
        )
        is True
    )
    # A final counter below the durable pre-create baseline is rollback, not a
    # valid stable accounting result.
    assert (
        controller.verify_final_before_remove(
            binding=binding,
            receipt=replace(recorded, baseline_cpu_counter=74),
            runtime_id="runtime-a",
        )
        is False
    )
    populated.write_text("populated 1\n", encoding="ascii")
    assert (
        controller.verify_final_before_remove(
            binding=binding, receipt=recorded, runtime_id="runtime-a"
        )
        is False
    )


def test_final_parent_proof_rejects_budget_overrun_and_unknown_child(tmp_path: Path) -> None:
    """A late aggregate overrun or extra empty scope cannot retire a successful attempt."""
    root = tmp_path / "cgroup2"
    control_group = "/base.slice/ksi-inspector-a0123456789abcdef.slice"
    directory = root / control_group.removeprefix("/")
    directory.mkdir(parents=True)
    for name, value in {
        "cgroup.controllers": "cpu memory pids\n",
        "cpu.stat": "usage_usec 20\n",
        "cpu.max": "1000 1000\n",
        "memory.max": "1000\n",
        "memory.swap.max": "0\n",
        "pids.max": "10\n",
        "cgroup.events": "populated 0\n",
    }.items():
        (directory / name).write_text(value, encoding="ascii")
    (directory / "docker-runtime-a.scope").mkdir()
    binding = _binding()
    unit = SystemdTransientUnitV1(
        unit_name=binding.systemd_slice_name,
        object_path="/org/freedesktop/systemd1/unit/ksi_2dinspector_2da.slice",
        control_group=control_group,
        description="ksi-external-inspector-attempt.v1:" + binding.digest,
        slice_name=binding.systemd_base_slice,
        invocation_id="a" * 32,
    )

    class _Manager:
        def inspect_exact(self, *, unit_name: str) -> SystemdTransientUnitV1:
            assert unit_name == binding.systemd_slice_name
            return unit

        def start_transient_slice(
            self, *, unit_name: str, mode: str, properties: tuple[tuple[str, object], ...]
        ) -> SystemdTransientUnitV1:
            del unit_name, mode, properties
            raise AssertionError("final proof must not create a unit")

        def stop_exact(self, *, unit_name: str) -> bool:
            del unit_name
            raise AssertionError("final proof must not stop a unit")

    from ksi_processing_controller.external_inspector_attempts import RuntimeParentReceiptV1

    controller = SystemdTransientSliceController(
        manager=_Manager(),
        cgroups=CgroupV2RootV1(
            CgroupV2RootConfigV1(
                root=root, base_control_group="/base.slice", maximum_control_bytes=4096
            )
        ),
        runtime_lifecycle=_Lifecycle(status="exited"),
        proc_cgroups=_ProcCgroups(),
        config=SystemdTransientSliceConfigV1(
            base_slice_name="ksi-inspector.slice",
            stable_final_samples=2,
            cleanup_timeout_millis=100,
        ),
    )
    receipt = RuntimeParentReceiptV1(
        unit_name=unit.unit_name,
        object_path=unit.object_path,
        description=unit.description,
        slice_name=unit.slice_name,
        control_group=unit.control_group,
        invocation_id=unit.invocation_id,
        device=directory.stat().st_dev,
        inode=directory.stat().st_ino,
        controllers=("cpu", "memory", "pids"),
        cpu_counter_unit="CPU_USEC",
        baseline_cpu_counter=1,
        cpu_budget_counter=10,
    )
    assert (
        controller.verify_final_before_remove(
            binding=binding, receipt=receipt, runtime_id="runtime-a"
        )
        is False
    )
    (directory / "foreign.scope").mkdir()
    assert (
        controller.verify_before_quiesce(
            binding=binding,
            receipt=replace(receipt, cpu_budget_counter=100),
            runtime_id="runtime-a",
        )
        is False
    )


def test_libsystemd_string_arguments_are_passed_as_char_p_not_pointer_to_pointer() -> None:
    """The sd-bus ABI receives the string bytes that its `s` signature requires."""

    class _Library:
        def sd_bus_message_append_basic(self, message, type_code, value):  # type: ignore[no-untyped-def]
            assert message == "message"
            assert type_code == ord("s")
            assert ctypes.string_at(value) == b"ksi-inspector.slice"
            return 0

    manager = cast(Any, object.__new__(LibsystemdUserManager))
    manager._library = _Library()
    manager._append_string("message", "ksi-inspector.slice")


def test_libsystemd_session_bus_configures_client_mode_and_uint64_timeout() -> None:
    """The concrete session-bus constructor uses Hello/client mode with a declared ABI."""
    manager = cast(Any, object.__new__(LibsystemdUserManager))
    manager._library = ctypes.CDLL("libsystemd.so.0")
    manager._configure_library()
    assert manager._library.sd_bus_call.argtypes[2] is ctypes.c_uint64
    assert manager._library.sd_bus_set_bus_client.argtypes == [ctypes.c_void_p, ctypes.c_int]
    bus = ctypes.c_void_p()
    assert manager._library.sd_bus_new(ctypes.byref(bus)) >= 0
    try:
        assert manager._library.sd_bus_set_bus_client(bus, 1) >= 0
        assert manager._library.sd_bus_is_bus_client(bus) == 1
    finally:
        manager._library.sd_bus_unref(bus)


def test_libsystemd_constructor_selects_session_client_before_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The configured SESSION_BUS route cannot silently retain libsystemd peer mode."""

    class _Call:
        def __init__(self, name: str, calls: list[str]) -> None:
            self._name = name
            self._calls = calls

        def __call__(self, *args: Any) -> int:
            self._calls.append(self._name)
            if self._name == "sd_bus_new":
                pointer = ctypes.cast(args[0], ctypes.POINTER(ctypes.c_void_p))
                pointer[0] = ctypes.c_void_p(7)
            return 0

    class _Library:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def __getattr__(self, name: str) -> _Call:
            value = _Call(name, self.calls)
            setattr(self, name, value)
            return value

    library = _Library()
    monkeypatch.setattr(
        "ksi_processing_controller.external_inspector_systemd.ctypes.CDLL",
        lambda _: library,
    )
    monkeypatch.setattr(LibsystemdUserManager, "_verify_bus_socket", lambda _self: None)
    manager = LibsystemdUserManager(
        UserSystemdBusConfigV1(
            bus_kind="SESSION_BUS",
            socket_path=Path("/run/user/1000/bus"),
            expected_owner_uid=1000,
            expected_mode=0o600,
            timeout_micros=100_000,
        )
    )
    try:
        assert library.calls[:4] == [
            "sd_bus_new",
            "sd_bus_set_address",
            "sd_bus_set_bus_client",
            "sd_bus_start",
        ]
    finally:
        manager.close()


def test_libsystemd_correlates_buffered_job_removed_before_final_unit_lookup() -> None:
    """A fast JobRemoved signal is authoritative even though its Job object already vanished."""

    class _Watch:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, float]] = []

        def wait_for(
            self, *, job_path: str, unit_name: str, deadline_monotonic: float
        ) -> str:
            self.calls.append((job_path, unit_name, deadline_monotonic))
            return "done"

    manager = cast(Any, object.__new__(LibsystemdUserManager))
    manager._config = UserSystemdBusConfigV1(
        bus_kind="SESSION_BUS",
        socket_path=Path("/run/user/1000/bus"),
        expected_owner_uid=1000,
        expected_mode=0o600,
        timeout_micros=100_000,
    )
    manager._job_state = lambda _path: (_ for _ in ()).throw(
        AssertionError("Job.State is not terminal")
    )
    watch = _Watch()

    assert (
        manager._wait_for_job_removed(
            watch=watch,
            job_path="/org/freedesktop/systemd1/job/17",
            unit_name="ksi-inspector-a0123456789abcdef.slice",
        )
        == "done"
    )
    assert watch.calls[0][:2] == (
        "/org/freedesktop/systemd1/job/17",
        "ksi-inspector-a0123456789abcdef.slice",
    )


def test_libsystemd_rejects_failed_job_removed_result() -> None:
    """Only a returned job's exact `done` JobRemoved result authorizes final inspection."""

    class _Watch:
        def __init__(self, result: str) -> None:
            self._result = result

        def wait_for(
            self, *, job_path: str, unit_name: str, deadline_monotonic: float
        ) -> str:
            del job_path, unit_name, deadline_monotonic
            return self._result

    manager = cast(Any, object.__new__(LibsystemdUserManager))
    manager._config = UserSystemdBusConfigV1(
        bus_kind="SESSION_BUS",
        socket_path=Path("/run/user/1000/bus"),
        expected_owner_uid=1000,
        expected_mode=0o600,
        timeout_micros=100_000,
    )
    for result in ("failed", "canceled", "timeout"):
        with pytest.raises(SystemdRuntimeUnavailable, match="JobRemoved"):
            manager._wait_for_job_removed(
                watch=_Watch(result),
                job_path="/org/freedesktop/systemd1/job/17",
                unit_name="ksi-inspector-a0123456789abcdef.slice",
            )


def test_job_removed_watch_ignores_other_units_before_its_exact_completion() -> None:
    """Normal service/scope completions cannot poison this attempt's buffered JobRemoved watch."""

    class _Library:
        def sd_bus_add_match(self, *args: object) -> int:
            del args
            return 0

        def sd_bus_message_read_basic(self, message, kind, pointer):  # type: ignore[no-untyped-def]
            del kind
            ctypes.cast(pointer, ctypes.POINTER(ctypes.c_uint32))[0] = message
            return 1

    target = "ksi-inspector-a0123456789abcdef.slice"
    manager = cast(Any, object.__new__(LibsystemdUserManager))
    manager._library = _Library()
    manager._bus = ctypes.c_void_p()
    watch = _JobRemovedWatch(manager, target_unit_name=target)

    def signal(job: int, unit_name: str) -> None:
        values = iter([f"/org/freedesktop/systemd1/job/{job}", unit_name, "done"])
        manager._read_basic = lambda *args: next(values)
        cast(Any, watch)._on_signal(job, None, None)

    signal(16, "docker.service")
    signal(17, "other.scope")
    signal(18, target)

    assert (
        watch.wait_for(
            job_path="/org/freedesktop/systemd1/job/18",
            unit_name=target,
            deadline_monotonic=time.monotonic() + 1.0,
        )
        == "done"
    )
    watch.close()


def test_job_removed_watch_rejects_malformed_event_for_its_exact_unit() -> None:
    """Filtering other units never permits an invalid JobRemoved identity for this slice."""

    class _Library:
        def sd_bus_add_match(self, *args: object) -> int:
            del args
            return 0

        def sd_bus_message_read_basic(self, message, kind, pointer):  # type: ignore[no-untyped-def]
            del kind
            ctypes.cast(pointer, ctypes.POINTER(ctypes.c_uint32))[0] = message
            return 1

    target = "ksi-inspector-a0123456789abcdef.slice"
    manager = cast(Any, object.__new__(LibsystemdUserManager))
    manager._library = _Library()
    manager._bus = ctypes.c_void_p()
    watch = _JobRemovedWatch(manager, target_unit_name=target)
    values = iter(["/org/freedesktop/systemd1/job/19", target, "done"])
    manager._read_basic = lambda *args: next(values)
    cast(Any, watch)._on_signal(18, None, None)

    with pytest.raises(SystemdRuntimeUnavailable, match="binding differs"):
        watch.wait_for(
            job_path="/org/freedesktop/systemd1/job/18",
            unit_name=target,
            deadline_monotonic=time.monotonic() + 1.0,
        )
    watch.close()


def test_created_unstarted_runtime_allows_only_empty_parent_at_durable_baseline() -> None:
    """A known created-but-never-started container has no Docker scope to prove or kill."""

    class _Parent:
        def is_unpopulated(self) -> bool:
            return True

        def has_no_child_cgroups(self) -> bool:
            return True

        def read_aggregate_cpu(self):  # type: ignore[no-untyped-def]
            from ksi_processing_controller.external_inspector_runtime import (
                AggregateCpuCounterV1,
                CpuCounterUnitV1,
            )

            return AggregateCpuCounterV1(
                value=7,
                unit=CpuCounterUnitV1.CPU_USEC,
                complete_process_tree=True,
            )

        def close(self) -> None:
            return None

    class _Lifecycle:
        def inspect_exact(self, runtime_id: str, *, deadline_monotonic: float) -> dict[str, object]:
            assert runtime_id == "runtime-a"
            assert deadline_monotonic > 0
            return {"State": {"Running": False, "Status": "created", "Pid": 0}}

    controller = cast(Any, object.__new__(SystemdTransientSliceController))
    controller._matches_recorded_parent = lambda *args: True
    controller._open_recorded_parent = lambda *args: _Parent()
    controller._runtime_lifecycle = _Lifecycle()
    controller._cleanup_timeout_seconds = 1.0
    controller._config = SimpleNamespace(stable_final_samples=2)

    from ksi_processing_controller.external_inspector_attempts import RuntimeParentReceiptV1

    binding = _binding()
    receipt = RuntimeParentReceiptV1(
        unit_name=binding.systemd_slice_name,
        object_path="/org/freedesktop/systemd1/unit/created",
        description="ksi-external-inspector-attempt.v1:" + binding.digest,
        slice_name=binding.systemd_base_slice,
        control_group="/base.slice/" + binding.systemd_slice_name,
        invocation_id="a" * 32,
        device=1,
        inode=2,
        controllers=("cpu", "memory", "pids"),
        cpu_counter_unit="CPU_USEC",
        baseline_cpu_counter=7,
        cpu_budget_counter=100,
    )
    assert (
        controller.verify_before_quiesce(
            binding=binding,
            receipt=receipt,
            runtime_id="runtime-a",
        )
        is True
    )
    assert (
        controller.verify_final_before_remove(
            binding=binding,
            receipt=receipt,
            runtime_id="runtime-a",
        )
        is True
    )


def test_running_runtime_without_its_exact_scope_is_not_quiesceable() -> None:
    """A live Engine PID never authorizes an empty parent as an equivalent scope."""

    class _Parent:
        def open_only_scope(self, *, expected_scope_name: str):  # type: ignore[no-untyped-def]
            assert expected_scope_name == "docker-runtime-a.scope"
            raise DockerRuntimeUnavailable("expected scope is absent")

        def close(self) -> None:
            return None

    class _Lifecycle:
        def inspect_exact(self, runtime_id: str, *, deadline_monotonic: float) -> dict[str, object]:
            assert runtime_id == "runtime-a"
            assert deadline_monotonic > 0
            return {"State": {"Running": True, "Status": "running", "Pid": 41}}

    controller = cast(Any, object.__new__(SystemdTransientSliceController))
    controller._matches_recorded_parent = lambda *args: True
    controller._open_recorded_parent = lambda *args: _Parent()
    controller._runtime_lifecycle = _Lifecycle()
    controller._proc_cgroups = _ProcCgroups()
    controller._cleanup_timeout_seconds = 1.0

    from ksi_processing_controller.external_inspector_attempts import RuntimeParentReceiptV1

    binding = _binding()
    receipt = RuntimeParentReceiptV1(
        unit_name=binding.systemd_slice_name,
        object_path="/org/freedesktop/systemd1/unit/running",
        description="ksi-external-inspector-attempt.v1:" + binding.digest,
        slice_name=binding.systemd_base_slice,
        control_group="/base.slice/" + binding.systemd_slice_name,
        invocation_id="a" * 32,
        device=1,
        inode=2,
        controllers=("cpu", "memory", "pids"),
        cpu_counter_unit="CPU_USEC",
        baseline_cpu_counter=7,
        cpu_budget_counter=100,
    )

    assert (
        controller.verify_before_quiesce(
            binding=binding,
            receipt=receipt,
            runtime_id="runtime-a",
        )
        is False
    )
