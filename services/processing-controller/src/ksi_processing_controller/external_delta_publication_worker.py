"""Late-export output worker: one publication lease to verified bytes.

This is the new output job, not the V2 Analysis worker. It consumes exactly
one Core-issued late-export input for one live publication lease and returns
exactly one observed FLOAT64 delta output:

- Core handshake (all closed, bounded, bearer-authenticated): acquire the
  publication upload lease, fetch the server-issued late-export input (exact
  sealed V2 identity + numeric + two DSM capabilities bound to the lease),
  post the observed output body, upload the raw octet-stream bytes, or record
  a typed failure. No V2 analysis attempt is leased, renewed, reported, or
  treated as live; the old COMPLETED numeric report is evidence only.
- Object downloads use the existing pinned-origin bounded transport
  (``ExternalObjectHttpByteSource`` with an operator-owned
  ``ExternalObjectTransportPolicyV1``). No DNS, proxy, redirect, cookie, or
  caller-supplied URL is accepted: the origin allow-list is explicit worker
  configuration, and every byte is hash/size verified against the sealed
  identity before measurement.
- Native measurement runs inside the separately verified contained runtime
  via :func:`reproduce_external_delta_raster_v2`, which reuses the owned DSM
  reader plus the shared align algorithm and verifies the exact grid, array
  metrics, coverage, and NaN handling against the ORIGINAL numeric result.
  The observed output body is parsed from the actual emitted TIFF (dtype,
  grid, transform, CRS, bounds, hash, size), never from caller claims.
- Currentness, expiry, deadline, and cancel are guarded at every stage: lease
  expiry, capability expiry, publication expiry, wall deadline, and the
  caller-supplied cancel/currentness callbacks abort the job closed with a
  typed failure posted when a lease is held. A late export never fabricates a
  V2 admission/authorization and never rewrites Core numeric state.

Network/host note: the Core and object transports are real software
transports (HTTP/1.1 over pinned loopback-allowed origins with bounded
headers, sizes, and deadlines). Activating them against a deployment network
still requires explicit host provisioning (trusted origin literals plus a
bearer token supplied by the operator); this module provides no defaults,
reads no environment, and never falls back to ambient credentials. The
factory below is opt-in and runtime-explicit for that reason.

Software proof and limits: local generated tests prove the real software
handshake (Core HTTP lease/input/observation/bytes plus pinned object
downloads plus native re-measurement) over loopback servers. That proves the
bytes and protocol only: it claims no OS sandbox, no host provisioning, and
no deployment containment. The separately verified contained runtime remains
operator-owned; this helper only runs inside it when explicitly configured.
"""

from __future__ import annotations

import hashlib
import ipaddress
import math
import os
import re
import stat
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import quote, urlsplit

import httpx
import rasterio
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import ResourceEnvelopeV1
from ksi_event_contracts.external_delta_publication_api import (
    DeltaOutputObservationWireV1,
    DeltaPublicationIntentViewV1,
    DeltaPublicationViewV1,
    SourceVersion,
)
from ksi_event_contracts.external_delta_publication_worker import (
    DeltaPublicationMaskedWorkerInputV1,
    DeltaPublicationPendingPageV1,
    DeltaPublicationWorkerInputCapabilityV1,
    DeltaPublicationWorkerInputV1,
)
from pydantic import ValidationError

from ksi_processing_controller.external_delta_reproduction_measurement import (
    ReproductionMeasurementError,
    reproduce_external_delta_raster_v2,
    reproduce_masked_delta_raster_v3,
)
from ksi_processing_controller.external_inspector_protocol import (
    ProtocolDeadline,
    ProtocolDeadlineExceeded,
    ProtocolViolation,
)
from ksi_processing_controller.external_measurement_algorithms import (
    MeasurementAlgorithmIncomplete,
    MeasurementWatchdogV2,
)
from ksi_processing_controller.external_measurement_protocol import MeasurementInputV2
from ksi_processing_controller.external_object_streams import (
    ExternalObjectCapabilityV1,
    ExternalObjectHttpByteSource,
    ExternalObjectTransportError,
    ExternalObjectTransportPolicyV1,
)

_JOB_ID_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.:")
_JOB_ID_SAFE_PUBLICATION_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_FAILURE_CODE_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")

#: Closed discovery source versions: the exact Core contract strings, never
#: guessed. ``None`` preserves the legacy unfiltered page for compat.
_DISCOVERY_SOURCE_VERSIONS = (
    "external-relative-volume-calculation-report.v2",
    "external-masked-volume-calculation-identity.v3",
)
_V2_SOURCE_CONTRACT_VERSION = "external-relative-volume-calculation-report.v2"
_MASKED_SOURCE_CONTRACT_VERSION = "external-masked-volume-calculation-identity.v3"


class DeltaPublicationWorkerError(RuntimeError):
    """Safe worker failure code without Core text, URLs, or bearer values."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _resource_id(value: object, field: str) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > 255
        or any(c not in _JOB_ID_CHARS for c in value)
    ):
        raise DeltaPublicationWorkerError(f"INVALID_{field}")
    return value


def _publication_id(value: object) -> str:
    """Narrow publication identifier: Core-safe `[A-Za-z0-9_-]`, never a path.

    The worker interpolates this value into URL path segments, so dots and
    colons are rejected even though the general job-id alphabet allows them
    elsewhere: a value such as ``..`` must never become a traversable path
    segment. Every interpolated segment is additionally percent-quoted.
    """
    if type(value) is not str or _JOB_ID_SAFE_PUBLICATION_RE.fullmatch(value) is None:
        raise DeltaPublicationWorkerError("INVALID_PUBLICATION")
    return value


def _failure_code(value: str) -> str:
    if (
        type(value) is not str
        or not 1 <= len(value) <= 128
        or value[0] not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        or any(c not in _FAILURE_CODE_CHARS for c in value)
    ):
        raise DeltaPublicationWorkerError("INVALID_FAILURE_REASON")
    return value


def _trusted_base_url(value: object) -> str:
    if type(value) is not str or not value or len(value) > 16384:
        raise ValueError("Core base URL is malformed")
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or any(ord(c) <= 32 for c in value)
        ):
            raise ValueError
        _ = parsed.port
        address = ipaddress.ip_address(parsed.hostname)
        if "%" in parsed.hostname or getattr(address, "scope_id", None) is not None:
            raise ValueError
        if parsed.scheme == "http" and not address.is_loopback:
            raise ValueError
        if any(segment in {"", ".", ".."} for segment in parsed.path.split("/")[1:]):
            raise ValueError
    except ValueError:
        raise ValueError(
            "Core base URL must use an explicit trusted literal IP HTTP(S) origin"
        ) from None
    return value.rstrip("/")


def _token(value: object) -> str:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or any(ord(c) <= 32 or ord(c) > 126 for c in value)
    ):
        raise ValueError("worker token is malformed")
    return value


@dataclass(frozen=True, slots=True)
class DeltaPublicationWorkerConfig:
    """Explicit opt-in runtime for one late-export job site.

    No defaults, no environment: every origin, bearer, identity, bound, and
    deadline is supplied by the operator for the verified contained runtime.
    """

    core_base_url: str
    core_bearer_token: str
    worker_instance_id: str
    publication_id: str
    lease_acquisition_id: str
    transport_policy: ExternalObjectTransportPolicyV1
    work_dir: Path
    envelope: ResourceEnvelopeV1
    maximum_output_bytes: int
    maximum_grid_cells: int
    maximum_response_bytes: int = 262_144
    request_timeout_seconds: float = 5.0
    max_chunk_bytes: int = 65_536
    heartbeat_interval_millis: int = 25

    def __post_init__(self) -> None:
        _trusted_base_url(self.core_base_url)
        _token(self.core_bearer_token)
        _resource_id(self.worker_instance_id, "WORKER_INSTANCE")
        _publication_id(self.publication_id)
        _resource_id(self.lease_acquisition_id, "LEASE_ACQUISITION")
        if not isinstance(self.transport_policy, ExternalObjectTransportPolicyV1):
            raise ValueError("worker requires an explicit pinned object transport policy")
        if not isinstance(self.work_dir, Path):
            raise ValueError("worker requires an explicit work directory")
        if not isinstance(self.envelope, ResourceEnvelopeV1):
            raise ValueError("worker requires a sealed resource envelope")
        if self.envelope.resource_envelope_digest is None or (
            self.envelope.resource_envelope_digest != self.envelope.canonical_digest()
        ):
            raise ValueError("worker requires a sealed resource envelope")
        for name in ("maximum_output_bytes", "maximum_grid_cells", "maximum_response_bytes"):
            value = getattr(self, name)
            if isinstance(value, bool) or type(value) is not int or value <= 0:
                raise ValueError(f"worker {name} must be a positive integer")
        if (
            isinstance(self.request_timeout_seconds, bool)
            or not math.isfinite(self.request_timeout_seconds)
            or not 0 < self.request_timeout_seconds <= 120
        ):
            raise ValueError("worker request timeout is invalid")
        if type(self.max_chunk_bytes) is not int or self.max_chunk_bytes <= 0:
            raise ValueError("worker chunk cap is invalid")
        if type(self.heartbeat_interval_millis) is not int or self.heartbeat_interval_millis <= 0:
            raise ValueError("worker heartbeat is invalid")


class DeltaPublicationCoreClient:
    """Bounded authenticated HTTP for the closed publication worker lane.

    Owns only its six worker calls; object bytes travel through the separate
    pinned object transport and are never logged here.
    """

    def __init__(
        self,
        *,
        base_url: str,
        bearer_token: str,
        maximum_response_bytes: int = 262_144,
        request_timeout_seconds: float = 5.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = _trusted_base_url(base_url) + "/"
        self._token = _token(bearer_token)
        if (
            type(maximum_response_bytes) is not int
            or not 128 <= maximum_response_bytes <= 4_194_304
        ):
            raise ValueError("Core response byte cap is invalid")
        if (
            isinstance(request_timeout_seconds, bool)
            or not math.isfinite(request_timeout_seconds)
            or not 0 < request_timeout_seconds <= 120
        ):
            raise ValueError("Core request timeout is invalid")
        self._maximum_response_bytes = maximum_response_bytes
        self._timeout = request_timeout_seconds
        self._client = httpx.Client(
            base_url=self._base_url,
            transport=transport,
            trust_env=False,
            follow_redirects=False,
            headers={"Authorization": f"Bearer {self._token}", "Accept-Encoding": "identity"},
        )
        self._closed = False

    def close(self) -> None:
        self._closed = True
        self._client.close()

    def __enter__(self) -> DeltaPublicationCoreClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str | int] | None = None,
        headers: dict[str, str] | None = None,
        body: dict | None = None,
        raw: bytes | None = None,
        content_type: str | None = None,
        accepted: tuple[int, ...] = (200,),
    ) -> tuple[int, bytes]:
        if self._closed:
            raise DeltaPublicationWorkerError("CLIENT_CLOSED")
        try:
            with self._client.stream(
                method,
                path,
                params=params,
                headers=headers,
                json=body,
                content=raw,
                timeout=self._timeout,
            ) as response:
                if response.status_code not in accepted:
                    raise DeltaPublicationWorkerError(f"CORE_HTTP_{response.status_code}")
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise DeltaPublicationWorkerError("ENCODED_CORE_RESPONSE")
                data = bytearray()
                for chunk in response.iter_bytes():
                    if len(data) + len(chunk) > self._maximum_response_bytes:
                        raise DeltaPublicationWorkerError("CORE_RESPONSE_LIMIT")
                    data.extend(chunk)
                _ = content_type
                return response.status_code, bytes(data)
        except DeltaPublicationWorkerError:
            raise
        except (httpx.TimeoutException, TimeoutError):
            raise DeltaPublicationWorkerError("CORE_HTTP_TIMEOUT") from None
        except httpx.HTTPError:
            raise DeltaPublicationWorkerError("CORE_HTTP_UNAVAILABLE") from None

    def discover_pending(
        self, limit: int = 50, source_contract_version: SourceVersion | None = None
    ) -> DeltaPublicationPendingPageV1:
        """Fetch the bounded worker-visible discovery page.

        With ``source_contract_version`` set, Core filters to that lane's
        pending ids before its limit/lease checks; omitted, the legacy
        unfiltered page is returned for compat. Returns only opaque
        publication ids each still requiring their own lease plus
        server-issued input before any download. Unknown fields, oversized
        or over-limit pages, repeated ids, non-opaque ids, and unknown
        source versions fail closed.
        """
        import json

        if type(limit) is not int or isinstance(limit, bool) or limit < 1 or limit > 50:
            raise DeltaPublicationWorkerError("INVALID_DISCOVERY_LIMIT")
        params: dict[str, str | int] = {"limit": limit}
        if source_contract_version is None:
            pass
        elif source_contract_version in _DISCOVERY_SOURCE_VERSIONS:
            params["source_contract_version"] = source_contract_version
        else:
            raise DeltaPublicationWorkerError("INVALID_DISCOVERY_FILTER")
        _, data = self._request(
            "GET",
            "v1/internal/delta-publication-uploads",
            params=params,
        )
        try:
            decoded = json.loads(data)
        except Exception:
            raise DeltaPublicationWorkerError("INVALID_CORE_RESPONSE") from None
        try:
            page = DeltaPublicationPendingPageV1.model_validate(decoded)
        except ValidationError:
            raise DeltaPublicationWorkerError("INVALID_CORE_RESPONSE") from None
        if len(page.publication_ids) > limit:
            raise DeltaPublicationWorkerError("INVALID_CORE_RESPONSE")
        return page

    def acquire_lease(
        self, publication_id: str, *, worker_instance_id: str, lease_acquisition_id: str
    ) -> dict:
        import json

        pid = _publication_id(publication_id)
        _, data = self._request(
            "POST",
            f"v1/internal/delta-publication-uploads/{quote(pid, safe='')}/lease",
            headers={"Content-Type": "application/json"},
            body={
                "workerInstanceId": _resource_id(worker_instance_id, "WORKER_INSTANCE"),
                "leaseAcquisitionId": _resource_id(lease_acquisition_id, "LEASE_ACQUISITION"),
            },
        )
        try:
            decoded = json.loads(data)
        except Exception:
            raise DeltaPublicationWorkerError("INVALID_CORE_RESPONSE") from None
        try:
            view = DeltaPublicationIntentViewV1.model_validate(decoded)
        except ValidationError:
            raise DeltaPublicationWorkerError("INVALID_CORE_RESPONSE") from None
        if (
            view.publication_id != pid
            or view.lease_generation < 1
            or view.lease_holder_instance_id != worker_instance_id
            or view.status != "PENDING"
        ):
            raise DeltaPublicationWorkerError("LEASE_BINDING_MISMATCH")
        return view.model_dump(by_alias=True, mode="json")

    def fetch_input(
        self, publication_id: str, *, worker_instance_id: str
    ) -> DeltaPublicationWorkerInputV1:
        import json

        pid = _publication_id(publication_id)
        _, data = self._request(
            "GET",
            f"v1/internal/delta-publication-uploads/{quote(pid, safe='')}/input",
            params={"worker_instance_id": _resource_id(worker_instance_id, "WORKER_INSTANCE")},
        )
        try:
            decoded = json.loads(data)
        except Exception:
            raise DeltaPublicationWorkerError("INVALID_CORE_RESPONSE") from None
        try:
            inner = (
                decoded["input"] if isinstance(decoded, dict) and "input" in decoded else decoded
            )
            worker_input = DeltaPublicationWorkerInputV1.model_validate(inner)
        except (ValidationError, ValueError, TypeError, KeyError):
            raise DeltaPublicationWorkerError("INVALID_CORE_RESPONSE") from None
        if worker_input.publication_id != pid or worker_input.worker_instance_id != (
            worker_instance_id
        ):
            raise DeltaPublicationWorkerError("INPUT_BINDING_MISMATCH")
        return worker_input

    def fetch_masked_input(
        self, publication_id: str, *, worker_instance_id: str
    ) -> DeltaPublicationMaskedWorkerInputV1:
        """Fetch the server-issued V3 late-export input for one live lease.

        Closed ``DeltaPublicationMaskedWorkerInputV1`` validation plus
        publication/instance binding; never a fabricated V2 numeric result.
        """
        import json

        pid = _publication_id(publication_id)
        _, data = self._request(
            "GET",
            f"v1/internal/delta-publication-uploads/{quote(pid, safe='')}/masked-input",
            params={"worker_instance_id": _resource_id(worker_instance_id, "WORKER_INSTANCE")},
        )
        try:
            decoded = json.loads(data)
        except Exception:
            raise DeltaPublicationWorkerError("INVALID_CORE_RESPONSE") from None
        try:
            inner = (
                decoded["input"] if isinstance(decoded, dict) and "input" in decoded else decoded
            )
            worker_input = DeltaPublicationMaskedWorkerInputV1.model_validate(inner)
        except (ValidationError, ValueError, TypeError, KeyError):
            raise DeltaPublicationWorkerError("INVALID_CORE_RESPONSE") from None
        if worker_input.publication_id != pid or worker_input.worker_instance_id != (
            worker_instance_id
        ):
            raise DeltaPublicationWorkerError("INPUT_BINDING_MISMATCH")
        return worker_input

    def fetch_mask_bytes(
        self,
        publication_id: str,
        *,
        worker_instance_id: str,
        lease_generation: int,
        expected_sha256: str,
        expected_size_bytes: int,
        mask_url: str,
    ) -> bytes:
        """Fetch mask bytes through the server-minted capability URL.

        The URL comes from the Core-issued masked input (minted from the
        explicit Core origin, never a client URL). The Core bearer is attached
        only after proving the URL shares the client's pinned Core origin —
        it is never sent to object-storage origins — and the opaque query
        binding (instance, generation) is verified against this call before
        any byte is accepted. The bounded body is hash/size-verified against
        the sealed binding before staging.
        """
        if (
            type(expected_sha256) is not str
            or not expected_sha256.startswith("sha256:")
            or len(expected_sha256) != 71
        ):
            raise DeltaPublicationWorkerError("INVALID_MASK_IDENTITY")
        if (
            type(expected_size_bytes) is not int
            or isinstance(expected_size_bytes, bool)
            or expected_size_bytes <= 0
            or expected_size_bytes > self._maximum_response_bytes
        ):
            raise DeltaPublicationWorkerError("INVALID_MASK_IDENTITY")
        if type(lease_generation) is not int or lease_generation <= 0:
            raise DeltaPublicationWorkerError("INVALID_LEASE_FENCE")
        pid = _publication_id(publication_id)
        instance = _resource_id(worker_instance_id, "WORKER_INSTANCE")
        try:
            parsed = urlsplit(mask_url)
            base = urlsplit(self._base_url)
            if (
                parsed.scheme not in {"http", "https"}
                or parsed.username is not None
                or parsed.password is not None
                or "\r" in mask_url
                or "\n" in mask_url
            ):
                raise ValueError
            if (parsed.scheme, parsed.hostname, parsed.port) != (
                base.scheme,
                base.hostname,
                base.port,
            ):
                raise DeltaPublicationWorkerError("MASK_ORIGIN_REJECTED")
            from urllib.parse import parse_qsl as _parse_qsl

            query = dict(_parse_qsl(parsed.query, keep_blank_values=True))
            if query.get("worker_instance_id") != instance or query.get("lease_generation") != str(
                lease_generation
            ):
                raise DeltaPublicationWorkerError("MASK_BINDING_MISMATCH")
            expected_path = f"/v1/internal/delta-publication-uploads/{pid}/mask-bytes"
            if parsed.path != expected_path:
                raise DeltaPublicationWorkerError("MASK_BINDING_MISMATCH")
        except DeltaPublicationWorkerError:
            raise
        except ValueError:
            raise DeltaPublicationWorkerError("INVALID_MASK_IDENTITY") from None
        _, data = self._request("GET", mask_url)
        if (
            len(data) != expected_size_bytes
            or ("sha256:" + hashlib.sha256(data).hexdigest()) != expected_sha256
        ):
            raise DeltaPublicationWorkerError("MASK_BYTE_STREAM_INVALID")
        return data

    def post_observation(
        self, publication_id: str, observation: DeltaOutputObservationWireV1
    ) -> dict:
        import json

        payload = observation.model_dump(by_alias=True, mode="json")
        pid = _publication_id(publication_id)
        _, data = self._request(
            "POST",
            f"v1/internal/delta-publication-uploads/{quote(pid, safe='')}/observation",
            headers={"Content-Type": "application/json"},
            body=payload,
        )
        try:
            decoded = json.loads(data)
        except Exception:
            raise DeltaPublicationWorkerError("INVALID_CORE_RESPONSE") from None
        try:
            echo = DeltaOutputObservationWireV1.model_validate(decoded)
        except ValidationError:
            raise DeltaPublicationWorkerError("INVALID_CORE_RESPONSE") from None
        if (
            echo.publication_id != pid
            or echo.observation_digest != observation.observation_digest
            or echo.lease_generation != observation.lease_generation
            or echo.source_contract_version != observation.source_contract_version
        ):
            raise DeltaPublicationWorkerError("OBSERVATION_BINDING_MISMATCH")
        return decoded if isinstance(decoded, dict) else {}

    def upload_bytes(
        self,
        publication_id: str,
        *,
        worker_instance_id: str,
        lease_generation: int,
        payload: bytes,
    ) -> dict:
        import json

        if type(lease_generation) is not int or lease_generation <= 0:
            raise DeltaPublicationWorkerError("INVALID_LEASE_FENCE")
        pid = _publication_id(publication_id)
        _, data = self._request(
            "POST",
            f"v1/internal/delta-publication-uploads/{quote(pid, safe='')}/bytes",
            params={
                "worker_instance_id": _resource_id(worker_instance_id, "WORKER_INSTANCE"),
                "lease_generation": lease_generation,
            },
            headers={"Content-Type": "application/octet-stream"},
            raw=payload,
        )
        try:
            decoded = json.loads(data)
        except Exception:
            raise DeltaPublicationWorkerError("INVALID_CORE_RESPONSE") from None
        try:
            published = DeltaPublicationViewV1.model_validate(decoded)
        except ValidationError:
            raise DeltaPublicationWorkerError("INVALID_CORE_RESPONSE") from None
        if published.publication_id != pid or published.status != "PUBLISHED":
            raise DeltaPublicationWorkerError("PUBLISH_BINDING_MISMATCH")
        return decoded if isinstance(decoded, dict) else {}

    def record_failure(
        self,
        publication_id: str,
        *,
        worker_instance_id: str,
        lease_generation: int,
        reason: str,
    ) -> None:
        try:
            if type(lease_generation) is not int or lease_generation <= 0:
                return
            pid = _publication_id(publication_id)
            self._request(
                "POST",
                f"v1/internal/delta-publication-uploads/{quote(pid, safe='')}/failure",
                headers={"Content-Type": "application/json"},
                body={
                    "workerInstanceId": _resource_id(worker_instance_id, "WORKER_INSTANCE"),
                    "leaseGeneration": lease_generation,
                    "reason": _failure_code(reason),
                },
            )
        except DeltaPublicationWorkerError:
            return


def _capability_input(item: DeltaPublicationWorkerInputCapabilityV1) -> MeasurementInputV2:
    return MeasurementInputV2(
        role=item.role,
        artifact_id=item.artifact_id,
        observed_sha256=item.observed_sha256,
        observed_size_bytes=item.observed_size_bytes,
    )


def download_inputs(
    *,
    worker_input: DeltaPublicationWorkerInputV1,
    source: ExternalObjectHttpByteSource,
    work_dir: Path,
    deadline: ProtocolDeadline,
    is_current: Callable[[], bool],
    heartbeat_interval_millis: int,
    max_chunk_bytes: int,
) -> tuple[Path, Path]:
    """Download both DSMs through the pinned transport into private files.

    Every chunk is guarded by the live lease/currentness callback and the
    shared deadline; hash and size are verified against the sealed identity
    before either path is returned. No caller URL is accepted here: the URLs
    come only from the Core-issued capabilities.
    """
    if len(worker_input.inputs) != 2:
        raise DeltaPublicationWorkerError("INPUT_BINDING_MISMATCH")
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        mode = stat.S_IMODE(os.stat(work_dir).st_mode)
    except OSError as exc:
        raise DeltaPublicationWorkerError("INPUT_WORKSPACE_UNAVAILABLE") from exc
    if mode & 0o077:
        raise DeltaPublicationWorkerError("INPUT_WORKSPACE_UNAVAILABLE")
    paths: list[Path] = []
    try:
        for index, item in enumerate(worker_input.inputs):
            if item.expires_at <= datetime.now(UTC):
                raise DeltaPublicationWorkerError("INPUT_CAPABILITY_EXPIRED")
            artifact = _capability_input(item)
            # Local filenames never embed caller-controlled artifact ids:
            # roles are a closed two-member enum, so role-plus-index names
            # cannot traverse the work directory.
            target = work_dir / f"{item.role.lower()}-{index}.tif"
            if target.exists():
                raise DeltaPublicationWorkerError("INPUT_WORKSPACE_UNAVAILABLE")
            reader = None
            descriptor = None
            try:
                if not is_current():
                    raise DeltaPublicationWorkerError("AUTHORITY_LOST")
                deadline.remaining()
                reader = source.open_bound_bytes(
                    artifact,
                    deadline=deadline,
                    wait_is_current=is_current,
                    heartbeat_interval_millis=heartbeat_interval_millis,
                )
                descriptor = os.open(
                    target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600
                )
                digest = hashlib.sha256()
                remaining = item.observed_size_bytes
                while remaining:
                    if not is_current():
                        raise DeltaPublicationWorkerError("AUTHORITY_LOST")
                    deadline.remaining()
                    chunk = reader.read_chunk(
                        min(remaining, max_chunk_bytes),
                        deadline=deadline,
                        wait_is_current=is_current,
                        heartbeat_interval_millis=heartbeat_interval_millis,
                    )
                    if not chunk or len(chunk) > remaining:
                        raise DeltaPublicationWorkerError("INPUT_BYTE_STREAM_INVALID")
                    written = 0
                    while written < len(chunk):
                        count = os.write(descriptor, chunk[written:])
                        if count <= 0:
                            raise DeltaPublicationWorkerError("INPUT_WORKSPACE_UNAVAILABLE")
                        written += count
                    digest.update(chunk)
                    remaining -= len(chunk)
                if not is_current():
                    raise DeltaPublicationWorkerError("AUTHORITY_LOST")
                deadline.remaining()
                if reader.read_chunk(
                    1,
                    deadline=deadline,
                    wait_is_current=is_current,
                    heartbeat_interval_millis=heartbeat_interval_millis,
                ):
                    raise DeltaPublicationWorkerError("INPUT_BYTE_STREAM_INVALID")
                if (
                    "sha256:" + digest.hexdigest() != item.observed_sha256
                    or os.fstat(descriptor).st_size != item.observed_size_bytes
                ):
                    raise DeltaPublicationWorkerError("INPUT_BYTE_STREAM_INVALID")
            except (ProtocolViolation, ExternalObjectTransportError) as exc:
                if isinstance(exc, ExternalObjectTransportError) and exc.code in {
                    "AUTHORITY_LOST",
                    "INPUT_CAPABILITY_UNAVAILABLE",
                }:
                    raise DeltaPublicationWorkerError(exc.code) from None
                raise DeltaPublicationWorkerError("INPUT_OBJECT_TRANSPORT_FAILED") from None
            finally:
                if reader is not None:
                    reader.close()
                if descriptor is not None:
                    os.close(descriptor)
            paths.append(target)
        return paths[0], paths[1]
    except BaseException:
        for path in paths:
            with open(path, "ab"):
                pass
        raise


def build_observation_from_output(
    *,
    worker_input: DeltaPublicationWorkerInputV1 | DeltaPublicationMaskedWorkerInputV1,
    output_path: Path | None = None,
    output_fd: int | None = None,
    output_sha256: str,
    output_size_bytes: int,
) -> DeltaOutputObservationWireV1:
    """Parse the ACTUAL emitted TIFF and bind the observed output body.

    The dtype, grid, transform, CRS, bounds, sign, and nodata convention come
    from rasterio's parse of the real bytes; the hash/size come from the
    measured output. Nothing here trusts an upload-caller claim.
    """
    if (output_path is None) == (output_fd is None):
        raise DeltaPublicationWorkerError("INVALID_OBSERVED_OUTPUT")
    target = str(output_path) if output_path is not None else f"/proc/self/fd/{output_fd}"
    try:
        with rasterio.open(target, "r", driver="GTiff") as dataset:
            if dataset.count != 1 or tuple(dataset.dtypes) != ("float64",):
                raise DeltaPublicationWorkerError("OBSERVED_OUTPUT_MISMATCH")
            if dataset.tags().get("DELTA_RULE") != "CURRENT_MINUS_BASELINE":
                raise DeltaPublicationWorkerError("OBSERVED_OUTPUT_MISMATCH")
            transform = tuple(float(v) for v in dataset.transform)[:6]
            bounds = (
                float(dataset.bounds.left),
                float(dataset.bounds.bottom),
                float(dataset.bounds.right),
                float(dataset.bounds.top),
            )
            rows, columns = int(dataset.height), int(dataset.width)
            nodata = dataset.nodata
            if nodata is None or not (isinstance(nodata, float) and math.isnan(nodata)):
                raise DeltaPublicationWorkerError("OBSERVED_OUTPUT_MISMATCH")
            # Read one block to prove decodability; full cell verification
            # already happened in the reproduction primitive.
            _ = dataset.read(1, window=((0, min(1, rows)), (0, min(1, columns))))
    except DeltaPublicationWorkerError:
        raise
    except Exception as exc:
        raise DeltaPublicationWorkerError("OBSERVED_OUTPUT_MISMATCH") from exc
    transform_digest = (
        "sha256:" + hashlib.sha256(canonical_json_bytes({"transform": list(transform)})).hexdigest()
    )
    raw = {
        "organizationId": worker_input.organization_id,
        "siteId": worker_input.site_id,
        "workAreaId": worker_input.work_area_id,
        "sourceContractVersion": worker_input.source_contract_version,
        "sourceCalculationIdentityDigest": worker_input.source_calculation_identity_digest,
        "sourceNumericResultIdentityDigest": worker_input.source_numeric_result_identity_digest,
        "sourceCoverageWitnessDigest": worker_input.source_coverage_witness_digest,
        "publicationId": worker_input.publication_id,
        "workerPrincipalId": worker_input.worker_principal_id,
        "workerInstanceId": worker_input.worker_instance_id,
        "leaseGeneration": worker_input.lease_generation,
        "outputSha256": output_sha256,
        "outputSizeBytes": output_size_bytes,
        "gridRows": rows,
        "gridColumns": columns,
        "transform": list(transform),
        "transformDigest": transform_digest,
        "gridCrsIdentifier": worker_input.grid_crs_identifier,
        "gridCrsDigest": worker_input.grid_crs_digest,
        "bounds": list(bounds),
        "dtype": "FLOAT64",
        "deltaSign": "CURRENT_MINUS_BASELINE",
        "nodataValue": "NAN",
    }
    observation_digest = "sha256:" + hashlib.sha256(canonical_json_bytes(raw)).hexdigest()
    try:
        return DeltaOutputObservationWireV1.model_validate(
            {**raw, "observationDigest": observation_digest}
        )
    except ValidationError as exc:
        raise DeltaPublicationWorkerError("OBSERVED_OUTPUT_MISMATCH") from exc


def _watchdog_from_envelope(
    envelope: ResourceEnvelopeV1,
    *,
    is_cancelled: Callable[[], bool] | None,
    maximum_wall_seconds: float | None,
) -> MeasurementWatchdogV2:
    if maximum_wall_seconds is None:
        maximum_wall_seconds = float(envelope.max_deadline_seconds)
    return MeasurementWatchdogV2.from_envelope(
        envelope, maximum_wall_seconds=maximum_wall_seconds, is_cancelled=is_cancelled
    )


def run_delta_publication_job(
    *,
    config: DeltaPublicationWorkerConfig,
    core_client: DeltaPublicationCoreClient | None = None,
    worker_principal_id: str,
    is_cancelled: Callable[[], bool] | None = None,
    maximum_wall_seconds: float | None = None,
    check_current: Callable[[], None] | None = None,
    deadline_monotonic: float | None = None,
    owned_client: bool = False,
) -> Literal["PUBLISHED", "FAILED"]:
    """Run one late-export job end-to-end with closed failure semantics.

    Returns ``"PUBLISHED"`` only after the raw bytes upload succeeds. Any
    guard, transport, measurement, observation, or Core rejection posts a
    typed ``record_failure`` (when a lease generation is known) and returns
    ``"FAILED"``. The old V2 numeric state is never touched: failure here
    marks only the new publication fence. A leased intent whose source
    contract is not the V2 report is abandoned without any further call —
    no input fetch, publish, or failure record — so a foreign-lane fence is
    never touched.
    """
    guard = check_current or (lambda: None)
    cancel = is_cancelled or (lambda: False)
    owns = core_client is None
    client = core_client or DeltaPublicationCoreClient(
        base_url=config.core_base_url,
        bearer_token=config.core_bearer_token,
        maximum_response_bytes=config.maximum_response_bytes,
        request_timeout_seconds=config.request_timeout_seconds,
    )
    lease_generation: int | None = None
    baseline_path: Path | None = None
    current_path: Path | None = None
    try:
        if cancel():
            raise DeltaPublicationWorkerError("WORKER_CANCELLED")
        guard()
        lease_view = client.acquire_lease(
            config.publication_id,
            worker_instance_id=config.worker_instance_id,
            lease_acquisition_id=config.lease_acquisition_id,
        )
        try:
            lease_generation = int(lease_view.get("leaseGeneration", 0))
        except Exception:
            raise DeltaPublicationWorkerError("LEASE_BINDING_MISMATCH") from None
        if lease_generation <= 0:
            raise DeltaPublicationWorkerError("LEASE_BINDING_MISMATCH")
        if lease_view.get("sourceContractVersion") != _V2_SOURCE_CONTRACT_VERSION:
            # A foreign-lane lease is abandoned without any further call: no
            # input fetch, publish, or failure record touches that fence.
            return "FAILED"
        if cancel():
            raise DeltaPublicationWorkerError("WORKER_CANCELLED")
        guard()
        worker_input = client.fetch_input(
            config.publication_id, worker_instance_id=config.worker_instance_id
        )
        if (
            worker_input.publication_id != config.publication_id
            or worker_input.worker_instance_id != config.worker_instance_id
            or worker_input.worker_principal_id != worker_principal_id
            or worker_input.lease_generation != lease_generation
        ):
            raise DeltaPublicationWorkerError("INPUT_BINDING_MISMATCH")
        if cancel():
            raise DeltaPublicationWorkerError("WORKER_CANCELLED")
        guard()
        now_monotonic = time.monotonic()
        wall = maximum_wall_seconds or float(config.envelope.max_deadline_seconds)
        expires_at = now_monotonic + wall
        if deadline_monotonic is not None:
            expires_at = min(expires_at, deadline_monotonic)
        deadline = ProtocolDeadline.at_expires_at(expires_at)

        def _is_current() -> bool:
            if cancel():
                return False
            try:
                guard()
            except Exception:
                return False
            try:
                deadline.remaining()
            except (ProtocolDeadlineExceeded, Exception):
                return False
            return True

        source = ExternalObjectHttpByteSource(
            (
                ExternalObjectCapabilityV1(
                    artifact=_capability_input(item),
                    url=item.download_url,
                    required_headers=dict(item.required_headers),
                )
                for item in worker_input.inputs
            ),
            policy=config.transport_policy,
        )
        baseline_path, current_path = download_inputs(
            worker_input=worker_input,
            source=source,
            work_dir=config.work_dir,
            deadline=deadline,
            is_current=_is_current,
            heartbeat_interval_millis=config.heartbeat_interval_millis,
            max_chunk_bytes=config.max_chunk_bytes,
        )
        if cancel():
            raise DeltaPublicationWorkerError("WORKER_CANCELLED")
        guard()
        watchdog = _watchdog_from_envelope(
            config.envelope, is_cancelled=cancel, maximum_wall_seconds=maximum_wall_seconds
        )
        with reproduce_external_delta_raster_v2(
            calculation_identity=worker_input.calculation_identity,
            numeric_result=worker_input.numeric_result,
            baseline_path=baseline_path,
            current_path=current_path,
            envelope=config.envelope,
            watchdog=watchdog,
            maximum_output_bytes=config.maximum_output_bytes,
            maximum_grid_cells=config.maximum_grid_cells,
            check_current=guard,
        ) as measured:
            if cancel():
                raise DeltaPublicationWorkerError("WORKER_CANCELLED")
            guard()
            with os.fdopen(os.dup(measured.fd), "rb") as stream:
                payload = stream.read()
            if (
                len(payload) != measured.size_bytes
                or ("sha256:" + hashlib.sha256(payload).hexdigest()) != measured.sha256
            ):
                raise DeltaPublicationWorkerError("OBSERVED_OUTPUT_MISMATCH")
            observation = build_observation_from_output(
                worker_input=worker_input,
                output_fd=measured.fd,
                output_sha256=measured.sha256,
                output_size_bytes=measured.size_bytes,
            )
            if cancel():
                raise DeltaPublicationWorkerError("WORKER_CANCELLED")
            guard()
            client.post_observation(config.publication_id, observation)
            if cancel():
                raise DeltaPublicationWorkerError("WORKER_CANCELLED")
            guard()
            client.upload_bytes(
                config.publication_id,
                worker_instance_id=config.worker_instance_id,
                lease_generation=lease_generation,
                payload=payload,
            )
        return "PUBLISHED"
    except DeltaPublicationWorkerError as exc:
        try:
            if lease_generation is not None:
                client.record_failure(
                    config.publication_id,
                    worker_instance_id=config.worker_instance_id,
                    lease_generation=lease_generation,
                    reason=exc.code
                    if exc.code and exc.code[0].isalpha()
                    else "WORKER_EXECUTION_FAILED",
                )
        except Exception:
            pass
        return "FAILED"
    except (MeasurementAlgorithmIncomplete, ReproductionMeasurementError) as exc:
        try:
            if lease_generation is not None:
                reason = (
                    getattr(exc, "code", None)
                    or getattr(exc, "reason", None)
                    or "MEASUREMENT_INCOMPLETE"
                )
                client.record_failure(
                    config.publication_id,
                    worker_instance_id=config.worker_instance_id,
                    lease_generation=lease_generation,
                    reason=str(reason) if str(reason)[0].isalpha() else "MEASUREMENT_INCOMPLETE",
                )
        except Exception:
            pass
        return "FAILED"
    except Exception:
        try:
            if lease_generation is not None:
                client.record_failure(
                    config.publication_id,
                    worker_instance_id=config.worker_instance_id,
                    lease_generation=lease_generation,
                    reason="WORKER_EXECUTION_FAILED",
                )
        except Exception:
            pass
        return "FAILED"
    finally:
        import contextlib as _contextlib

        for path in (baseline_path, current_path):
            if path is not None:
                with _contextlib.suppress(OSError):
                    if path.exists():
                        os.remove(path)
        if owns or owned_client:
            with _contextlib.suppress(Exception):
                client.close()


def download_masked_inputs(
    *,
    worker_input: DeltaPublicationMaskedWorkerInputV1,
    source: ExternalObjectHttpByteSource,
    work_dir: Path,
    deadline: ProtocolDeadline,
    is_current: Callable[[], bool],
    heartbeat_interval_millis: int,
    max_chunk_bytes: int,
) -> tuple[Path, Path]:
    """Download the two V3 DSMs through the pinned transport into private files.

    Only the ordered DSM capabilities travel the object transport; the mask
    retrieval descriptor is resolved separately via :meth:`fetch_mask_bytes`.
    Every chunk is guarded by the live lease/currentness callback and the
    shared deadline; hash and size are verified against the sealed source
    identity before either path is returned.
    """
    if len(worker_input.inputs) != 3:
        raise DeltaPublicationWorkerError("INPUT_BINDING_MISMATCH")
    baseline_item, current_item, mask_item = worker_input.inputs
    if (baseline_item.role, current_item.role, mask_item.role) != (
        "BASELINE_DSM",
        "CURRENT_DSM",
        "EXCLUSION_MASK",
    ):
        raise DeltaPublicationWorkerError("INPUT_BINDING_MISMATCH")
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        mode = stat.S_IMODE(os.stat(work_dir).st_mode)
    except OSError as exc:
        raise DeltaPublicationWorkerError("INPUT_WORKSPACE_UNAVAILABLE") from exc
    if mode & 0o077:
        raise DeltaPublicationWorkerError("INPUT_WORKSPACE_UNAVAILABLE")
    if mask_item.expires_at <= datetime.now(UTC):
        raise DeltaPublicationWorkerError("INPUT_CAPABILITY_EXPIRED")
    paths: list[Path] = []
    try:
        for index, item in enumerate((baseline_item, current_item)):
            if item.expires_at <= datetime.now(UTC):
                raise DeltaPublicationWorkerError("INPUT_CAPABILITY_EXPIRED")
            artifact = _capability_input(item)
            target = work_dir / f"{item.role.lower()}-{index}.tif"
            if target.exists():
                raise DeltaPublicationWorkerError("INPUT_WORKSPACE_UNAVAILABLE")
            reader = None
            descriptor = None
            try:
                if not is_current():
                    raise DeltaPublicationWorkerError("AUTHORITY_LOST")
                deadline.remaining()
                reader = source.open_bound_bytes(
                    artifact,
                    deadline=deadline,
                    wait_is_current=is_current,
                    heartbeat_interval_millis=heartbeat_interval_millis,
                )
                descriptor = os.open(
                    target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600
                )
                digest = hashlib.sha256()
                remaining = item.observed_size_bytes
                while remaining:
                    if not is_current():
                        raise DeltaPublicationWorkerError("AUTHORITY_LOST")
                    deadline.remaining()
                    chunk = reader.read_chunk(
                        min(remaining, max_chunk_bytes),
                        deadline=deadline,
                        wait_is_current=is_current,
                        heartbeat_interval_millis=heartbeat_interval_millis,
                    )
                    if not chunk or len(chunk) > remaining:
                        raise DeltaPublicationWorkerError("INPUT_BYTE_STREAM_INVALID")
                    written = 0
                    while written < len(chunk):
                        count = os.write(descriptor, chunk[written:])
                        if count <= 0:
                            raise DeltaPublicationWorkerError("INPUT_WORKSPACE_UNAVAILABLE")
                        written += count
                    digest.update(chunk)
                    remaining -= len(chunk)
                if not is_current():
                    raise DeltaPublicationWorkerError("AUTHORITY_LOST")
                deadline.remaining()
                if reader.read_chunk(
                    1,
                    deadline=deadline,
                    wait_is_current=is_current,
                    heartbeat_interval_millis=heartbeat_interval_millis,
                ):
                    raise DeltaPublicationWorkerError("INPUT_BYTE_STREAM_INVALID")
                if (
                    "sha256:" + digest.hexdigest() != item.observed_sha256
                    or os.fstat(descriptor).st_size != item.observed_size_bytes
                ):
                    raise DeltaPublicationWorkerError("INPUT_BYTE_STREAM_INVALID")
            except (ProtocolViolation, ExternalObjectTransportError) as exc:
                if isinstance(exc, ExternalObjectTransportError) and exc.code in {
                    "AUTHORITY_LOST",
                    "INPUT_CAPABILITY_UNAVAILABLE",
                }:
                    raise DeltaPublicationWorkerError(exc.code) from None
                raise DeltaPublicationWorkerError("INPUT_OBJECT_TRANSPORT_FAILED") from None
            finally:
                if reader is not None:
                    reader.close()
                if descriptor is not None:
                    os.close(descriptor)
            paths.append(target)
        return paths[0], paths[1]
    except BaseException:
        for path in paths:
            with open(path, "ab"):
                pass
        raise


def _write_private_bytes(*, work_dir: Path, name: str, payload: bytes) -> Path:
    """Stage already-verified bytes as an owner-private sealed regular file."""
    target = work_dir / name
    if target.exists():
        raise DeltaPublicationWorkerError("INPUT_WORKSPACE_UNAVAILABLE")
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    try:
        view = memoryview(payload)
        while view:
            count = os.write(descriptor, view)
            if count <= 0:
                raise DeltaPublicationWorkerError("INPUT_WORKSPACE_UNAVAILABLE")
            view = view[count:]
    finally:
        os.close(descriptor)
    return target


def run_masked_delta_publication_job(
    *,
    config: DeltaPublicationWorkerConfig,
    core_client: DeltaPublicationCoreClient | None = None,
    worker_principal_id: str,
    is_cancelled: Callable[[], bool] | None = None,
    maximum_wall_seconds: float | None = None,
    check_current: Callable[[], None] | None = None,
    deadline_monotonic: float | None = None,
    owned_client: bool = False,
) -> Literal["PUBLISHED", "FAILED"]:
    """Run one masked late-export job end-to-end with closed failure semantics.

    Mirrors :func:`run_delta_publication_job` for the V3 profile: acquire the
    publication lease, fetch the server-issued masked input, download the two
    DSMs through the pinned object transport, fetch the mask bytes through
    the dedicated lease-scoped same-origin route, re-measure against the
    ORIGINAL sealed V3 report (never minting a new numeric identity and never
    touching any V2 attempt), then post the observed output and upload the raw
    bytes. Returns ``"PUBLISHED"`` only after the raw bytes upload succeeds.
    A leased intent whose source contract is not the V3 masked identity is
    abandoned without any further call: no input fetch, publish, or failure
    record touches that foreign-lane fence.
    """
    guard = check_current or (lambda: None)
    cancel = is_cancelled or (lambda: False)
    owns = core_client is None
    client = core_client or DeltaPublicationCoreClient(
        base_url=config.core_base_url,
        bearer_token=config.core_bearer_token,
        maximum_response_bytes=config.maximum_response_bytes,
        request_timeout_seconds=config.request_timeout_seconds,
    )
    lease_generation: int | None = None
    baseline_path: Path | None = None
    current_path: Path | None = None
    mask_path: Path | None = None
    try:
        if cancel():
            raise DeltaPublicationWorkerError("WORKER_CANCELLED")
        guard()
        lease_view = client.acquire_lease(
            config.publication_id,
            worker_instance_id=config.worker_instance_id,
            lease_acquisition_id=config.lease_acquisition_id,
        )
        try:
            lease_generation = int(lease_view.get("leaseGeneration", 0))
        except Exception:
            raise DeltaPublicationWorkerError("LEASE_BINDING_MISMATCH") from None
        if lease_generation <= 0:
            raise DeltaPublicationWorkerError("LEASE_BINDING_MISMATCH")
        if lease_view.get("sourceContractVersion") != _MASKED_SOURCE_CONTRACT_VERSION:
            # A foreign-lane lease is abandoned without any further call: no
            # input fetch, publish, or failure record touches that fence.
            return "FAILED"
        if cancel():
            raise DeltaPublicationWorkerError("WORKER_CANCELLED")
        guard()
        worker_input = client.fetch_masked_input(
            config.publication_id, worker_instance_id=config.worker_instance_id
        )
        if (
            worker_input.publication_id != config.publication_id
            or worker_input.worker_instance_id != config.worker_instance_id
            or worker_input.worker_principal_id != worker_principal_id
            or worker_input.lease_generation != lease_generation
        ):
            raise DeltaPublicationWorkerError("INPUT_BINDING_MISMATCH")
        if cancel():
            raise DeltaPublicationWorkerError("WORKER_CANCELLED")
        guard()
        now_monotonic = time.monotonic()
        wall = maximum_wall_seconds or float(config.envelope.max_deadline_seconds)
        expires_at = now_monotonic + wall
        if deadline_monotonic is not None:
            expires_at = min(expires_at, deadline_monotonic)
        deadline = ProtocolDeadline.at_expires_at(expires_at)

        def _is_current() -> bool:
            if cancel():
                return False
            try:
                guard()
            except Exception:
                return False
            try:
                deadline.remaining()
            except (ProtocolDeadlineExceeded, Exception):
                return False
            return True

        mask_item = worker_input.inputs[2]
        if mask_item.expires_at <= datetime.now(UTC):
            raise DeltaPublicationWorkerError("INPUT_CAPABILITY_EXPIRED")
        source = ExternalObjectHttpByteSource(
            (
                ExternalObjectCapabilityV1(
                    artifact=_capability_input(item),
                    url=item.download_url,
                    required_headers=dict(item.required_headers),
                )
                for item in (worker_input.inputs[0], worker_input.inputs[1])
            ),
            policy=config.transport_policy,
        )
        baseline_path, current_path = download_masked_inputs(
            worker_input=worker_input,
            source=source,
            work_dir=config.work_dir,
            deadline=deadline,
            is_current=_is_current,
            heartbeat_interval_millis=config.heartbeat_interval_millis,
            max_chunk_bytes=config.max_chunk_bytes,
        )
        if cancel():
            raise DeltaPublicationWorkerError("WORKER_CANCELLED")
        guard()
        mask_bytes = client.fetch_mask_bytes(
            config.publication_id,
            worker_instance_id=config.worker_instance_id,
            lease_generation=lease_generation,
            expected_sha256=mask_item.observed_sha256,
            expected_size_bytes=mask_item.observed_size_bytes,
            mask_url=mask_item.download_url,
        )
        if cancel():
            raise DeltaPublicationWorkerError("WORKER_CANCELLED")
        guard()
        mask_path = _write_private_bytes(
            work_dir=config.work_dir, name="exclusion-mask-0.tif", payload=mask_bytes
        )
        watchdog = _watchdog_from_envelope(
            config.envelope, is_cancelled=cancel, maximum_wall_seconds=maximum_wall_seconds
        )
        with reproduce_masked_delta_raster_v3(
            masked_identity=worker_input.masked_calculation_identity,
            report=worker_input.report,
            baseline_path=baseline_path,
            current_path=current_path,
            mask_path=mask_path,
            envelope=config.envelope,
            watchdog=watchdog,
            maximum_output_bytes=config.maximum_output_bytes,
            maximum_grid_cells=config.maximum_grid_cells,
            check_current=guard,
        ) as measured:
            if cancel():
                raise DeltaPublicationWorkerError("WORKER_CANCELLED")
            guard()
            with os.fdopen(os.dup(measured.fd), "rb") as stream:
                payload = stream.read()
            if (
                len(payload) != measured.size_bytes
                or ("sha256:" + hashlib.sha256(payload).hexdigest()) != measured.sha256
            ):
                raise DeltaPublicationWorkerError("OBSERVED_OUTPUT_MISMATCH")
            observation = build_observation_from_output(
                worker_input=worker_input,
                output_fd=measured.fd,
                output_sha256=measured.sha256,
                output_size_bytes=measured.size_bytes,
            )
            if cancel():
                raise DeltaPublicationWorkerError("WORKER_CANCELLED")
            guard()
            client.post_observation(config.publication_id, observation)
            if cancel():
                raise DeltaPublicationWorkerError("WORKER_CANCELLED")
            guard()
            client.upload_bytes(
                config.publication_id,
                worker_instance_id=config.worker_instance_id,
                lease_generation=lease_generation,
                payload=payload,
            )
        return "PUBLISHED"
    except DeltaPublicationWorkerError as exc:
        try:
            if lease_generation is not None:
                client.record_failure(
                    config.publication_id,
                    worker_instance_id=config.worker_instance_id,
                    lease_generation=lease_generation,
                    reason=exc.code
                    if exc.code and exc.code[0].isalpha()
                    else "WORKER_EXECUTION_FAILED",
                )
        except Exception:
            pass
        return "FAILED"
    except (MeasurementAlgorithmIncomplete, ReproductionMeasurementError) as exc:
        try:
            if lease_generation is not None:
                reason = (
                    getattr(exc, "code", None)
                    or getattr(exc, "reason", None)
                    or "MEASUREMENT_INCOMPLETE"
                )
                client.record_failure(
                    config.publication_id,
                    worker_instance_id=config.worker_instance_id,
                    lease_generation=lease_generation,
                    reason=str(reason) if str(reason)[0].isalpha() else "MEASUREMENT_INCOMPLETE",
                )
        except Exception:
            pass
        return "FAILED"
    except Exception:
        try:
            if lease_generation is not None:
                client.record_failure(
                    config.publication_id,
                    worker_instance_id=config.worker_instance_id,
                    lease_generation=lease_generation,
                    reason="WORKER_EXECUTION_FAILED",
                )
        except Exception:
            pass
        return "FAILED"
    finally:
        import contextlib as _contextlib

        for path in (baseline_path, current_path, mask_path):
            if path is not None:
                with _contextlib.suppress(OSError):
                    if path.exists():
                        os.remove(path)
        if owns or owned_client:
            with _contextlib.suppress(Exception):
                client.close()


__all__ = [
    "DeltaPublicationCoreClient",
    "DeltaPublicationWorkerConfig",
    "DeltaPublicationWorkerError",
    "build_observation_from_output",
    "download_inputs",
    "download_masked_inputs",
    "run_delta_publication_job",
    "run_masked_delta_publication_job",
]
