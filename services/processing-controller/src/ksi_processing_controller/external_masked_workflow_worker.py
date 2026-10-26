"""First-execution masked workflow worker: inspection plus V3 calculation (P2, additive).

This is the new first-execution job, not the V2 Analysis worker and not the
late-export output worker owned by the other Lead (``ses_e87673...``). It
consumes exactly Core-owned queues (never client raw URLs) for ONE bounded
drain pass:

- Core handshake (all closed, bounded, bearer-authenticated): discover the
  worker-visible pendings from Core-owned queues (no caller ids, no raw URLs),
  lease the narrow inspection job, fetch sealed mask bytes through the
  Core-bearer window, seal from the narrow report, then lease the V3
  calculation, fetch the server-issued three-input fence, fetch the two DSM
  legs through the NEW presigned DSM seam plus the mask leg through the
  Core-bearer ``EXCLUSION_MASK`` window, and post the fenced report/failure.
  No V2 analysis attempt is leased, renewed, reported, or treated as live; the
  old COMPLETED V2 numeric is evidence only (ADMIT_PROVISIONAL stays
  provisional, numeric appears only under AVAILABLE).
- Object downloads use the existing pinned-origin bounded transport
  (``ExternalObjectHttpByteSource`` with an operator-owned
  ``ExternalObjectTransportPolicyV1``). No DNS, proxy, redirect, cookie, or
  caller-supplied URL is accepted: the origin allow-list is explicit worker
  configuration, and every byte is hash/size verified against the sealed
  identity before measurement. The Core bearer is attached only to the pinned
  Core origin — it is never sent to object-storage origins — and the mask leg
  never leaves the Core-bearer path.
- Native measurement runs via the direct native helpers
  (:func:`inspect_mask_bytes_v1` and :func:`dispatch_masked_execution_v3`)
  which reuse the owned readers plus the shared align algorithm and verify the
  exact grid, array metrics, coverage, and NaN handling. The observed report is
  parsed from the actual emitted bytes, never from caller claims.
- Currentness, expiry, deadline, and cancel are guarded at every stage: lease
  expiry, capability expiry, wall deadline, and the caller-supplied
  cancel/currentness callbacks abort the job closed with a typed failure
  posted when a lease is held. A late export never fabricates a V2
  admission/authorization and never rewrites Core numeric state.

Network/host note: the Core and object transports are real software
transports (HTTP/1.1 over pinned loopback-allowed origins with bounded
headers, sizes, and deadlines). Activating them against a deployment network
still requires explicit host provisioning (trusted origin literals plus a
bearer token supplied by the operator via a protected file or a caller-explicit
object for the local harness); this module provides no defaults, reads no
environment, and never falls back to ambient credentials. The factory below is
opt-in and runtime-explicit for that reason.

Software proof and limits: local generated tests prove the real software
handshake (Core HTTP lease/input/DSM-caps/mask-bytes plus pinned object
downloads plus native dispatch) over loopback servers with synthetic bytes.
That proves the bytes and protocol only: the direct native helper runs
in-process for local software proof only (test loopback generated safe). It
claims no OS sandbox, no host provisioning, and no deployment containment — a
signed pin is never read as an OS sandbox. The separately verified contained
runtime remains operator-owned; the direct helper only runs inside it when
explicitly configured. Optional local composition (building a FastAPI app
around the real lane for tests) is test-only and never production-enabled.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import ipaddress
import math
import os
import re
import stat
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import quote, urlsplit

import httpx
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import ResourceEnvelopeV1
from ksi_event_contracts.external_mask_input import MaskInspectionProfileV1
from ksi_event_contracts.external_masked_api import (
    MaskedCalculationPendingListV1,
    MaskInspectionPendingListV1,
)
from ksi_event_contracts.external_masked_execution import MaskedWorkerInputV3
from ksi_event_contracts.external_masked_volume import MaskedRelativeVolumeProfileV3
from ksi_event_contracts.external_masked_volume_result import (
    MaskedVolumeCalculationFailureV3,
)
from ksi_event_contracts.external_masked_worker import MaskedWorkflowDsmInputViewV1
from pydantic import ValidationError

from ksi_processing_controller.external_inspector_protocol import (
    ProtocolDeadline,
    ProtocolDeadlineExceeded,
    ProtocolViolation,
)
from ksi_processing_controller.external_mask_input_inspection import (
    MaskInspectionError,
    inspect_mask_bytes_v1,
)
from ksi_processing_controller.external_masked_execution_dispatch import (
    MaskedDispatchInputsV3,
    MaskedExecutionDispatchError,
    dispatch_masked_execution_v3,
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
_JOB_ID_SAFE_MASKED_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_PATH_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_FAILURE_CODE_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


class MaskedWorkflowWorkerError(RuntimeError):
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
        raise MaskedWorkflowWorkerError(f"INVALID_{field}")
    return value


def _path_segment(value: object, field: str) -> str:
    if type(value) is not str or _PATH_SEGMENT_RE.fullmatch(value) is None:
        raise MaskedWorkflowWorkerError(f"INVALID_{field}")
    if ".." in value:
        raise MaskedWorkflowWorkerError(f"INVALID_{field}")
    return value


def _masked_job_id(value: object) -> str:
    if type(value) is not str or _JOB_ID_SAFE_MASKED_RE.fullmatch(value) is None:
        raise MaskedWorkflowWorkerError("INVALID_JOB_ID")
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


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _masked_inspection_runtime_digest_local(profile: MaskInspectionProfileV1) -> str:
    """Local copy of the closed 5-field inspector binding plus mask grammar.

    Pure digest, no Core state: the exact inspector image that may observe mask
    bytes is the one the pinned inspection profile names. Kept local so this
    worker never imports Core code; Core re-verifies the same digest behind its
    activation before sealing.
    """
    sealed = MaskInspectionProfileV1.model_validate(profile.model_dump(by_alias=True))
    if (
        sealed.inspection_profile_digest is None
        or sealed.inspection_profile_digest != sealed.canonical_digest()
    ):
        raise MaskedWorkflowWorkerError("INVALID_PINNED_PROFILE")
    return (
        "sha256:"
        + hashlib.sha256(
            canonical_json_bytes(
                {
                    "workerExecutableDigest": sealed.worker_executable_digest,
                    "workerBuildDigest": sealed.worker_build_digest,
                    "runtimeImageVersion": sealed.runtime_image_version,
                    "runtimeImageOciDigest": sealed.runtime_image_oci_digest,
                    "dependencyLockDigest": sealed.dependency_lock_digest,
                    "maskGrammarDigest": sealed.mask_grammar_digest,
                }
            )
        ).hexdigest()
    )


def _expected_lane_runtime_digest(config: MaskedWorkflowWorkerConfig) -> str:
    """Local copy of the closed lane runtime binding (no Core import).

    Mirrors the owner ``masked_execution_runtime_digest`` exactly: the five
    pinned execution-worker fields plus the masked profile, resource envelope,
    and narrow inspection profile digests, hashed over canonical JSON with
    stable camelCase keys. A declared model runtime that differs from the
    signed Core-authorized value fails closed before any download or native
    parse. This pin check is not an OS sandbox claim: native containment
    remains separately gated and operator-owned.
    """
    from ksi_event_contracts.external_masked_execution import MaskedExecutionRuntimeV3

    runtime = config.execution_runtime
    if not isinstance(runtime, MaskedExecutionRuntimeV3):
        raise MaskedWorkflowWorkerError("INVALID_PINNED_RUNTIME")
    sealed = MaskedExecutionRuntimeV3.model_validate(runtime.model_dump(by_alias=True))
    if sealed.runtime_digest is None or sealed.runtime_digest != sealed.canonical_digest():
        raise MaskedWorkflowWorkerError("INVALID_PINNED_RUNTIME")
    masked_profile_digest = config.masked_profile.canonical_digest()
    envelope_digest = config.envelope.canonical_digest()
    inspection_digest = config.inspection_profile.canonical_digest()
    for label, value in (
        ("masked profile", masked_profile_digest),
        ("resource envelope", envelope_digest),
        ("inspection profile", inspection_digest),
    ):
        if not isinstance(value, str) or len(value) != 71 or not value.startswith("sha256:"):
            raise MaskedWorkflowWorkerError(f"INVALID_PINNED_RUNTIME_{label!r}")
    return (
        "sha256:"
        + hashlib.sha256(
            canonical_json_bytes(
                {
                    "workerExecutableDigest": sealed.worker_executable_digest,
                    "workerBuildDigest": sealed.worker_build_digest,
                    "runtimeImageVersion": sealed.runtime_image_version,
                    "runtimeImageOciDigest": sealed.runtime_image_oci_digest,
                    "dependencyLockDigest": sealed.dependency_lock_digest,
                    "maskedProfileDigest": masked_profile_digest,
                    "resourceEnvelopeDigest": envelope_digest,
                    "inspectionProfileDigest": inspection_digest,
                }
            )
        ).hexdigest()
    )


def load_bearer_from_protected_file(path: Path) -> str:
    """Read an operator-provisioned bearer from an explicit protected file.

    The file must be an absolute owner-private regular file (0600, single link,
    no symlink) under an owner-controlled path. No environment fallback.
    """
    if not isinstance(path, Path) or not path.is_absolute() or ".." in path.parts:
        raise ValueError("bearer file must be an explicit absolute path")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as exc:
        raise ValueError("bearer file is unavailable") from exc
    try:
        file_stat = os.fstat(descriptor)
        if (
            not stat.S_ISREG(file_stat.st_mode)
            or file_stat.st_nlink != 1
            or stat.S_IMODE(file_stat.st_mode) != 0o600
        ):
            raise ValueError("bearer file must be a private single-link regular file")
        if file_stat.st_size <= 0 or file_stat.st_size > 8192:
            raise ValueError("bearer file size is out of bounds")
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            raw = handle.read()
            descriptor = -1
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    try:
        text = raw.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise ValueError("bearer file must be ASCII") from exc
    return _token(text)


@dataclass(frozen=True, slots=True)
class MaskedInspectionJobSpec:
    """Internal inspection spec derived from Core discovery (never caller URLs).

    Every fact comes from the Lead-owned pending declaration (opaque ids
    plus digests plus the sealed subjects); the worker supplies them back
    verbatim to the lease endpoint. Constructed only from
    ``MaskInspectionPendingListV1`` items inside the drain, never from
    caller-supplied ids. No raw path, URL, grid, or profile truth
    is accepted from any other source.
    """

    mask_child_id: str
    site_id: str
    work_area_id: str
    mask_artifact_id: str
    subject_digest: str
    parent_subject: dict
    baseline_subject: dict
    baseline_dsm_artifact_id: str
    declared_sha256: str
    declared_size_bytes: int
    organization_id: str = ""


@dataclass(frozen=True, slots=True)
class MaskedWorkflowWorkerConfig:
    """Explicit opt-in runtime for one masked first-execution drain site.

    No defaults, no environment: every origin, bearer, identity, bound, and
    deadline is supplied by the operator for the verified contained runtime.
    Credentials arrive as an explicit bearer string (caller-explicit object for
    the local harness) or via :func:`load_bearer_from_protected_file`; none
    are read from the environment and no default is inferred.
    """

    core_base_url: str
    core_bearer_token: str
    worker_instance_id: str
    lease_acquisition_id: str
    transport_policy: ExternalObjectTransportPolicyV1
    work_dir: Path
    envelope: ResourceEnvelopeV1
    masked_profile: MaskedRelativeVolumeProfileV3
    inspection_profile: MaskInspectionProfileV1
    execution_runtime: object
    maximum_response_bytes: int = 262_144
    request_timeout_seconds: float = 5.0
    max_chunk_bytes: int = 65_536
    heartbeat_interval_millis: int = 25

    def __post_init__(self) -> None:
        _trusted_base_url(self.core_base_url)
        _token(self.core_bearer_token)
        _resource_id(self.worker_instance_id, "WORKER_INSTANCE")
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
        if not isinstance(self.masked_profile, MaskedRelativeVolumeProfileV3):
            raise ValueError("worker requires the sealed masked profile pin")
        if (
            self.masked_profile.masked_profile_digest is None
            or self.masked_profile.masked_profile_digest != self.masked_profile.canonical_digest()
        ):
            raise ValueError("worker requires a sealed masked profile")
        if not isinstance(self.inspection_profile, MaskInspectionProfileV1):
            raise ValueError("worker requires the sealed narrow inspection profile pin")
        if (
            self.inspection_profile.inspection_profile_digest is None
            or self.inspection_profile.inspection_profile_digest
            != self.inspection_profile.canonical_digest()
        ):
            raise ValueError("worker requires a sealed inspection profile")
        # New runtime: exact five pins, sealed. Never a V2 runtime.
        from ksi_event_contracts.external_masked_execution import MaskedExecutionRuntimeV3

        if not isinstance(self.execution_runtime, MaskedExecutionRuntimeV3):
            raise ValueError("worker requires the sealed five-pin execution runtime")
        runtime = self.execution_runtime
        if runtime.runtime_digest is None or runtime.runtime_digest != runtime.canonical_digest():
            raise ValueError("worker requires a sealed execution runtime")
        if self.inspection_profile.resource_envelope_digest != self.envelope.canonical_digest():
            raise ValueError("worker inspection profile must bind this resource envelope")
        value = self.maximum_response_bytes
        if isinstance(value, bool) or type(value) is not int or value <= 0:
            raise ValueError("worker maximum_response_bytes must be a positive integer")
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


class MaskedWorkflowCoreClient:
    """Bounded authenticated HTTP for the closed masked first-execution lane.

    Owns only its worker calls; object bytes travel through the separate
    pinned object transport and are never logged here. The Core bearer is
    attached only to the pinned Core origin, never to object-storage origins.
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

    def __enter__(self) -> MaskedWorkflowCoreClient:
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
        accepted: tuple[int, ...] = (200,),
    ) -> tuple[int, bytes]:
        if self._closed:
            raise MaskedWorkflowWorkerError("CLIENT_CLOSED")
        # Core-controlled URI paths only: the caller supplies opaque ids that
        # are percent-quoted into fixed templates; no caller URL is accepted.
        if "\r" in path or "\n" in path or ".." in path:
            raise MaskedWorkflowWorkerError("INVALID_CORE_PATH")
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
                    raise MaskedWorkflowWorkerError(f"CORE_HTTP_{response.status_code}")
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise MaskedWorkflowWorkerError("ENCODED_CORE_RESPONSE")
                data = bytearray()
                for chunk in response.iter_bytes():
                    if len(data) + len(chunk) > self._maximum_response_bytes:
                        raise MaskedWorkflowWorkerError("CORE_RESPONSE_LIMIT")
                    data.extend(chunk)
                return response.status_code, bytes(data)
        except MaskedWorkflowWorkerError:
            raise
        except (httpx.TimeoutException, TimeoutError):
            raise MaskedWorkflowWorkerError("CORE_HTTP_TIMEOUT") from None
        except httpx.HTTPError:
            raise MaskedWorkflowWorkerError("CORE_HTTP_UNAVAILABLE") from None

    def discover_inspection_pending(self, limit: int = 50) -> MaskInspectionPendingListV1:
        """Bounded worker-visible inspection discovery (Lead-owned pending)."""
        import json as _json

        if type(limit) is not int or isinstance(limit, bool) or limit < 1 or limit > 50:
            raise MaskedWorkflowWorkerError("INVALID_DISCOVERY_LIMIT")
        _, data = self._request(
            "GET",
            "v1/internal/mask-inspection-jobs/pending",
            params={"limit": limit},
        )
        try:
            decoded = _json.loads(data)
        except Exception:
            raise MaskedWorkflowWorkerError("INVALID_CORE_RESPONSE") from None
        try:
            page = MaskInspectionPendingListV1.model_validate(decoded)
        except ValidationError:
            raise MaskedWorkflowWorkerError("INVALID_CORE_RESPONSE") from None
        if len(page.items) > limit:
            raise MaskedWorkflowWorkerError("INVALID_CORE_RESPONSE")
        return page

    def discover_masked_pending(self, limit: int = 50) -> MaskedCalculationPendingListV1:
        """Bounded worker-visible V3 discovery (Lead-owned pending).

        Answers 503 with the exact owner hook until the parent wires the real
        ``list_queued_calculations`` listing; the worker treats that as a hint
        miss, never as an empty queue.
        """
        import json as _json

        if type(limit) is not int or isinstance(limit, bool) or limit < 1 or limit > 50:
            raise MaskedWorkflowWorkerError("INVALID_DISCOVERY_LIMIT")
        _, data = self._request(
            "GET",
            "v1/internal/masked-calculations/pending",
            params={"limit": limit},
        )
        try:
            decoded = _json.loads(data)
        except Exception:
            raise MaskedWorkflowWorkerError("INVALID_CORE_RESPONSE") from None
        try:
            page = MaskedCalculationPendingListV1.model_validate(decoded)
        except ValidationError:
            raise MaskedWorkflowWorkerError("INVALID_CORE_RESPONSE") from None
        if len(page.items) > limit:
            raise MaskedWorkflowWorkerError("INVALID_CORE_RESPONSE")
        return page

    def lease_inspection(
        self,
        spec: MaskedInspectionJobSpec,
        *,
        worker_instance_id: str,
        inspection_profile_digest: str,
        lease_acquisition_id: str,
    ) -> dict:
        import json as _json

        child = _masked_job_id(spec.mask_child_id)
        _resource_id(worker_instance_id, "WORKER_INSTANCE")
        _resource_id(lease_acquisition_id, "LEASE_ACQUISITION")
        _, data = self._request(
            "POST",
            f"v1/internal/mask-children/{quote(child, safe='')}/inspection-lease",
            headers={"Content-Type": "application/json"},
            body={
                "siteId": _path_segment(spec.site_id, "SITE"),
                "workAreaId": _path_segment(spec.work_area_id, "WORK_AREA"),
                "maskArtifactId": _masked_job_id(spec.mask_artifact_id),
                "subjectDigest": spec.subject_digest,
                "baselineSubject": spec.baseline_subject,
                "baselineDsmArtifactId": _masked_job_id(spec.baseline_dsm_artifact_id),
                "inspectionProfileDigest": inspection_profile_digest,
                "workerInstanceId": worker_instance_id,
                "leaseAcquisitionId": lease_acquisition_id,
            },
        )
        try:
            decoded = _json.loads(data)
        except Exception:
            raise MaskedWorkflowWorkerError("INVALID_CORE_RESPONSE") from None
        if not isinstance(decoded, dict) or decoded.get("maskChildId") != child:
            raise MaskedWorkflowWorkerError("LEASE_BINDING_MISMATCH")
        return decoded

    def fetch_inspection_bytes(
        self,
        *,
        mask_child_id: str,
        mask_artifact_id: str,
        offset: int,
        length: int,
        lease_id: str,
        worker_instance_id: str,
    ) -> bytes:
        import json as _json

        child = _masked_job_id(mask_child_id)
        artifact = _masked_job_id(mask_artifact_id)
        if type(offset) is not int or offset < 0:
            raise MaskedWorkflowWorkerError("INVALID_BYTE_RANGE")
        if type(length) is not int or length <= 0 or length > 1024 * 1024:
            raise MaskedWorkflowWorkerError("INVALID_BYTE_RANGE")
        _, data = self._request(
            "GET",
            f"v1/internal/mask-children/{quote(child, safe='')}/bytes",
            params={
                "mask_artifact_id": artifact,
                "offset": offset,
                "length": length,
                "lease_id": lease_id,
                "worker_instance_id": worker_instance_id,
            },
        )
        try:
            decoded = _json.loads(data)
        except Exception:
            raise MaskedWorkflowWorkerError("INVALID_CORE_RESPONSE") from None
        try:
            content = decoded["contentBase64"]
            returned_artifact = decoded.get("artifactId", artifact)
            returned_offset = decoded.get("offset", offset)
        except (KeyError, TypeError, AttributeError):
            raise MaskedWorkflowWorkerError("INVALID_CORE_RESPONSE") from None
        if returned_artifact != artifact or int(returned_offset) != offset:
            raise MaskedWorkflowWorkerError("BYTE_BINDING_MISMATCH")
        try:
            window = base64.b64decode(content, validate=True)
        except Exception:
            raise MaskedWorkflowWorkerError("INVALID_CORE_RESPONSE") from None
        if len(window) != length or base64.b64encode(window).decode("ascii") != content:
            raise MaskedWorkflowWorkerError("BYTE_BINDING_MISMATCH")
        return window

    def seal_inspection(
        self,
        *,
        mask_child_id: str,
        lease_id: str,
        worker_instance_id: str,
        report: dict,
        inspection_profile: dict,
    ) -> dict:
        import json as _json

        child = _masked_job_id(mask_child_id)
        _, data = self._request(
            "POST",
            f"v1/internal/mask-children/{quote(child, safe='')}:report",
            headers={"Content-Type": "application/json"},
            body={
                "leaseId": lease_id,
                "workerInstanceId": worker_instance_id,
                "report": report,
                "inspectionProfile": inspection_profile,
            },
        )
        try:
            decoded = _json.loads(data)
        except Exception:
            raise MaskedWorkflowWorkerError("INVALID_CORE_RESPONSE") from None
        if not isinstance(decoded, dict) or "manifest" not in decoded:
            raise MaskedWorkflowWorkerError("INVALID_CORE_RESPONSE") from None
        return decoded

    def fail_inspection(
        self,
        mask_child_id: str,
        *,
        lease_id: str,
        worker_instance_id: str,
        inspection_profile_digest: str,
        reason: str,
    ) -> None:
        """Best-effort fenced inspection failure (additive endpoint).

        Exact owner wire: live lease fence (lease id, worker instance, sealed
        inspection profile digest) plus one closed reason code only — never
        byte content, grids, profiles beyond the digest, coordinates, accuracy,
        or native traces, and never an untrusted error path for Core to store.
        Core re-binds the live lease, worker, profile, and activation on
        receipt; any rejection (including 404 while the endpoint is still
        landing) fails closed with no caller effect. Callers always suppress
        and still return FAILED.
        """
        from ksi_event_contracts.external_masked_api import MaskInspectionFailureReasonV1

        allowed: tuple[str, ...] = (
            "MASK_NODATA_REJECTED",
            "MASK_BYTES_MISMATCH",
            "MASK_RESOURCE_EXCEEDED",
            "MASK_INSPECTION_FAILED",
        )
        child = _masked_job_id(mask_child_id)
        if not isinstance(lease_id, str) or not lease_id.strip():
            raise MaskedWorkflowWorkerError("INVALID_LEASE_FENCE")
        if reason not in allowed:
            raise MaskedWorkflowWorkerError("INVALID_FAILURE_REASON")
        _ = MaskInspectionFailureReasonV1
        self._request(
            "POST",
            f"v1/internal/mask-children/{quote(child, safe='')}:inspection-failure",
            headers={"Content-Type": "application/json"},
            body={
                "leaseId": lease_id,
                "workerInstanceId": _resource_id(worker_instance_id, "WORKER_INSTANCE"),
                "inspectionProfileDigest": inspection_profile_digest,
                "reasonCode": reason,
            },
        )

    def lease_masked_calculation(
        self, request_id: str, *, worker_instance_id: str, lease_acquisition_id: str
    ) -> dict:
        import json as _json

        rid = _masked_job_id(request_id)
        _, data = self._request(
            "POST",
            f"v1/internal/masked-calculations/{quote(rid, safe='')}:lease",
            headers={"Content-Type": "application/json"},
            body={
                "workerInstanceId": _resource_id(worker_instance_id, "WORKER_INSTANCE"),
                "leaseAcquisitionId": _resource_id(lease_acquisition_id, "LEASE_ACQUISITION"),
            },
        )
        try:
            decoded = _json.loads(data)
        except Exception:
            raise MaskedWorkflowWorkerError("INVALID_CORE_RESPONSE") from None
        try:
            attempt = decoded["attempt"]
        except (KeyError, TypeError):
            raise MaskedWorkflowWorkerError("INVALID_CORE_RESPONSE") from None
        if decoded.get("requestId") != rid:
            raise MaskedWorkflowWorkerError("LEASE_BINDING_MISMATCH")
        _ = attempt
        return decoded

    def fetch_masked_input(
        self, request_id: str, *, attempt_digest: str, worker_instance_id: str
    ) -> MaskedWorkerInputV3:
        import json as _json

        rid = _masked_job_id(request_id)
        _, data = self._request(
            "GET",
            f"v1/internal/masked-calculations/{quote(rid, safe='')}/input",
            headers={
                "X-Masked-Attempt-Digest": attempt_digest,
                "X-Masked-Worker-Instance-Id": _resource_id(worker_instance_id, "WORKER_INSTANCE"),
            },
        )
        try:
            decoded = _json.loads(data)
        except Exception:
            raise MaskedWorkflowWorkerError("INVALID_CORE_RESPONSE") from None
        try:
            worker_input = MaskedWorkerInputV3.model_validate(decoded)
        except ValidationError:
            raise MaskedWorkflowWorkerError("INVALID_CORE_RESPONSE") from None
        if worker_input.masked_request_id != rid or worker_input.attempt.worker_instance_id != (
            worker_instance_id
        ):
            raise MaskedWorkflowWorkerError("INPUT_BINDING_MISMATCH")
        return worker_input

    def fetch_masked_bytes(
        self,
        request_id: str,
        role: str,
        *,
        offset: int,
        length: int,
        attempt_digest: str,
        worker_instance_id: str,
    ) -> bytes:
        import json as _json

        rid = _masked_job_id(request_id)
        if role not in ("BASELINE_DSM", "CURRENT_DSM", "EXCLUSION_MASK"):
            raise MaskedWorkflowWorkerError("INVALID_INPUT_ROLE")
        if type(offset) is not int or offset < 0:
            raise MaskedWorkflowWorkerError("INVALID_BYTE_RANGE")
        if type(length) is not int or length <= 0 or length > 1024 * 1024:
            raise MaskedWorkflowWorkerError("INVALID_BYTE_RANGE")
        _, data = self._request(
            "GET",
            f"v1/internal/masked-calculations/{quote(rid, safe='')}/inputs/{role}/bytes",
            params={"offset": offset, "length": length},
            headers={
                "X-Masked-Attempt-Digest": attempt_digest,
                "X-Masked-Worker-Instance-Id": _resource_id(worker_instance_id, "WORKER_INSTANCE"),
            },
        )
        try:
            decoded = _json.loads(data)
        except Exception:
            raise MaskedWorkflowWorkerError("INVALID_CORE_RESPONSE") from None
        try:
            content = decoded["contentBase64"]
        except (KeyError, TypeError):
            raise MaskedWorkflowWorkerError("INVALID_CORE_RESPONSE") from None
        try:
            window = base64.b64decode(content, validate=True)
        except Exception:
            raise MaskedWorkflowWorkerError("INVALID_CORE_RESPONSE") from None
        if len(window) != length or base64.b64encode(window).decode("ascii") != content:
            raise MaskedWorkflowWorkerError("BYTE_BINDING_MISMATCH")
        return window

    def fetch_dsm_input(
        self, request_id: str, *, attempt_digest: str, worker_instance_id: str
    ) -> MaskedWorkflowDsmInputViewV1:
        import json as _json

        rid = _masked_job_id(request_id)
        _, data = self._request(
            "GET",
            f"v1/internal/masked-calculations/{quote(rid, safe='')}/dsm-input",
            headers={
                "X-Masked-Attempt-Digest": attempt_digest,
                "X-Masked-Worker-Instance-Id": _resource_id(worker_instance_id, "WORKER_INSTANCE"),
            },
        )
        try:
            decoded = _json.loads(data)
        except Exception:
            raise MaskedWorkflowWorkerError("INVALID_CORE_RESPONSE") from None
        try:
            view = MaskedWorkflowDsmInputViewV1.model_validate(decoded)
        except ValidationError:
            raise MaskedWorkflowWorkerError("INVALID_CORE_RESPONSE") from None
        if view.request_id != rid or view.worker_instance_id != worker_instance_id:
            raise MaskedWorkflowWorkerError("INPUT_BINDING_MISMATCH")
        return view

    def report_masked(self, request_id: str, *, attempt: dict, report: dict) -> dict:
        import json as _json

        rid = _masked_job_id(request_id)
        _, data = self._request(
            "POST",
            f"v1/internal/masked-calculations/{quote(rid, safe='')}:report",
            headers={"Content-Type": "application/json"},
            body={"attempt": attempt, "report": report},
        )
        try:
            decoded = _json.loads(data)
        except Exception:
            raise MaskedWorkflowWorkerError("INVALID_CORE_RESPONSE") from None
        if decoded.get("requestId") != rid or decoded.get("status") != "COMPLETED":
            raise MaskedWorkflowWorkerError("REPORT_BINDING_MISMATCH")
        return decoded

    def fail_masked(self, request_id: str, *, attempt: dict, failure: dict) -> None:
        rid = _masked_job_id(request_id)
        try:
            self._request(
                "POST",
                f"v1/internal/masked-calculations/{quote(rid, safe='')}:failure",
                headers={"Content-Type": "application/json"},
                body={"attempt": attempt, "failure": failure},
            )
        except MaskedWorkflowWorkerError:
            return


def _capability_input(item: object) -> MeasurementInputV2:
    """Narrow an opaque Core-issued DSM capability to the object-transport input.

    Every field is validated before construction: the role must be one of the
    exact transport literals, texts must be non-empty, and the size must be a
    positive integer (booleans rejected). No cast without validation.
    """
    role_value = getattr(item, "role", None)
    artifact_value = getattr(item, "artifact_id", None)
    sha_value = getattr(item, "observed_sha256", None)
    size_value = getattr(item, "observed_size_bytes", None)
    if role_value == "TARGET_DSM":
        role: Literal["TARGET_DSM", "CHECKPOINT_CSV", "BASELINE_DSM", "CURRENT_DSM"] = "TARGET_DSM"
    elif role_value == "CHECKPOINT_CSV":
        role = "CHECKPOINT_CSV"
    elif role_value == "BASELINE_DSM":
        role = "BASELINE_DSM"
    elif role_value == "CURRENT_DSM":
        role = "CURRENT_DSM"
    else:
        raise MaskedWorkflowWorkerError("INPUT_BINDING_MISMATCH")
    if not isinstance(artifact_value, str) or not artifact_value:
        raise MaskedWorkflowWorkerError("INPUT_BINDING_MISMATCH")
    if not isinstance(sha_value, str) or not sha_value:
        raise MaskedWorkflowWorkerError("INPUT_BINDING_MISMATCH")
    if isinstance(size_value, bool) or not isinstance(size_value, int) or size_value <= 0:
        raise MaskedWorkflowWorkerError("INPUT_BINDING_MISMATCH")
    return MeasurementInputV2(
        role=role,
        artifact_id=artifact_value,
        observed_sha256=sha_value,
        observed_size_bytes=size_value,
    )


def _ensure_private_work_root(work_dir: Path) -> Path:
    if work_dir.is_symlink():
        raise MaskedWorkflowWorkerError("INPUT_WORKSPACE_UNAVAILABLE")
    work_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    try:
        os.chmod(work_dir, 0o700)
    except OSError as exc:
        raise MaskedWorkflowWorkerError("INPUT_WORKSPACE_UNAVAILABLE") from exc
    try:
        mode = stat.S_IMODE(os.stat(work_dir).st_mode)
    except OSError as exc:
        raise MaskedWorkflowWorkerError("INPUT_WORKSPACE_UNAVAILABLE") from exc
    if work_dir.is_symlink() or mode & 0o077:
        raise MaskedWorkflowWorkerError("INPUT_WORKSPACE_UNAVAILABLE")
    return work_dir


def _fresh_attempt_dir(work_dir: Path, *parts: str) -> Path:
    for part in parts:
        if not part or part in {"", ".", ".."} or "/" in part or "\\" in part:
            raise MaskedWorkflowWorkerError("INPUT_WORKSPACE_UNAVAILABLE")
        if _PATH_SEGMENT_RE.fullmatch(part) is None and len(part) > 128:
            raise MaskedWorkflowWorkerError("INPUT_WORKSPACE_UNAVAILABLE")
    root = _ensure_private_work_root(work_dir)
    parent = root.joinpath(*parts[:-1]) if len(parts) > 1 else root
    if parent.is_symlink():
        raise MaskedWorkflowWorkerError("INPUT_WORKSPACE_UNAVAILABLE")
    parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if not parent.is_dir() or parent.is_symlink():
        raise MaskedWorkflowWorkerError("INPUT_WORKSPACE_UNAVAILABLE")
    leaf = root.joinpath(*parts)
    try:
        leaf.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise MaskedWorkflowWorkerError("INPUT_WORKSPACE_UNAVAILABLE") from exc
    try:
        os.chmod(leaf, 0o700)
    except OSError as exc:
        raise MaskedWorkflowWorkerError("INPUT_WORKSPACE_UNAVAILABLE") from exc
    if leaf.is_symlink():
        raise MaskedWorkflowWorkerError("INPUT_WORKSPACE_UNAVAILABLE")
    return leaf


def _write_private_bytes(*, work_dir: Path, name: str, payload: bytes) -> Path:
    if "/" in name or "\\" in name or name in {"", ".", ".."}:
        raise MaskedWorkflowWorkerError("INPUT_WORKSPACE_UNAVAILABLE")
    target = work_dir / name
    if target.exists() or target.is_symlink():
        raise MaskedWorkflowWorkerError("INPUT_WORKSPACE_UNAVAILABLE")
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    try:
        view = memoryview(payload)
        while view:
            count = os.write(descriptor, view)
            if count <= 0:
                raise MaskedWorkflowWorkerError("INPUT_WORKSPACE_UNAVAILABLE")
            view = view[count:]
    finally:
        os.close(descriptor)
    return target


def _private_download_object(
    *,
    source: ExternalObjectHttpByteSource,
    artifact: MeasurementInputV2,
    path: Path,
    deadline: ProtocolDeadline,
    is_current: Callable[[], bool],
    heartbeat_interval_millis: int,
    max_chunk_bytes: int,
) -> None:
    if path.exists() or path.is_symlink():
        raise MaskedWorkflowWorkerError("INPUT_WORKSPACE_UNAVAILABLE")
    reader = None
    descriptor = None
    try:
        if not is_current():
            raise MaskedWorkflowWorkerError("AUTHORITY_LOST")
        deadline.remaining()
        reader = source.open_bound_bytes(
            artifact,
            deadline=deadline,
            wait_is_current=is_current,
            heartbeat_interval_millis=heartbeat_interval_millis,
        )
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
        digest = hashlib.sha256()
        remaining = artifact.observed_size_bytes
        while remaining:
            if not is_current():
                raise MaskedWorkflowWorkerError("AUTHORITY_LOST")
            deadline.remaining()
            chunk = reader.read_chunk(
                min(remaining, max_chunk_bytes),
                deadline=deadline,
                wait_is_current=is_current,
                heartbeat_interval_millis=heartbeat_interval_millis,
            )
            if not chunk or len(chunk) > remaining:
                raise MaskedWorkflowWorkerError("INPUT_BYTE_STREAM_INVALID")
            written = 0
            while written < len(chunk):
                count = os.write(descriptor, chunk[written:])
                if count <= 0:
                    raise MaskedWorkflowWorkerError("INPUT_WORKSPACE_UNAVAILABLE")
                written += count
            digest.update(chunk)
            remaining -= len(chunk)
        if not is_current():
            raise MaskedWorkflowWorkerError("AUTHORITY_LOST")
        deadline.remaining()
        if reader.read_chunk(
            1,
            deadline=deadline,
            wait_is_current=is_current,
            heartbeat_interval_millis=heartbeat_interval_millis,
        ):
            raise MaskedWorkflowWorkerError("INPUT_BYTE_STREAM_INVALID")
        if (
            "sha256:" + digest.hexdigest() != artifact.observed_sha256
            or os.fstat(descriptor).st_size != artifact.observed_size_bytes
        ):
            raise MaskedWorkflowWorkerError("INPUT_BYTE_STREAM_INVALID")
    except (ProtocolViolation, ExternalObjectTransportError) as exc:
        if isinstance(exc, ExternalObjectTransportError) and exc.code in {
            "AUTHORITY_LOST",
            "INPUT_CAPABILITY_UNAVAILABLE",
        }:
            raise MaskedWorkflowWorkerError(exc.code) from None
        raise MaskedWorkflowWorkerError("INPUT_OBJECT_TRANSPORT_FAILED") from None
    finally:
        if reader is not None:
            reader.close()
        if descriptor is not None:
            os.close(descriptor)


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


def _failure_for_dispatch(
    *, masked_identity_digest: str, report_id: str, reason: str, failed_at: datetime
) -> MaskedVolumeCalculationFailureV3:
    failure_id = "failure-" + hashlib.sha256(report_id.encode("utf-8")).hexdigest()[:32]
    return MaskedVolumeCalculationFailureV3(
        failure_id=failure_id,
        masked_calculation_identity_digest=masked_identity_digest,
        reason_code=reason,
        failed_at=failed_at,
    ).sealed()


_INSPECTION_FAILURE_REASONS = frozenset(
    {
        "MASK_NODATA_REJECTED",
        "MASK_BYTES_MISMATCH",
        "MASK_RESOURCE_EXCEEDED",
        "MASK_INSPECTION_FAILED",
    }
)


def _inspection_failure_reason(code: object) -> str:
    """Bounded map from worker failure codes to the exact owner reason codes.

    Only the four closed owner codes are ever emitted (Core rejects anything
    else): deterministic native input rejections keep their exact byte meaning
    (NoData passthrough, byte/shape/grid mismatch incl. chunk-sha and binding
    mismatch, resource caps); stale leases, lost authority, transport/binding
    failures, and unexpected IO all collapse to the generic closed code. No
    byte content, grids, coordinates, or accuracy detail ever travels — reason
    only.
    """
    if code == "MASK_NODATA_REJECTED":
        return "MASK_NODATA_REJECTED"
    if code in {"MASK_BYTES_MISMATCH", "INPUT_BYTE_STREAM_INVALID", "SEAL_BINDING_MISMATCH"}:
        return "MASK_BYTES_MISMATCH"
    if code == "RESOURCE_LIMIT_EXCEEDED":
        return "MASK_RESOURCE_EXCEEDED"
    if isinstance(code, str) and code in _INSPECTION_FAILURE_REASONS:
        return code
    return "MASK_INSPECTION_FAILED"


def _record_inspection_failure_best_effort(
    *,
    core_client: MaskedWorkflowCoreClient,
    mask_child_id: str,
    lease_id: str | None,
    worker_instance_id: str,
    inspection_profile_digest: str,
    reason: str,
) -> None:
    """Best-effort fenced inspection failure; never raises.

    Without a bound lease there is no fence to record against (wrong worker,
    missing announcement, unleased child): fail closed with no post. Any Core
    rejection — including 404 while the additive endpoint is still landing —
    is suppressed; the caller still returns FAILED and Core stores nothing
    untrusted.
    """
    if lease_id is None:
        return
    # Narrow suppression is deliberate: only expected Core fence/transport
    # rejections are best-effort. Programming errors propagate loudly instead
    # of hiding behind a catch-all.
    with contextlib.suppress(MaskedWorkflowWorkerError):
        core_client.fail_inspection(
            mask_child_id,
            lease_id=lease_id,
            worker_instance_id=worker_instance_id,
            inspection_profile_digest=inspection_profile_digest,
            reason=reason,
        )


def run_mask_inspection_job(
    *,
    config: MaskedWorkflowWorkerConfig,
    core_client: MaskedWorkflowCoreClient,
    spec: MaskedInspectionJobSpec,
    worker_instance_id: str,
    lease_acquisition_id: str | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    maximum_wall_seconds: float | None = None,
    check_current: Callable[[], None] | None = None,
    deadline_monotonic: float | None = None,
    report_id: str | None = None,
    now_fn: Callable[[], datetime] | None = None,
) -> Literal["SEALED", "FAILED", "SKIPPED"]:
    """Run one narrow inspection job end-to-end with closed failure semantics.

    Deterministic native input rejections (NoData, non-binary/shape/grid
    mismatch, over-cap bytes) post a fenced closed failure reason against the
    live lease instead of only returning local FAILED, so the Console can show
    a reason status rather than a perpetual null manifest. Wrong-worker, stale
    lease, and missing-authority paths cannot mint a report: they best-effort
    post against the held lease (which fails closed when the fence is gone)
    and return FAILED. Core never stores untrusted error paths.
    """
    guard = check_current or (lambda: None)
    cancel = is_cancelled or (lambda: False)
    clock = now_fn or _utc_now
    acquisition = lease_acquisition_id or config.lease_acquisition_id
    _masked_job_id(spec.mask_child_id)
    _masked_job_id(spec.mask_artifact_id)
    _path_segment(spec.site_id, "SITE")
    _path_segment(spec.work_area_id, "WORK_AREA")
    if spec.declared_size_bytes <= 0 or spec.declared_size_bytes > min(
        config.envelope.max_input_bytes, config.envelope.max_streamed_bytes
    ):
        raise MaskedWorkflowWorkerError("INVALID_JOB_SPEC")
    attempt_dir: Path | None = None
    lease_id: str | None = None
    try:
        if cancel():
            return "SKIPPED"
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

        try:
            lease_view = core_client.lease_inspection(
                spec,
                worker_instance_id=worker_instance_id,
                inspection_profile_digest=config.inspection_profile.canonical_digest(),
                lease_acquisition_id=acquisition,
            )
        except MaskedWorkflowWorkerError as exc:
            if exc.code in {"CORE_HTTP_404", "CORE_HTTP_409"}:
                return "SKIPPED"
            return "FAILED"
        try:
            lease_id = str(lease_view["leaseId"])
            expected_rows = int(lease_view["expectedRows"])
            expected_columns = int(lease_view["expectedColumns"])
            expected_transform = tuple(lease_view["expectedTransform"])
            expected_transform_digest = str(lease_view["expectedTransformDigest"])
            expected_crs = str(lease_view["expectedCrsIdentifier"])
            expected_crs_digest = str(lease_view["expectedCrsDigest"])
            lease_expires = datetime.fromisoformat(
                str(lease_view["expiresAt"]).replace("Z", "+00:00")
            )
        except (KeyError, TypeError, ValueError):
            raise MaskedWorkflowWorkerError("INVALID_CORE_RESPONSE") from None
        if cancel():
            return "FAILED"
        if not _is_current():
            raise MaskedWorkflowWorkerError("AUTHORITY_LOST")
        if clock() >= lease_expires:
            raise MaskedWorkflowWorkerError("STALE_LEASE")
        # Private workdir: 0700 snapshot owned, no symlink/stale reuse.
        attempt_dir = _fresh_attempt_dir(
            config.work_dir,
            "mask-inspection",
            spec.mask_child_id,
            worker_instance_id,
            lease_id[:16],
        )
        total = spec.declared_size_bytes
        fetched = bytearray()
        offset = 0
        while offset < total:
            if cancel() or not _is_current():
                raise MaskedWorkflowWorkerError("WORKER_CANCELLED")
            deadline.remaining()
            length = min(1024 * 1024, total - offset)
            try:
                window = core_client.fetch_inspection_bytes(
                    mask_child_id=spec.mask_child_id,
                    mask_artifact_id=spec.mask_artifact_id,
                    offset=offset,
                    length=length,
                    lease_id=lease_id,
                    worker_instance_id=worker_instance_id,
                )
            except MaskedWorkflowWorkerError:
                raise
            fetched.extend(window)
            offset += len(window)
        if len(fetched) != total or ("sha256:" + hashlib.sha256(bytes(fetched)).hexdigest()) != (
            spec.declared_sha256
        ):
            raise MaskedWorkflowWorkerError("INPUT_BYTE_STREAM_INVALID")
        if cancel() or not _is_current():
            raise MaskedWorkflowWorkerError("WORKER_CANCELLED")
        deadline.remaining()
        staged = _write_private_bytes(work_dir=attempt_dir, name="mask.tif", payload=bytes(fetched))
        if cancel() or not _is_current():
            raise MaskedWorkflowWorkerError("WORKER_CANCELLED")
        deadline.remaining()
        # Retry/deadline/cancel after I/O before the native dispatch.
        watchdog = _watchdog_from_envelope(
            config.envelope, is_cancelled=cancel, maximum_wall_seconds=maximum_wall_seconds
        )
        computed_report_id = report_id or ("narrow-report-" + uuid.uuid4().hex[:12])
        reported_at = clock()
        try:
            narrow_report = inspect_mask_bytes_v1(
                path=staged,
                envelope=config.envelope,
                watchdog=watchdog,
                organization_id=_spec_org(spec),
                site_id=spec.site_id,
                work_area_id=spec.work_area_id,
                mask_child_id=spec.mask_child_id,
                mask_artifact_id=spec.mask_artifact_id,
                subject=spec.parent_subject,
                inspection_profile=config.inspection_profile,
                contained_runtime_digest=_masked_inspection_runtime_digest_local(
                    config.inspection_profile
                ),
                inspector_build_digest=config.inspection_profile.worker_build_digest,
                expected_crs_identifier=expected_crs,
                expected_crs_digest=expected_crs_digest,
                expected_transform=tuple(expected_transform),
                expected_transform_digest=expected_transform_digest,
                report_id=computed_report_id,
                reported_at=reported_at,
            )
        except MaskInspectionError as exc:
            raise MaskedWorkflowWorkerError(exc.reason or "MASK_INSPECTION_FAILED") from None
        if cancel() or not _is_current():
            raise MaskedWorkflowWorkerError("WORKER_CANCELLED")
        deadline.remaining()
        if clock() >= lease_expires:
            raise MaskedWorkflowWorkerError("STALE_LEASE")
        try:
            sealed = core_client.seal_inspection(
                mask_child_id=spec.mask_child_id,
                lease_id=lease_id,
                worker_instance_id=worker_instance_id,
                report=narrow_report.model_dump(by_alias=True, mode="json"),
                inspection_profile=config.inspection_profile.model_dump(by_alias=True, mode="json"),
            )
        except MaskedWorkflowWorkerError:
            raise
        manifest = sealed.get("manifest", {})
        if manifest.get("observedSha256") != spec.declared_sha256:
            raise MaskedWorkflowWorkerError("SEAL_BINDING_MISMATCH")
        _ = (expected_rows, expected_columns)
        return "SEALED"
    except MaskedWorkflowWorkerError as exc:
        if not cancel() and lease_id is not None:
            _record_inspection_failure_best_effort(
                core_client=core_client,
                mask_child_id=spec.mask_child_id,
                lease_id=lease_id,
                worker_instance_id=worker_instance_id,
                inspection_profile_digest=config.inspection_profile.canonical_digest(),
                reason=_inspection_failure_reason(exc.code),
            )
        return "FAILED"
    except (MeasurementAlgorithmIncomplete, Exception):
        if not cancel() and lease_id is not None:
            _record_inspection_failure_best_effort(
                core_client=core_client,
                mask_child_id=spec.mask_child_id,
                lease_id=lease_id,
                worker_instance_id=worker_instance_id,
                inspection_profile_digest=config.inspection_profile.canonical_digest(),
                reason="MASK_INSPECTION_FAILED",
            )
        return "FAILED"
    finally:
        if attempt_dir is not None:
            import contextlib as _contextlib

            with _contextlib.suppress(OSError):
                for child in sorted(attempt_dir.iterdir()):
                    with _contextlib.suppress(OSError):
                        if child.is_file() and not child.is_symlink():
                            child.unlink()
                attempt_dir.rmdir()


def _spec_org(spec: MaskedInspectionJobSpec) -> str:
    """Organization is Core-owned: explicit spec field from the human create."""
    if spec.organization_id:
        return spec.organization_id
    for candidate in (spec.parent_subject, spec.baseline_subject):
        if isinstance(candidate, dict):
            for key in ("organizationId", "organization_id"):
                value = candidate.get(key)
                if isinstance(value, str) and value:
                    return value
    return ""


def run_masked_calculation_job(
    *,
    config: MaskedWorkflowWorkerConfig,
    core_client: MaskedWorkflowCoreClient,
    request_id: str,
    worker_principal_id: str,
    worker_instance_id: str,
    lease_acquisition_id: str | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    maximum_wall_seconds: float | None = None,
    check_current: Callable[[], None] | None = None,
    deadline_monotonic: float | None = None,
    report_id: str | None = None,
    now_fn: Callable[[], datetime] | None = None,
) -> Literal["COMPLETED", "FAILED", "SKIPPED"]:
    """Run one V3 calculation job end-to-end (first execution, not late export)."""
    guard = check_current or (lambda: None)
    cancel = is_cancelled or (lambda: False)
    clock = now_fn or _utc_now
    acquisition = lease_acquisition_id or config.lease_acquisition_id
    rid = _masked_job_id(request_id)
    attempt_dir: Path | None = None
    lease_generation: int | None = None
    live_attempt: dict | None = None
    try:
        if cancel():
            return "SKIPPED"
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

        try:
            leased = core_client.lease_masked_calculation(
                rid,
                worker_instance_id=worker_instance_id,
                lease_acquisition_id=acquisition,
            )
        except MaskedWorkflowWorkerError as exc:
            if exc.code in {"CORE_HTTP_404", "CORE_HTTP_409"}:
                return "SKIPPED"
            return "FAILED"
        try:
            live_attempt = leased["attempt"]
            lease_generation = int(live_attempt["leaseGeneration"])
            attempt_digest = str(live_attempt["executionAttemptDigest"])
            lease_expires_at = datetime.fromisoformat(
                str(live_attempt["leaseExpiresAt"]).replace("Z", "+00:00")
            )
        except (KeyError, TypeError, ValueError):
            return "FAILED"
        if lease_generation <= 0 or cancel() or not _is_current():
            return "FAILED"
        if clock() >= lease_expires_at:
            return "FAILED"
        try:
            worker_input = core_client.fetch_masked_input(
                rid, attempt_digest=attempt_digest, worker_instance_id=worker_instance_id
            )
        except MaskedWorkflowWorkerError:
            return "FAILED"
        # Closed pin checks against the operator-supplied sealed lane pins.
        if (
            worker_input.masked_calculation_identity.masked_profile_digest
            != config.masked_profile.canonical_digest()
        ):
            return "FAILED"
        if worker_input.attempt.worker_instance_id != worker_instance_id:
            return "FAILED"
        if worker_input.attempt.authorization.worker_principal_id != worker_principal_id:
            # The V3 authorization binds the designated lane worker as the
            # expected owner (store pins the real ANALYSIS_WORKER at issue;
            # a borrowed V2 worker identity or a human issuer id fails closed
            # here). Core additionally enforces the designated bearer on every
            # fenced call. Never relaxed to green tests.
            return "FAILED"
        if [item.role for item in worker_input.inputs] != [
            "BASELINE_DSM",
            "CURRENT_DSM",
            "EXCLUSION_MASK",
        ]:
            return "FAILED"
        for capability in worker_input.inputs:
            if capability.expires_at > worker_input.attempt.lease_expires_at:
                return "FAILED"
        if cancel() or not _is_current():
            return "FAILED"
        deadline.remaining()
        # New DSM leg: two direct sealed capabilities via the Core DSM seam;
        # the mask leg stays on the Core-bearer EXCLUSION_MASK window.
        try:
            dsm_view = core_client.fetch_dsm_input(
                rid, attempt_digest=attempt_digest, worker_instance_id=worker_instance_id
            )
        except MaskedWorkflowWorkerError:
            return "FAILED"
        if (
            dsm_view.masked_calculation_identity_digest
            != worker_input.masked_calculation_identity.masked_calculation_identity_digest
            or dsm_view.source_calculation_identity_digest
            != worker_input.masked_calculation_identity.source_calculation_identity_digest
            or dsm_view.attempt_digest != attempt_digest
            or dsm_view.lease_generation != lease_generation
        ):
            return "FAILED"
        baseline_cap, current_cap = dsm_view.capabilities
        expected_dsm = tuple(
            (item.artifact_id, item.observed_sha256, item.observed_size_bytes)
            for item in worker_input.inputs[:2]
        )
        supplied_dsm = tuple(
            (item.artifact_id, item.observed_sha256, item.observed_size_bytes)
            for item in (baseline_cap, current_cap)
        )
        if supplied_dsm != expected_dsm:
            return "FAILED"
        # Lane-seal pin checks BEFORE any object download or native parse.
        # The declared model runtime/envelope/activation must equal the
        # signed Core-authorized values; a mismatch fails closed here with
        # no bytes fetched and no native invocation. This pin is not an OS
        # sandbox claim: native containment remains separately gated.
        try:
            expected_runtime_digest = _expected_lane_runtime_digest(config)
        except MaskedWorkflowWorkerError:
            return "FAILED"
        authorized_envelope_digest = worker_input.attempt.authorization.resource_envelope_digest
        authorized_activation_digest = worker_input.attempt.authorization.activation_digest
        if (
            dsm_view.execution_runtime_digest != expected_runtime_digest
            or dsm_view.resource_envelope_digest != config.envelope.canonical_digest()
            or dsm_view.resource_envelope_digest != authorized_envelope_digest
            or authorized_envelope_digest != config.envelope.canonical_digest()
            or dsm_view.activation_digest != authorized_activation_digest
        ):
            # Best-effort terminal post only; programming errors propagate
            # loudly instead of hiding behind a catch-all.
            with contextlib.suppress(MaskedWorkflowWorkerError):
                core_client.fail_masked(
                    rid,
                    attempt=live_attempt,
                    failure=_failure_for_dispatch(
                        masked_identity_digest=(
                            worker_input.masked_calculation_identity.masked_calculation_identity_digest
                            or ""
                        ),
                        report_id=report_id or ("report-" + uuid.uuid4().hex[:12]),
                        reason="MASKED_RUNTIME_MISMATCH",
                        failed_at=clock(),
                    ).model_dump(by_alias=True, mode="json"),
                )
            return "FAILED"
        mask_cap = worker_input.inputs[2]
        attempt_dir = _fresh_attempt_dir(
            config.work_dir,
            "masked-calculation",
            rid,
            worker_instance_id,
            str(lease_generation),
        )
        # Pinned object downloads for the two DSM legs (never a Core bearer).
        source = ExternalObjectHttpByteSource(
            (
                ExternalObjectCapabilityV1(
                    artifact=_capability_input(baseline_cap),
                    url=baseline_cap.download_url,
                    required_headers=dict(baseline_cap.required_headers),
                ),
                ExternalObjectCapabilityV1(
                    artifact=_capability_input(current_cap),
                    url=current_cap.download_url,
                    required_headers=dict(current_cap.required_headers),
                ),
            ),
            policy=config.transport_policy,
        )
        baseline_path = attempt_dir / "baseline.tif"
        current_path = attempt_dir / "current.tif"
        _private_download_object(
            source=source,
            artifact=_capability_input(baseline_cap),
            path=baseline_path,
            deadline=deadline,
            is_current=_is_current,
            heartbeat_interval_millis=config.heartbeat_interval_millis,
            max_chunk_bytes=config.max_chunk_bytes,
        )
        _private_download_object(
            source=source,
            artifact=_capability_input(current_cap),
            path=current_path,
            deadline=deadline,
            is_current=_is_current,
            heartbeat_interval_millis=config.heartbeat_interval_millis,
            max_chunk_bytes=config.max_chunk_bytes,
        )
        # Mask leg via the Core-bearer protected window (never object S3).
        mask_total = mask_cap.observed_size_bytes
        if mask_total <= 0 or mask_total > min(
            config.envelope.max_input_bytes, config.envelope.max_streamed_bytes
        ):
            raise MaskedWorkflowWorkerError("RESOURCE_LIMIT_EXCEEDED")
        mask_bytes = bytearray()
        mask_offset = 0
        while mask_offset < mask_total:
            if cancel() or not _is_current():
                raise MaskedWorkflowWorkerError("WORKER_CANCELLED")
            deadline.remaining()
            window = core_client.fetch_masked_bytes(
                rid,
                "EXCLUSION_MASK",
                offset=mask_offset,
                length=min(1024 * 1024, mask_total - mask_offset),
                attempt_digest=attempt_digest,
                worker_instance_id=worker_instance_id,
            )
            mask_bytes.extend(window)
            mask_offset += len(window)
        if (
            len(mask_bytes) != mask_total
            or ("sha256:" + hashlib.sha256(bytes(mask_bytes)).hexdigest())
            != mask_cap.observed_sha256
        ):
            raise MaskedWorkflowWorkerError("INPUT_BYTE_STREAM_INVALID")
        mask_path = _write_private_bytes(
            work_dir=attempt_dir, name="mask.tif", payload=bytes(mask_bytes)
        )
        if cancel() or not _is_current():
            raise MaskedWorkflowWorkerError("WORKER_CANCELLED")
        deadline.remaining()
        # Retry/deadline/cancel after I/O: re-prove the live fence before dispatch.
        try:
            fresh_input = core_client.fetch_masked_input(
                rid, attempt_digest=attempt_digest, worker_instance_id=worker_instance_id
            )
        except MaskedWorkflowWorkerError:
            raise MaskedWorkflowWorkerError("STALE_LEASE") from None
        if (
            fresh_input.masked_calculation_identity.masked_calculation_identity_digest
            != worker_input.masked_calculation_identity.masked_calculation_identity_digest
        ):
            raise MaskedWorkflowWorkerError("STALE_LEASE")
        if clock() >= lease_expires_at:
            raise MaskedWorkflowWorkerError("STALE_LEASE")
        watchdog = _watchdog_from_envelope(
            config.envelope, is_cancelled=cancel, maximum_wall_seconds=maximum_wall_seconds
        )
        computed_report_id = report_id or ("report-" + uuid.uuid4().hex[:12])
        computed_at = clock()
        reported_at = clock()
        try:
            outcome = dispatch_masked_execution_v3(
                worker_input=fresh_input,
                files=MaskedDispatchInputsV3(
                    baseline_path=baseline_path,
                    current_path=current_path,
                    mask_path=mask_path,
                ),
                envelope=config.envelope,
                watchdog=watchdog,
                lease_expires_at=lease_expires_at,
                report_id=computed_report_id,
                computed_at=computed_at,
                reported_at=reported_at,
            )
        except MaskedExecutionDispatchError as exc:
            try:
                failure = _failure_for_dispatch(
                    masked_identity_digest=(
                        fresh_input.masked_calculation_identity.masked_calculation_identity_digest
                        or ""
                    ),
                    report_id=computed_report_id,
                    reason=exc.reason,
                    failed_at=clock(),
                )
                core_client.fail_masked(
                    rid,
                    attempt=live_attempt,
                    failure=failure.model_dump(by_alias=True, mode="json"),
                )
            except MaskedWorkflowWorkerError:
                # Best-effort terminal post only; programming errors propagate
                # loudly instead of hiding behind a catch-all.
                pass
            return "FAILED"
        if cancel() or not _is_current():
            raise MaskedWorkflowWorkerError("WORKER_CANCELLED")
        deadline.remaining()
        if outcome.report is not None:
            try:
                core_client.report_masked(
                    rid,
                    attempt=live_attempt,
                    report=outcome.report.model_dump(by_alias=True, mode="json"),
                )
            except MaskedWorkflowWorkerError:
                return "FAILED"
            return "COMPLETED"
        # Measured failure (e.g. bad mask NoData): post the typed V3 failure.
        measured_failure = outcome.failure
        if measured_failure is None:
            return "FAILED"
        with contextlib.suppress(MaskedWorkflowWorkerError):
            core_client.fail_masked(
                rid,
                attempt=live_attempt,
                failure=measured_failure.model_dump(by_alias=True, mode="json"),
            )
        return "FAILED"
    except MaskedWorkflowWorkerError as exc:
        if exc.code in {"WORKER_CANCELLED", "STALE_LEASE", "AUTHORITY_LOST"}:
            if live_attempt is not None:
                with contextlib.suppress(MaskedWorkflowWorkerError):
                    core_client.fail_masked(
                        rid,
                        attempt=live_attempt,
                        failure=_failure_for_dispatch(
                            masked_identity_digest="sha256:" + "0" * 64,
                            report_id=report_id or "report-unknown",
                            reason="WORKER_CANCELLED"
                            if exc.code == "WORKER_CANCELLED"
                            else "STALE_LEASE",
                            failed_at=clock(),
                        ).model_dump(by_alias=True, mode="json"),
                    )
            return "FAILED"
        return "FAILED"
    except (MeasurementAlgorithmIncomplete, Exception):
        if live_attempt is not None:
            with contextlib.suppress(MaskedWorkflowWorkerError):
                core_client.fail_masked(
                    rid,
                    attempt=live_attempt,
                    failure=_failure_for_dispatch(
                        masked_identity_digest="sha256:" + "0" * 64,
                        report_id=report_id or "report-unknown",
                        reason="WORKER_EXECUTION_FAILED",
                        failed_at=clock(),
                    ).model_dump(by_alias=True, mode="json"),
                )
        return "FAILED"
    finally:
        if attempt_dir is not None:
            import contextlib as _contextlib

            with _contextlib.suppress(OSError):
                for child in sorted(attempt_dir.iterdir()):
                    with _contextlib.suppress(OSError):
                        if child.is_file() and not child.is_symlink():
                            child.unlink()
                attempt_dir.rmdir()


@dataclass(frozen=True, slots=True)
class MaskedWorkflowDrainOutcome:
    """One attempted job and what this single drain pass did with it."""

    job_id: str
    kind: Literal["inspection", "calculation"]
    result: Literal["SEALED", "COMPLETED", "FAILED", "SKIPPED"]


@dataclass(frozen=True, slots=True)
class MaskedWorkflowDrainSummary:
    """Bounded outcome of one drain pass over explicit Core-owned ids."""

    discovered: tuple[str, ...]
    outcomes: tuple[MaskedWorkflowDrainOutcome, ...]

    @property
    def sealed(self) -> tuple[str, ...]:
        return tuple(o.job_id for o in self.outcomes if o.result == "SEALED")

    @property
    def completed(self) -> tuple[str, ...]:
        return tuple(o.job_id for o in self.outcomes if o.result == "COMPLETED")

    @property
    def failed(self) -> tuple[str, ...]:
        return tuple(o.job_id for o in self.outcomes if o.result == "FAILED")

    @property
    def skipped(self) -> tuple[str, ...]:
        return tuple(o.job_id for o in self.outcomes if o.result == "SKIPPED")


def run_masked_workflow_drain(
    *,
    config: MaskedWorkflowWorkerConfig,
    worker_principal_id: str,
    limit: int = 50,
    core_client: MaskedWorkflowCoreClient | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    maximum_wall_seconds: float | None = None,
    check_current: Callable[[], None] | None = None,
    deadline_monotonic: float | None = None,
    now_fn: Callable[[], datetime] | None = None,
    owned_client: bool = False,
) -> MaskedWorkflowDrainSummary:
    """Discover pending masked jobs from Core and run each exactly once.

    No caller-supplied ids: the drain fetches the two Lead-owned bounded
    worker-visible pendings (``mask-inspection-jobs/pending`` then
    ``masked-calculations/pending``) under the designated worker bearer, so a
    withdrawn source, an expired activation, or a foreign scope never runs.
    Each discovered job is attempted at most once per drain call, inspections
    in page order then calculations in page order, truncated to ``limit`` (50
    max). A failed job posts its fenced failure/report, never retried here;
    re-driving requires a new drain call, never an internal loop. No V2
    analysis attempt is touched here. A 503 masked pending (owner hook not
    yet wired) runs inspections only rather than failing the drain.
    """
    if type(limit) is not int or isinstance(limit, bool) or limit < 1 or limit > 50:
        raise MaskedWorkflowWorkerError("INVALID_DISCOVERY_LIMIT")
    _resource_id(worker_principal_id, "WORKER_PRINCIPAL")
    cancel = is_cancelled or (lambda: False)
    clock = now_fn or _utc_now
    owns = core_client is None
    client = core_client or MaskedWorkflowCoreClient(
        base_url=config.core_base_url,
        bearer_token=config.core_bearer_token,
        maximum_response_bytes=config.maximum_response_bytes,
        request_timeout_seconds=config.request_timeout_seconds,
    )
    try:
        if cancel():
            return MaskedWorkflowDrainSummary(discovered=(), outcomes=())
        # Bounded Core discovery itself (designated worker bearer, fresh
        # Core-side witness per item). No out-of-band ids, no raw URLs.
        inspection_page = client.discover_inspection_pending(limit)
        try:
            masked_page = client.discover_masked_pending(limit)
        except MaskedWorkflowWorkerError as exc:
            if exc.code != "CORE_HTTP_503":
                raise
            masked_page = None
        inspection_specs: tuple[MaskedInspectionJobSpec, ...] = ()
        try:
            specs: list[MaskedInspectionJobSpec] = []
            for item in inspection_page.items:
                declaration = item.declaration
                specs.append(
                    MaskedInspectionJobSpec(
                        mask_child_id=item.mask_child_id,
                        site_id=item.site_id,
                        work_area_id=item.work_area_id,
                        mask_artifact_id=declaration.mask_artifact_id,
                        subject_digest=declaration.parent_subject.canonical_digest(),
                        parent_subject=declaration.parent_subject.model_dump(
                            by_alias=True, mode="json"
                        ),
                        baseline_subject=declaration.target_baseline_subject.model_dump(
                            by_alias=True, mode="json"
                        ),
                        baseline_dsm_artifact_id=declaration.target_baseline_dsm_artifact_id,
                        declared_sha256=declaration.declared_sha256,
                        declared_size_bytes=declaration.declared_size_bytes,
                        organization_id=declaration.organization_id,
                    )
                )
            inspection_specs = tuple(specs)
        except (AttributeError, TypeError, ValueError) as exc:
            raise MaskedWorkflowWorkerError("INVALID_CORE_RESPONSE") from exc
        calculation_request_ids: tuple[str, ...] = (
            tuple(item.request_id for item in masked_page.items) if masked_page is not None else ()
        )
        # Bound the combined drain to ``limit``: inspections first in page
        # order, then calculations fill the remainder.
        inspection_specs = inspection_specs[:limit]
        remaining = limit - len(inspection_specs)
        calculation_request_ids = calculation_request_ids[: max(0, remaining)]
        discovered: tuple[str, ...] = tuple(
            spec.mask_child_id for spec in inspection_specs
        ) + tuple(calculation_request_ids)
        now_monotonic = time.monotonic()
        wall = maximum_wall_seconds or float(config.envelope.max_deadline_seconds)
        shared_expires_at = now_monotonic + wall
        if deadline_monotonic is not None:
            shared_expires_at = min(shared_expires_at, deadline_monotonic)
        outcomes: list[MaskedWorkflowDrainOutcome] = []
        for spec in inspection_specs:
            if cancel():
                outcomes.extend(
                    MaskedWorkflowDrainOutcome(
                        job_id=rest.mask_child_id, kind="inspection", result="SKIPPED"
                    )
                    for rest in inspection_specs[inspection_specs.index(spec) :]
                )
                break
            result = run_mask_inspection_job(
                config=config,
                core_client=client,
                spec=spec,
                worker_instance_id=config.worker_instance_id,
                is_cancelled=is_cancelled,
                maximum_wall_seconds=maximum_wall_seconds,
                check_current=check_current,
                deadline_monotonic=shared_expires_at,
                now_fn=clock,
            )
            outcomes.append(
                MaskedWorkflowDrainOutcome(
                    job_id=spec.mask_child_id,
                    kind="inspection",
                    result=result,
                )
            )
        for rid in calculation_request_ids:
            if cancel():
                remaining_ids = calculation_request_ids[calculation_request_ids.index(rid) :]
                outcomes.extend(
                    MaskedWorkflowDrainOutcome(job_id=rest, kind="calculation", result="SKIPPED")
                    for rest in remaining_ids
                )
                break
            calculation_result = run_masked_calculation_job(
                config=config,
                core_client=client,
                request_id=rid,
                worker_principal_id=worker_principal_id,
                worker_instance_id=config.worker_instance_id,
                is_cancelled=is_cancelled,
                maximum_wall_seconds=maximum_wall_seconds,
                check_current=check_current,
                deadline_monotonic=shared_expires_at,
                now_fn=clock,
            )
            outcomes.append(
                MaskedWorkflowDrainOutcome(
                    job_id=rid,
                    kind="calculation",
                    result=calculation_result,
                )
            )
        return MaskedWorkflowDrainSummary(discovered=discovered, outcomes=tuple(outcomes))
    finally:
        if owns or owned_client:
            import contextlib as _contextlib

            with _contextlib.suppress(Exception):
                client.close()


__all__ = [
    "MaskedInspectionJobSpec",
    "MaskedWorkflowCoreClient",
    "MaskedWorkflowDrainOutcome",
    "MaskedWorkflowDrainSummary",
    "MaskedWorkflowWorkerConfig",
    "MaskedWorkflowWorkerError",
    "load_bearer_from_protected_file",
    "run_mask_inspection_job",
    "run_masked_calculation_job",
    "run_masked_workflow_drain",
]
