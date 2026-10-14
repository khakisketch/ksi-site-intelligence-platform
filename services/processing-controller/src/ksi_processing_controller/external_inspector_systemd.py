"""Narrow user-systemd transient-slice control for external inspector attempts.

Task 5 provisions the user manager and base slice.  This module performs no
raw cgroup creation or dummy-process fallback: a D-Bus manager must return the
actual ControlGroup, which is then opened through the provisioned cgroup-v2
root and persisted before Docker create.
"""

from __future__ import annotations

import ctypes
import math
import os
import re
import stat
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Literal, Protocol

from ksi_processing_controller.external_inspector_attempts import (
    RuntimeParentReceiptV1,
)
from ksi_processing_controller.external_inspector_container_protocol import (
    FixedContainerConfigurationV1,
)
from ksi_processing_controller.external_inspector_docker import (
    CgroupV2AttemptSlice,
    CgroupV2RootV1,
    DockerRuntimeUnavailable,
    ProcCgroupReaderPort,
)
from ksi_processing_controller.external_inspector_runtime import CpuCounterUnitV1
from ksi_processing_controller.external_runtime_binding import ExactRuntimeBindingPort

_SLICE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@:-]{0,254}\.slice$")
_JOB_PATH = re.compile(r"^/org/freedesktop/systemd1/job/([1-9][0-9]*)$")


class SystemdRuntimeUnavailable(DockerRuntimeUnavailable):
    """The exact user-manager transient slice cannot be proven or controlled."""


class _SystemdUnitMissing(SystemdRuntimeUnavailable):
    """Only the exact requested unit was absent; callers still have no broad lookup."""


class _SdBusError(ctypes.Structure):
    _fields_ = [
        ("name", ctypes.c_char_p),
        ("message", ctypes.c_char_p),
        ("need_free", ctypes.c_int),
    ]


_SdBusMessageHandler = ctypes.CFUNCTYPE(
    ctypes.c_int,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.POINTER(_SdBusError),
)


@dataclass(frozen=True, slots=True)
class _JobRemovedEvent:
    job_id: int
    job_path: str
    unit_name: str
    result: str


@dataclass(frozen=True, slots=True)
class SystemdTransientSliceConfigV1:
    base_slice_name: str
    stable_final_samples: int
    cleanup_timeout_millis: int

    def __post_init__(self) -> None:
        if _SLICE.fullmatch(self.base_slice_name) is None:
            raise ValueError("configured systemd base slice name is invalid")
        if type(self.stable_final_samples) is not int or self.stable_final_samples < 2:
            raise ValueError("systemd final CPU stability samples are required")
        if type(self.cleanup_timeout_millis) is not int or self.cleanup_timeout_millis <= 0:
            raise ValueError("systemd cleanup deadline is required")


@dataclass(frozen=True, slots=True)
class UserSystemdBusConfigV1:
    """The provisioned user-manager bus identity; no environment discovery occurs."""

    bus_kind: str
    socket_path: Path
    expected_owner_uid: int
    expected_mode: int
    timeout_micros: int

    def __post_init__(self) -> None:
        if self.bus_kind != "SESSION_BUS":
            raise ValueError("user systemd bus kind must be the configured session bus")
        if not self.socket_path.is_absolute():
            raise ValueError("user systemd bus path must be absolute")
        if type(self.expected_owner_uid) is not int or self.expected_owner_uid < 0:
            raise ValueError("user systemd bus owner is invalid")
        if (self.expected_mode & 0o777) != 0o600:
            raise ValueError("user systemd bus mode must be exactly 0600")
        if type(self.timeout_micros) is not int or self.timeout_micros <= 0:
            raise ValueError("user systemd D-Bus timeout is required")


@dataclass(frozen=True, slots=True)
class SystemdTransientUnitV1:
    unit_name: str
    object_path: str
    control_group: str
    description: str
    slice_name: str
    invocation_id: str

    def __post_init__(self) -> None:
        if _SLICE.fullmatch(self.unit_name) is None:
            raise ValueError("transient systemd slice name is invalid")
        if (
            not self.object_path.startswith("/")
            or not self.control_group.startswith("/")
            or not self.description
            or _SLICE.fullmatch(self.slice_name) is None
            or re.fullmatch(r"[0-9a-f]{32}", self.invocation_id) is None
        ):
            raise ValueError("transient systemd identity is invalid")


class DockerRuntimeLifecyclePort(Protocol):
    """Read only the exact recorded Engine object during parent cleanup proof."""

    def inspect_exact(self, runtime_id: str, *, deadline_monotonic: float) -> Mapping[str, Any]: ...


class SystemdUserManagerPort(Protocol):
    """A narrow D-Bus manager facade: no unit listing or arbitrary methods."""

    def start_transient_slice(
        self, *, unit_name: str, mode: str, properties: tuple[tuple[str, object], ...]
    ) -> SystemdTransientUnitV1: ...

    def inspect_exact(self, *, unit_name: str) -> SystemdTransientUnitV1 | None: ...

    def stop_exact(self, *, unit_name: str) -> bool: ...


class _JobRemovedWatch:
    """A retained pre-call JobRemoved subscription with bounded early-event buffering."""

    _MATCH = (
        "type='signal',sender='org.freedesktop.systemd1',"
        "interface='org.freedesktop.systemd1.Manager',member='JobRemoved'"
    ).encode("ascii")
    _MAX_UNBOUND_BUFFERED_EVENTS = 16

    def __init__(
        self, manager: LibsystemdUserManager, *, target_unit_name: str | None = None
    ) -> None:
        if target_unit_name is not None and _SLICE.fullmatch(target_unit_name) is None:
            raise SystemdRuntimeUnavailable("systemd JobRemoved target unit is invalid")
        self._manager = manager
        self._target_unit_name = target_unit_name
        self._slot = ctypes.c_void_p()
        self._events: list[_JobRemovedEvent] = []
        self._failure: SystemdRuntimeUnavailable | None = None
        self._closed = False
        self._callback = _SdBusMessageHandler(self._on_signal)
        manager._check(
            manager._library.sd_bus_add_match(
                manager._bus,
                ctypes.byref(self._slot),
                self._MATCH,
                self._callback,
                None,
            )
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._slot.value:
            self._manager._library.sd_bus_slot_unref(self._slot)
            self._slot = ctypes.c_void_p()

    def wait_for(self, *, job_path: str, unit_name: str, deadline_monotonic: float) -> str:
        match = _JOB_PATH.fullmatch(job_path)
        if match is None or _SLICE.fullmatch(unit_name) is None:
            raise SystemdRuntimeUnavailable("systemd JobRemoved binding is invalid")
        if self._target_unit_name is None:
            # Production binds the target before Start/Stop.  Keeping this
            # bounded deferred binding supports direct callback conformance
            # tests without making unrelated units target failures.
            self._target_unit_name = unit_name
        elif unit_name != self._target_unit_name:
            raise SystemdRuntimeUnavailable("systemd JobRemoved binding is invalid")
        expected_id = int(match.group(1))
        while True:
            if self._failure is not None:
                raise self._failure
            while self._events:
                event = self._events.pop(0)
                if event.unit_name != unit_name:
                    continue
                if event.job_path != job_path or event.job_id != expected_id:
                    raise SystemdRuntimeUnavailable("systemd JobRemoved binding differs")
                return event.result
            remaining = deadline_monotonic - time.monotonic()
            if remaining <= 0.0:
                raise SystemdRuntimeUnavailable("systemd JobRemoved did not arrive before deadline")
            processed = self._manager._library.sd_bus_process(self._manager._bus, None)
            self._manager._check(processed)
            if processed == 0:
                timeout_micros = max(1, int(remaining * 1_000_000))
                self._manager._check(
                    self._manager._library.sd_bus_wait(self._manager._bus, timeout_micros)
                )

    def _on_signal(
        self,
        message: ctypes.c_void_p,
        userdata: ctypes.c_void_p,
        error: object,
    ) -> int:
        del userdata, error
        try:
            event = self._manager._decode_job_removed(message)
            # The Manager broadcasts completions for unrelated services and
            # scopes on this same user bus.  The target slice is known before
            # the subscription is installed, so filter that ordinary traffic
            # before applying target job/path identity validation in wait_for.
            if self._target_unit_name is not None and event.unit_name != self._target_unit_name:
                return 0
            if self._target_unit_name is not None and self._events:
                raise SystemdRuntimeUnavailable("multiple JobRemoved signals for exact unit")
            if (
                self._target_unit_name is None
                and len(self._events) >= self._MAX_UNBOUND_BUFFERED_EVENTS
            ):
                raise SystemdRuntimeUnavailable("unbound JobRemoved callback buffer exceeded")
            self._events.append(event)
        except SystemdRuntimeUnavailable as exc:
            self._failure = exc
        return 0


class LibsystemdUserManager:
    """Concrete narrow libsystemd D-Bus client for only transient-slice methods.

    It opens an operator-configured AF_UNIX session bus, never runs a CLI or
    discovers a user manager from ambient environment. Task 5 supplies the
    actual bus/unit proof before an assembly may construct this client.
    """

    _TYPE_ARRAY = ord("a")
    _TYPE_STRUCT = ord("r")
    _TYPE_VARIANT = ord("v")
    _TYPE_STRING = ord("s")
    _TYPE_OBJECT_PATH = ord("o")
    _TYPE_BOOLEAN = ord("b")
    _TYPE_BYTE = ord("y")
    _TYPE_UINT32 = ord("u")

    def __init__(self, config: UserSystemdBusConfigV1) -> None:
        self._config = config
        self._verify_bus_socket()
        try:
            library = ctypes.CDLL("libsystemd.so.0")
        except OSError as exc:
            raise SystemdRuntimeUnavailable("libsystemd user D-Bus client is unavailable") from exc
        self._library = library
        self._configure_library()
        self._bus = ctypes.c_void_p()
        self._check(self._library.sd_bus_new(ctypes.byref(self._bus)))
        try:
            address = f"unix:path={config.socket_path}".encode()
            self._check(self._library.sd_bus_set_address(self._bus, address))
            self._check(self._library.sd_bus_set_bus_client(self._bus, 1))
            self._check(self._library.sd_bus_start(self._bus))
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        if getattr(self, "_bus", None) and self._bus.value:
            self._library.sd_bus_unref(self._bus)
            self._bus = ctypes.c_void_p()

    def start_transient_slice(
        self, *, unit_name: str, mode: str, properties: tuple[tuple[str, object], ...]
    ) -> SystemdTransientUnitV1:
        if mode != "fail" or _SLICE.fullmatch(unit_name) is None:
            raise SystemdRuntimeUnavailable("transient slice start literal is invalid")
        watch = self._install_job_removed_watch(unit_name)
        try:
            message = self._new_message("StartTransientUnit")
        except Exception:
            watch.close()
            raise
        try:
            deadline = self._operation_deadline()
            self._append_string(message, unit_name)
            self._append_string(message, mode)
            self._append_properties(message, properties)
            self._open(message, self._TYPE_ARRAY, b"(sa(sv))")
            self._close(message)
            reply = self._call(message, deadline_monotonic=deadline)
            try:
                job_path = self._read_basic(reply, self._TYPE_OBJECT_PATH)
            finally:
                self._library.sd_bus_message_unref(reply)
            return self._wait_for_exact_unit(unit_name, job_path, watch, deadline)
        finally:
            self._library.sd_bus_message_unref(message)
            watch.close()

    def inspect_exact(self, *, unit_name: str) -> SystemdTransientUnitV1 | None:
        if _SLICE.fullmatch(unit_name) is None:
            raise SystemdRuntimeUnavailable("transient slice name is invalid")
        try:
            unit_path = self._get_unit_path(unit_name)
        except _SystemdUnitMissing:
            return None
        return SystemdTransientUnitV1(
            unit_name=self._get_string_property(unit_path, "org.freedesktop.systemd1.Unit", "Id"),
            object_path=unit_path,
            control_group=self._get_string_property(
                unit_path, "org.freedesktop.systemd1.Slice", "ControlGroup"
            ),
            description=self._get_string_property(
                unit_path, "org.freedesktop.systemd1.Unit", "Description"
            ),
            slice_name=self._get_string_property(
                unit_path, "org.freedesktop.systemd1.Slice", "Slice"
            ),
            invocation_id=self._get_byte_array_property(
                unit_path, "org.freedesktop.systemd1.Unit", "InvocationID"
            ).hex(),
        )

    def stop_exact(self, *, unit_name: str) -> bool:
        if _SLICE.fullmatch(unit_name) is None:
            return False
        watch = self._install_job_removed_watch(unit_name)
        try:
            message = self._new_message("StopUnit")
        except Exception:
            watch.close()
            return False
        try:
            deadline = self._operation_deadline()
            self._append_string(message, unit_name)
            self._append_string(message, "fail")
            reply = self._call(message, deadline_monotonic=deadline)
            try:
                job_path = self._read_basic(reply, self._TYPE_OBJECT_PATH)
            finally:
                self._library.sd_bus_message_unref(reply)
            return self._wait_for_absence(unit_name, job_path, watch, deadline)
        except SystemdRuntimeUnavailable:
            return False
        finally:
            self._library.sd_bus_message_unref(message)
            watch.close()

    def _get_unit_path(self, unit_name: str) -> str:
        message = self._new_message("GetUnit")
        try:
            self._append_string(message, unit_name)
            reply = self._call(message)
            try:
                return self._read_basic(reply, self._TYPE_OBJECT_PATH)
            finally:
                self._library.sd_bus_message_unref(reply)
        finally:
            self._library.sd_bus_message_unref(message)

    def _get_string_property(self, object_path: str, interface: str, property_name: str) -> str:
        reply = self._get_unit_property(object_path, interface, property_name)
        try:
            self._check(
                self._library.sd_bus_message_enter_container(reply, self._TYPE_VARIANT, None)
            )
            value = self._read_basic(reply, self._TYPE_STRING)
            self._check(self._library.sd_bus_message_exit_container(reply))
            return value
        finally:
            self._library.sd_bus_message_unref(reply)

    def _get_byte_array_property(
        self, object_path: str, interface: str, property_name: str
    ) -> bytes:
        reply = self._get_unit_property(object_path, interface, property_name)
        try:
            self._check(
                self._library.sd_bus_message_enter_container(reply, self._TYPE_VARIANT, None)
            )
            pointer = ctypes.c_void_p()
            length = ctypes.c_size_t()
            self._check(
                self._library.sd_bus_message_read_array(
                    reply, self._TYPE_BYTE, ctypes.byref(pointer), ctypes.byref(length)
                )
            )
            self._check(self._library.sd_bus_message_exit_container(reply))
            if pointer.value is None or length.value != 16:
                raise SystemdRuntimeUnavailable("systemd InvocationID is invalid")
            return ctypes.string_at(pointer, length.value)
        finally:
            self._library.sd_bus_message_unref(reply)

    def _get_unit_property(
        self, object_path: str, interface: str, property_name: str
    ) -> ctypes.c_void_p:
        message = ctypes.c_void_p()
        self._check(
            self._library.sd_bus_message_new_method_call(
                self._bus,
                ctypes.byref(message),
                b"org.freedesktop.systemd1",
                object_path.encode("utf-8"),
                b"org.freedesktop.DBus.Properties",
                b"Get",
            )
        )
        try:
            self._append_string(message, interface)
            self._append_string(message, property_name)
            return self._call(message)
        finally:
            self._library.sd_bus_message_unref(message)

    def _new_message(self, member: str) -> ctypes.c_void_p:
        message = ctypes.c_void_p()
        self._check(
            self._library.sd_bus_message_new_method_call(
                self._bus,
                ctypes.byref(message),
                b"org.freedesktop.systemd1",
                b"/org/freedesktop/systemd1",
                b"org.freedesktop.systemd1.Manager",
                member.encode("ascii"),
            )
        )
        return message

    def _append_properties(
        self, message: ctypes.c_void_p, properties: tuple[tuple[str, object], ...]
    ) -> None:
        self._open(message, self._TYPE_ARRAY, b"(sv)")
        for name, value in properties:
            # libsystemd requires the explicit struct signature for 'r'; a NULL
            # contents string is refused with EINVAL.
            self._open(message, self._TYPE_STRUCT, b"sv")
            self._append_string(message, name)
            if isinstance(value, bool):
                self._open(message, self._TYPE_VARIANT, b"b")
                raw = ctypes.c_int(1 if value else 0)
                self._check(
                    self._library.sd_bus_message_append_basic(
                        message, self._TYPE_BOOLEAN, ctypes.byref(raw)
                    )
                )
            elif isinstance(value, str):
                self._open(message, self._TYPE_VARIANT, b"s")
                self._append_string(message, value)
            else:
                raise SystemdRuntimeUnavailable("transient slice property value is invalid")
            self._close(message)
            self._close(message)
        self._close(message)

    def _append_string(self, message: ctypes.c_void_p, value: str) -> None:
        encoded = ctypes.c_char_p(value.encode("utf-8"))
        self._check(self._library.sd_bus_message_append_basic(message, self._TYPE_STRING, encoded))

    def _install_job_removed_watch(self, unit_name: str) -> _JobRemovedWatch:
        return _JobRemovedWatch(self, target_unit_name=unit_name)

    def _wait_for_job_removed(
        self,
        *,
        watch: object,
        job_path: str,
        unit_name: str,
        deadline_monotonic: float | None = None,
    ) -> str:
        if _JOB_PATH.fullmatch(job_path) is None or _SLICE.fullmatch(unit_name) is None:
            raise SystemdRuntimeUnavailable("systemd manager did not return an exact job")
        wait_for = getattr(watch, "wait_for", None)
        if not callable(wait_for):
            raise SystemdRuntimeUnavailable("systemd JobRemoved subscription is unavailable")
        deadline = self._operation_deadline() if deadline_monotonic is None else deadline_monotonic
        if (
            type(deadline) is not float
            or not math.isfinite(deadline)
            or deadline <= time.monotonic()
        ):
            raise SystemdRuntimeUnavailable("systemd JobRemoved deadline is unavailable")
        result = wait_for(
            job_path=job_path,
            unit_name=unit_name,
            deadline_monotonic=deadline,
        )
        if result != "done":
            raise SystemdRuntimeUnavailable("systemd JobRemoved result is not done")
        return result

    def _wait_for_exact_unit(
        self, unit_name: str, job_path: str, watch: _JobRemovedWatch, deadline_monotonic: float
    ) -> SystemdTransientUnitV1:
        self._wait_for_job_removed(
            watch=watch,
            job_path=job_path,
            unit_name=unit_name,
            deadline_monotonic=deadline_monotonic,
        )
        inspected = self.inspect_exact(unit_name=unit_name)
        if inspected is None or inspected.unit_name != unit_name:
            raise SystemdRuntimeUnavailable("systemd started unit identity is unavailable")
        return inspected

    def _wait_for_absence(
        self,
        unit_name: str,
        job_path: str,
        watch: _JobRemovedWatch,
        deadline_monotonic: float,
    ) -> bool:
        try:
            self._wait_for_job_removed(
                watch=watch,
                job_path=job_path,
                unit_name=unit_name,
                deadline_monotonic=deadline_monotonic,
            )
            return self.inspect_exact(unit_name=unit_name) is None
        except SystemdRuntimeUnavailable:
            return False

    def _decode_job_removed(self, message: ctypes.c_void_p) -> _JobRemovedEvent:
        job_id = ctypes.c_uint32()
        self._check(
            self._library.sd_bus_message_read_basic(
                message, self._TYPE_UINT32, ctypes.byref(job_id)
            )
        )
        job_path = self._read_basic(message, self._TYPE_OBJECT_PATH)
        unit_name = self._read_basic(message, self._TYPE_STRING)
        result = self._read_basic(message, self._TYPE_STRING)
        return _JobRemovedEvent(
            job_id=job_id.value,
            job_path=job_path,
            unit_name=unit_name,
            result=result,
        )

    def _read_basic(self, message: ctypes.c_void_p, type_code: int) -> str:
        raw = ctypes.c_char_p()
        self._check(self._library.sd_bus_message_read_basic(message, type_code, ctypes.byref(raw)))
        if raw.value is None:
            raise SystemdRuntimeUnavailable("systemd D-Bus reply value is unavailable")
        try:
            return raw.value.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SystemdRuntimeUnavailable("systemd D-Bus reply value is invalid") from exc

    def _call(
        self, message: ctypes.c_void_p, *, deadline_monotonic: float | None = None
    ) -> ctypes.c_void_p:
        timeout_micros = self._config.timeout_micros
        if deadline_monotonic is not None:
            if type(deadline_monotonic) is not float or not math.isfinite(deadline_monotonic):
                raise SystemdRuntimeUnavailable("user systemd D-Bus deadline is invalid")
            remaining = deadline_monotonic - time.monotonic()
            if remaining <= 0:
                raise SystemdRuntimeUnavailable("user systemd D-Bus deadline expired")
            timeout_micros = max(1, int(remaining * 1_000_000))
        reply = ctypes.c_void_p()
        error = _SdBusError()
        result = self._library.sd_bus_call(
            self._bus,
            message,
            timeout_micros,
            ctypes.byref(error),
            ctypes.byref(reply),
        )
        try:
            if result < 0:
                if error.name == b"org.freedesktop.systemd1.NoSuchUnit":
                    raise _SystemdUnitMissing("exact transient slice is absent")
                raise SystemdRuntimeUnavailable("user systemd D-Bus operation failed")
            return reply
        finally:
            self._library.sd_bus_error_free(ctypes.byref(error))

    def _operation_deadline(self) -> float:
        return time.monotonic() + self._config.timeout_micros / 1_000_000

    def _open(self, message: ctypes.c_void_p, type_code: int, contents: bytes | None) -> None:
        self._check(self._library.sd_bus_message_open_container(message, type_code, contents))

    def _close(self, message: ctypes.c_void_p) -> None:
        self._check(self._library.sd_bus_message_close_container(message))

    def _verify_bus_socket(self) -> None:
        try:
            observed = os.lstat(self._config.socket_path)
        except OSError as exc:
            raise SystemdRuntimeUnavailable("provisioned user systemd bus is unavailable") from exc
        if (
            not stat.S_ISSOCK(observed.st_mode)
            or observed.st_uid != self._config.expected_owner_uid
            or (observed.st_mode & 0o777) != self._config.expected_mode
        ):
            raise SystemdRuntimeUnavailable("provisioned user systemd bus identity is invalid")

    def _configure_library(self) -> None:
        pointer = ctypes.c_void_p
        character = ctypes.c_char_p
        integer = ctypes.c_int
        self._library.sd_bus_new.argtypes = [ctypes.POINTER(pointer)]
        self._library.sd_bus_new.restype = integer
        self._library.sd_bus_set_address.argtypes = [pointer, character]
        self._library.sd_bus_set_address.restype = integer
        self._library.sd_bus_set_bus_client.argtypes = [pointer, integer]
        self._library.sd_bus_set_bus_client.restype = integer
        self._library.sd_bus_start.argtypes = [pointer]
        self._library.sd_bus_start.restype = integer
        self._library.sd_bus_unref.argtypes = [pointer]
        self._library.sd_bus_unref.restype = pointer
        self._library.sd_bus_message_new_method_call.argtypes = [
            pointer,
            ctypes.POINTER(pointer),
            character,
            character,
            character,
            character,
        ]
        self._library.sd_bus_message_new_method_call.restype = integer
        self._library.sd_bus_message_unref.argtypes = [pointer]
        self._library.sd_bus_message_unref.restype = pointer
        self._library.sd_bus_message_append_basic.argtypes = [pointer, integer, pointer]
        self._library.sd_bus_message_append_basic.restype = integer
        self._library.sd_bus_message_open_container.argtypes = [pointer, integer, character]
        self._library.sd_bus_message_open_container.restype = integer
        self._library.sd_bus_message_close_container.argtypes = [pointer]
        self._library.sd_bus_message_close_container.restype = integer
        self._library.sd_bus_message_enter_container.argtypes = [pointer, integer, character]
        self._library.sd_bus_message_enter_container.restype = integer
        self._library.sd_bus_message_exit_container.argtypes = [pointer]
        self._library.sd_bus_message_exit_container.restype = integer
        self._library.sd_bus_message_read_basic.argtypes = [pointer, integer, pointer]
        self._library.sd_bus_message_read_basic.restype = integer
        self._library.sd_bus_message_read_array.argtypes = [
            pointer,
            integer,
            ctypes.POINTER(pointer),
            ctypes.POINTER(ctypes.c_size_t),
        ]
        self._library.sd_bus_message_read_array.restype = integer
        self._library.sd_bus_call.argtypes = [
            pointer,
            pointer,
            ctypes.c_uint64,
            ctypes.POINTER(_SdBusError),
            ctypes.POINTER(pointer),
        ]
        self._library.sd_bus_call.restype = integer
        self._library.sd_bus_error_free.argtypes = [ctypes.POINTER(_SdBusError)]
        self._library.sd_bus_error_free.restype = None
        self._library.sd_bus_add_match.argtypes = [
            pointer,
            ctypes.POINTER(pointer),
            character,
            _SdBusMessageHandler,
            pointer,
        ]
        self._library.sd_bus_add_match.restype = integer
        self._library.sd_bus_slot_unref.argtypes = [pointer]
        self._library.sd_bus_slot_unref.restype = pointer
        self._library.sd_bus_process.argtypes = [pointer, ctypes.POINTER(pointer)]
        self._library.sd_bus_process.restype = integer
        self._library.sd_bus_wait.argtypes = [pointer, ctypes.c_uint64]
        self._library.sd_bus_wait.restype = integer

    @staticmethod
    def _check(result: int) -> None:
        if result < 0:
            raise SystemdRuntimeUnavailable("user systemd D-Bus operation failed")


class SystemdTransientSliceController:
    """Binds and later retires only the journaled user-systemd attempt slice."""

    _receipt_type: ClassVar[type[RuntimeParentReceiptV1]] = RuntimeParentReceiptV1
    _description_prefix: ClassVar[str] = "ksi-external-inspector-attempt.v1:"

    def __init__(
        self,
        *,
        manager: SystemdUserManagerPort,
        cgroups: CgroupV2RootV1,
        runtime_lifecycle: DockerRuntimeLifecyclePort,
        proc_cgroups: ProcCgroupReaderPort,
        config: SystemdTransientSliceConfigV1,
    ) -> None:
        self._manager = manager
        self._cgroups = cgroups
        self._runtime_lifecycle = runtime_lifecycle
        self._proc_cgroups = proc_cgroups
        self._config = config
        self._cleanup_timeout_seconds = config.cleanup_timeout_millis / 1_000.0

    def bind_before_create(
        self,
        *,
        binding: ExactRuntimeBindingPort,
        configuration: FixedContainerConfigurationV1,
    ) -> RuntimeParentReceiptV1:
        self._require_namespace(binding)
        if binding.systemd_base_slice != self._config.base_slice_name:
            raise SystemdRuntimeUnavailable(
                "journaled systemd base slice does not match operator config"
            )
        if _SLICE.fullmatch(binding.systemd_slice_name) is None:
            raise SystemdRuntimeUnavailable("journaled systemd attempt slice is invalid")
        unit = self._manager.start_transient_slice(
            unit_name=binding.systemd_slice_name,
            mode="fail",
            properties=(
                ("Description", _binding_description(binding)),
                # systemd refuses Slice= on slice units: the parent of
                # ksi-inspector-a<stable>.slice is name-derived and must be
                # exactly the configured base slice (verified below).
                ("CPUAccounting", True),
                ("MemoryAccounting", True),
                ("TasksAccounting", True),
                ("StopWhenUnneeded", False),
                ("CollectMode", "inactive-or-failed"),
            ),
        )
        self._require_exact_unit(binding, unit)
        if configuration.cpu_budget_counter != binding.cpu_budget_counter:
            raise SystemdRuntimeUnavailable("fixed CPU budget differs from durable attempt binding")
        return self._receipt_for_fresh_parent(
            binding, unit, cpu_budget_counter=binding.cpu_budget_counter
        )

    def adopt_if_prebound(
        self, *, binding: ExactRuntimeBindingPort
    ) -> RuntimeParentReceiptV1 | None:
        """Durably adopt only the INPUT_BOUND pre-receipt crash window.

        Docker create cannot have happened before this receipt.  A present unit
        must therefore still be empty and carry the exact INTENDED digest marker.
        """
        self._require_namespace(binding)
        if binding.systemd_base_slice != self._config.base_slice_name:
            raise SystemdRuntimeUnavailable(
                "journaled systemd base slice does not match operator config"
            )
        unit = self._manager.inspect_exact(unit_name=binding.systemd_slice_name)
        if unit is None:
            return None
        self._require_exact_unit(binding, unit)
        return self._receipt_for_fresh_parent(
            binding, unit, cpu_budget_counter=binding.cpu_budget_counter
        )

    def _require_namespace(self, binding: ExactRuntimeBindingPort) -> None:
        if binding.runtime_description != self._description_prefix + binding.digest:
            raise SystemdRuntimeUnavailable("attempt belongs to a different runtime namespace")

    def _require_exact_unit(
        self, binding: ExactRuntimeBindingPort, unit: SystemdTransientUnitV1
    ) -> None:
        if (
            unit.unit_name != binding.systemd_slice_name
            or unit.description != _binding_description(binding)
            or unit.slice_name != binding.systemd_base_slice
        ):
            raise SystemdRuntimeUnavailable("user manager returned a different transient slice")

    def _receipt_for_fresh_parent(
        self,
        binding: ExactRuntimeBindingPort,
        unit: SystemdTransientUnitV1,
        *,
        cpu_budget_counter: int,
    ) -> RuntimeParentReceiptV1:
        try:
            attempt = self._cgroups.open_attempt_slice(
                control_group=unit.control_group,
                expected_slice_name=binding.systemd_slice_name,
            )
            try:
                attempt.verify_required_controllers()
                if not attempt.is_unpopulated() or not attempt.has_no_child_cgroups():
                    raise SystemdRuntimeUnavailable("fresh attempt slice is already populated")
                identity = attempt.identity()
                baseline = attempt.read_aggregate_cpu()
            finally:
                attempt.close()
        except DockerRuntimeUnavailable as exc:
            raise SystemdRuntimeUnavailable("transient slice cgroup proof is unavailable") from exc
        return self._receipt_type(
            unit_name=unit.unit_name,
            object_path=unit.object_path,
            description=unit.description,
            slice_name=unit.slice_name,
            control_group=unit.control_group,
            invocation_id=unit.invocation_id,
            device=identity.st_dev,
            inode=identity.st_ino,
            controllers=("cpu", "memory", "pids"),
            cpu_counter_unit=baseline.unit.value,
            baseline_cpu_counter=baseline.value,
            cpu_budget_counter=cpu_budget_counter,
        )

    def verify_before_quiesce(
        self, *, binding: ExactRuntimeBindingPort, receipt: RuntimeParentReceiptV1, runtime_id: str
    ) -> bool:
        """Prove current parent identity and the Engine lifecycle before a bounded kill/wait."""
        if not runtime_id or not self._matches_recorded_parent(binding, receipt):
            return False
        try:
            lifecycle, pid = self._read_runtime_lifecycle(runtime_id)
            attempt = self._open_recorded_parent(binding, receipt)
            try:
                if lifecycle == "CREATED":
                    return self._empty_parent_at_baseline(attempt, receipt)
                if lifecycle == "RUNNING":
                    return self._verify_running_scope(
                        attempt=attempt,
                        receipt=receipt,
                        runtime_id=runtime_id,
                        pid=pid,
                    )
                if lifecycle == "EXITED":
                    return attempt.is_unpopulated() and self._verify_exited_child(
                        attempt=attempt, runtime_id=runtime_id
                    )
                return False
            finally:
                attempt.close()
        except (DockerRuntimeUnavailable, SystemdRuntimeUnavailable):
            return False

    def stop_exact(
        self, *, binding: ExactRuntimeBindingPort, receipt: RuntimeParentReceiptV1
    ) -> bool:
        if (
            binding.runtime_description != self._description_prefix + binding.digest
            or receipt.unit_name != binding.systemd_slice_name
            or receipt.control_group == ""
            or binding.systemd_base_slice != self._config.base_slice_name
        ):
            return False
        try:
            current = self._manager.inspect_exact(unit_name=receipt.unit_name)
        except SystemdRuntimeUnavailable:
            return False
        if current is None:
            return False
        if (
            current.object_path != receipt.object_path
            or current.control_group != receipt.control_group
            or current.description != _binding_description(binding)
            or current.slice_name != binding.systemd_base_slice
            or current.invocation_id != receipt.invocation_id
        ):
            return False
        try:
            attempt = self._cgroups.open_attempt_slice(
                control_group=receipt.control_group,
                expected_slice_name=receipt.unit_name,
            )
            try:
                identity = attempt.identity()
                if identity.st_dev != receipt.device or identity.st_ino != receipt.inode:
                    return False
                attempt.verify_required_controllers()
                if not attempt.is_unpopulated() or not attempt.has_no_child_cgroups():
                    return False
            finally:
                attempt.close()
        except DockerRuntimeUnavailable:
            return False
        if self._manager.stop_exact(unit_name=receipt.unit_name) is not True:
            return False
        try:
            return self._manager.inspect_exact(unit_name=receipt.unit_name) is None
        except SystemdRuntimeUnavailable:
            return False

    def verify_final_before_remove(
        self, *, binding: ExactRuntimeBindingPort, receipt: RuntimeParentReceiptV1, runtime_id: str
    ) -> bool:
        """Require a re-read nonrunning Engine fact and stable bounded parent accounting."""
        if not runtime_id or not self._matches_recorded_parent(binding, receipt):
            return False
        try:
            lifecycle, _pid = self._read_runtime_lifecycle(runtime_id)
            if lifecycle == "RUNNING":
                return False
            attempt = self._open_recorded_parent(binding, receipt)
            try:
                if lifecycle == "CREATED":
                    if not self._empty_parent_at_baseline(attempt, receipt):
                        return False
                elif lifecycle == "EXITED":
                    if not attempt.is_unpopulated() or not self._verify_exited_child(
                        attempt=attempt, runtime_id=runtime_id
                    ):
                        return False
                else:
                    return False
                return self._stable_final_cpu(attempt, receipt)
            finally:
                attempt.close()
        except (DockerRuntimeUnavailable, SystemdRuntimeUnavailable):
            return False

    def _read_runtime_lifecycle(
        self, runtime_id: str
    ) -> tuple[Literal["CREATED", "RUNNING", "EXITED"], int | None]:
        try:
            lifecycle = self._runtime_lifecycle
            cleanup_timeout_seconds = self._cleanup_timeout_seconds
        except AttributeError as exc:
            raise SystemdRuntimeUnavailable(
                "exact Docker lifecycle adapter is unavailable"
            ) from exc
        inspected = lifecycle.inspect_exact(
            runtime_id,
            deadline_monotonic=time.monotonic() + cleanup_timeout_seconds,
        )
        state = inspected.get("State")
        if not isinstance(state, Mapping):
            raise SystemdRuntimeUnavailable("exact Docker lifecycle state is unavailable")
        running = state.get("Running")
        status = state.get("Status")
        pid = state.get("Pid")
        if type(running) is not bool or not isinstance(status, str) or type(pid) is not int:
            raise SystemdRuntimeUnavailable("exact Docker lifecycle state is invalid")
        if running is True:
            if status != "running" or pid <= 0:
                raise SystemdRuntimeUnavailable("running Docker lifecycle is invalid")
            return "RUNNING", pid
        if status == "created" and pid == 0:
            return "CREATED", None
        if status == "exited" and pid == 0:
            return "EXITED", None
        raise SystemdRuntimeUnavailable("nonrunning Docker lifecycle is not proven")

    @staticmethod
    def _empty_parent_at_baseline(
        attempt: CgroupV2AttemptSlice, receipt: RuntimeParentReceiptV1
    ) -> bool:
        counter = attempt.read_aggregate_cpu()
        return (
            attempt.is_unpopulated()
            and attempt.has_no_child_cgroups()
            and counter.unit is CpuCounterUnitV1.CPU_USEC
            and counter.complete_process_tree is True
            and counter.value == receipt.baseline_cpu_counter
        )

    def _verify_running_scope(
        self,
        *,
        attempt: CgroupV2AttemptSlice,
        receipt: RuntimeParentReceiptV1,
        runtime_id: str,
        pid: int | None,
    ) -> bool:
        if pid is None:
            return False
        scope_name = f"docker-{runtime_id}.scope"
        scope = attempt.open_only_scope(expected_scope_name=scope_name)
        scope.close()
        expected_path = receipt.control_group + "/" + scope_name
        return self._proc_cgroups.read_cgroup_path(pid) == expected_path

    @staticmethod
    def _verify_exited_child(*, attempt: CgroupV2AttemptSlice, runtime_id: str) -> bool:
        if attempt.has_no_child_cgroups():
            return True
        scope = attempt.open_only_scope(expected_scope_name=f"docker-{runtime_id}.scope")
        scope.close()
        return True

    def _stable_final_cpu(
        self, attempt: CgroupV2AttemptSlice, receipt: RuntimeParentReceiptV1
    ) -> bool:
        samples = [attempt.read_aggregate_cpu() for _ in range(self._config.stable_final_samples)]
        return (
            receipt.cpu_counter_unit == "CPU_USEC"
            and samples[0].value >= receipt.baseline_cpu_counter
            and samples[0].value - receipt.baseline_cpu_counter <= receipt.cpu_budget_counter
            and all(sample == samples[0] for sample in samples[1:])
        )

    def _matches_recorded_parent(
        self, binding: ExactRuntimeBindingPort, receipt: RuntimeParentReceiptV1
    ) -> bool:
        if (
            binding.runtime_description != self._description_prefix + binding.digest
            or receipt.unit_name != binding.systemd_slice_name
            or receipt.description != _binding_description(binding)
            or receipt.slice_name != self._config.base_slice_name
            or binding.systemd_base_slice != self._config.base_slice_name
        ):
            return False
        current = self._manager.inspect_exact(unit_name=receipt.unit_name)
        return current is not None and (
            current.object_path == receipt.object_path
            and current.control_group == receipt.control_group
            and current.description == receipt.description
            and current.slice_name == receipt.slice_name
            and current.invocation_id == receipt.invocation_id
        )

    def _open_recorded_parent(
        self, binding: ExactRuntimeBindingPort, receipt: RuntimeParentReceiptV1
    ) -> CgroupV2AttemptSlice:
        if not self._matches_recorded_parent(binding, receipt):
            raise SystemdRuntimeUnavailable("runtime parent identity has changed")
        attempt = self._cgroups.open_attempt_slice(
            control_group=receipt.control_group,
            expected_slice_name=receipt.unit_name,
        )
        try:
            identity = attempt.identity()
            if identity.st_dev != receipt.device or identity.st_ino != receipt.inode:
                raise SystemdRuntimeUnavailable("runtime parent cgroup identity has changed")
            attempt.verify_required_controllers()
            return attempt
        except Exception:
            attempt.close()
            raise


def _binding_description(binding: ExactRuntimeBindingPort) -> str:
    return binding.runtime_description


__all__ = [
    "LibsystemdUserManager",
    "SystemdRuntimeUnavailable",
    "SystemdTransientSliceConfigV1",
    "SystemdTransientSliceController",
    "SystemdTransientUnitV1",
    "UserSystemdBusConfigV1",
]
