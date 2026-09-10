"""Read-only exact runtime identity shared by versioned local attempt journals."""

from typing import Protocol


class ExactRuntimeBindingPort(Protocol):
    @property
    def attempt_nonce(self) -> str: ...

    @property
    def owner(self) -> str: ...

    @property
    def container_name(self) -> str: ...

    @property
    def systemd_slice_name(self) -> str: ...

    @property
    def systemd_base_slice(self) -> str: ...

    @property
    def execution_manifest_digest(self) -> str: ...

    @property
    def oci_manifest_digest(self) -> str: ...

    @property
    def oci_config_digest(self) -> str: ...

    @property
    def backend_profile_digest(self) -> str: ...

    @property
    def security_profile_digest(self) -> str: ...

    @property
    def resource_envelope_digest(self) -> str: ...

    @property
    def inspector_protocol_digest(self) -> str: ...

    @property
    def cpu_budget_counter(self) -> int: ...

    @property
    def digest(self) -> str: ...

    @property
    def runtime_description(self) -> str: ...
