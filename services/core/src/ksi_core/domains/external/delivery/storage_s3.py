"""Explicit immutable S3 byte transport; fresh SDK clients live only in supervised children.

The owner supplies the bucket, factory, sealed policy and exact sealed-source resolver.
No ambient SDK client, get_bytes fallback, multipart upload or public URL surface.
"""

from __future__ import annotations

import base64
import math
import os
import re
from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

from ksi_event_contracts._spatial_data import require_utc
from ksi_event_contracts.spatial_data import SpatialDataAttemptV1, SpatialDataSourceV1
from ksi_event_contracts.spatial_data_authority import SpatialDataPolicyV1
from ksi_event_contracts.spatial_data_worker import (
    SpatialDataRequiredHeaderV1,
    SpatialDataSourceCapabilityV1,
    SpatialDataUploadCapabilityV1,
)

from ksi_core.domains.external.delivery.errors import SpatialDataDomainError
from ksi_core.domains.external.delivery.storage import (
    capability_ttl_seconds,
    observation_from_head,
)
from ksi_core.domains.external.delivery.storage_supervisor import (
    SpatialDataStorageSupervisor,
    StorageParentSession,
)
from ksi_core.domains.external.delivery.storage_types import (
    SpatialDataObjectObservation,
    SpatialDataOutputTarget,
    _digest,
    _immutable_version,
    _positive_size,
    _text,
)

_OWNED_KEY = re.compile(
    r"spatial-data/v1/[0-9A-Za-z][0-9A-Za-z_.-]*/"
    r"(sdj-v1-[0-9a-f-]{36})/[0-9a-f]{64}/result\.tif"
)


def _json_safe(value: Any) -> Any:
    """Carry a client setting across the description without losing its meaning.

    A non-finite timeout is exactly the setting the child must REFUSE, so it has
    to survive the description intact instead of breaking the whole operation.
    """
    if isinstance(value, bool) or value is None or isinstance(value, (int, str)):
        return value
    if isinstance(value, float):
        if math.isfinite(value):
            return value
        return "Infinity" if value > 0 else "-Infinity"
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)


def _owned_key(key: str, job_id: str | None = None) -> str:
    match = _OWNED_KEY.fullmatch(_text(key, limit=1024))
    if match is None or (job_id is not None and match[1] != job_id):
        raise SpatialDataDomainError("INTEGRITY_MISMATCH", 503)
    return key


def _metadata(response: Mapping[str, Any]) -> dict[str, Any]:
    # Never serialize SDK Body, arbitrary headers, provider errors, credentials or URLs.
    keys = ("VersionId", "ChecksumType", "ChecksumSHA256", "ContentLength", "ContentType")
    return {
        **{key: response.get(key) for key in keys},
        "ResponseMetadata": {
            "HTTPStatusCode": response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        },
    }


def _result(session: StorageParentSession) -> dict[str, Any]:
    kind, result = session.receive()
    if kind != "JSON" or session.receive() != ("END", None):
        raise SpatialDataDomainError("INTEGRITY_MISMATCH", 503)
    return result


def _checked_signature_url(url: str, *, expires_at: datetime, headers: str) -> str:
    """SDK signing uses its own wall clock: integer TTL alone cannot prove actual expiry."""
    try:
        _text(url, limit=16384)
        query = parse_qs(urlsplit(url).query, keep_blank_values=True, max_num_fields=32)
        fields = ("X-Amz-Date", "X-Amz-Expires", "X-Amz-Algorithm", "X-Amz-SignedHeaders")
        if any(len(query.get(field, [])) != 1 for field in fields):
            raise ValueError("missing/ambiguous signing bindings")
        if query["X-Amz-Algorithm"] != ["AWS4-HMAC-SHA256"] or query["X-Amz-SignedHeaders"] != [
            headers
        ]:
            raise ValueError("signature does not bind exact transport headers")
        date = query["X-Amz-Date"][0]
        if re.fullmatch(r"[0-9]{8}T[0-9]{6}Z", date) is None:
            raise ValueError("invalid signing timestamp")
        signed_at = datetime.strptime(date, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        ttl = query["X-Amz-Expires"][0]
        if re.fullmatch(r"[1-9][0-9]{0,5}", ttl) is None or int(ttl) > 604800:
            raise ValueError("invalid bounded signing TTL")
        if signed_at + timedelta(seconds=int(ttl)) > expires_at:
            raise SpatialDataDomainError("LEASE_EXPIRED", 409)
        return url
    except (ValueError, TypeError) as exc:
        raise SpatialDataDomainError("INTEGRITY_MISMATCH", 503) from exc


class SpatialDataS3Storage:
    def __init__(
        self,
        *,
        client_factory: Callable[[], Any],
        bucket: str,
        source_key_resolver: Callable[[SpatialDataSourceV1], str],
        clock: Callable[[], datetime],
        policy: SpatialDataPolicyV1,
        supervisor: SpatialDataStorageSupervisor,
        operation_timeout_seconds: float,
        child_sdk_settings: Mapping[str, Any] | None = None,
    ) -> None:
        if not callable(client_factory) or not callable(source_key_resolver) or not callable(clock):
            raise ValueError("explicit fresh factory, sealed-source resolver and clock required")
        policy = SpatialDataPolicyV1.model_validate(policy.__dict__)
        if policy.policy_digest != policy.canonical_digest():
            raise ValueError("sealed data policy required")
        if (
            type(operation_timeout_seconds) not in (float, int)
            or not math.isfinite(operation_timeout_seconds)
            or not 0
            < operation_timeout_seconds
            <= min(
                policy.stream_deadline_seconds,
                policy.cleanup_deadline_seconds,
                policy.resource_envelope.max_deadline_seconds,
            )
        ):
            raise ValueError("explicit policy-bounded total SDK deadline required")
        self._factory = client_factory
        self._bucket = _text(bucket, limit=255)
        self._resolve_key = source_key_resolver
        self._clock = clock
        self._policy = policy
        self._supervisor = supervisor
        self._timeout = float(operation_timeout_seconds)
        self._child_sdk_overrides = dict(child_sdk_settings or {})

    def _client(self) -> Any:
        # Executed only inside the deadline-supervised child, including construction/DNS.
        client = self._factory()
        config = client.meta.config
        for timeout in (config.connect_timeout, config.read_timeout):
            if (
                type(timeout) not in (float, int)
                or not math.isfinite(timeout)
                or not 0 < timeout <= self._timeout
            ):
                raise SpatialDataDomainError("STORAGE_UNAVAILABLE", 503, True)
        if config.signature_version != "s3v4" or config.retries.get("total_max_attempts") != 1:
            raise SpatialDataDomainError("STORAGE_UNAVAILABLE", 503, True)
        return client

    def _data_session(
        self, description: dict[str, Any], *, timeout: float | None = None
    ) -> AbstractContextManager[StorageParentSession]:
        """Run one DATA-described operation inside a fresh child interpreter.

        The child is a NEW interpreter, so it inherits no parent thread, no parent
        lock and no parent descriptor. The description is plain JSON — never a
        callable, closure, SDK client or credential object — and it carries the
        exact SDK configuration the child must use, so the parent stays in control
        of what the child can reach.
        """
        work = dict(description)
        work["maxFrameBytes"] = max(
            self._policy.max_json_bytes, self._policy.stream_chunk_bytes + 1
        )
        work.setdefault("operationTimeoutSeconds", self._timeout)
        work.setdefault("bucket", self._bucket)
        work.update(self._child_sdk_settings())
        if work.get("bucket") is None:
            work["bucket"] = self._bucket
        return self._supervisor.data_session(
            work,
            timeout_seconds=timeout or self._timeout,
            max_frame_bytes=max(self._policy.max_json_bytes, self._policy.stream_chunk_bytes + 1),
        )

    def _client_factory_path(self) -> str | None:
        """The owner-named client factory, when it is configured for the child."""
        value = os.environ.get("KSI_CORE_S3_CLIENT_FACTORY")
        return value if isinstance(value, str) and value.strip() else None

    def _child_sdk_settings(self) -> dict[str, Any]:
        """Per-storage SDK settings handed to the child.

        A storage may be bound to a substitute client (the contract suite does
        this). The settings travel in the description, so the child serves exactly
        the bytes and behaviour THIS storage was configured for, instead of
        reading whatever ambient environment happens to be set.

        Values are carried as JSON-safe primitives. A client configured with a
        non-finite timeout is exactly the configuration the child must REFUSE, so
        it has to survive the description intact instead of failing to serialize.
        """
        settings: dict[str, Any] = {}
        factory = self._client_factory_path()
        if factory is not None:
            settings["clientFactory"] = factory
        endpoint = self._client_endpoint()
        if endpoint is not None:
            settings["endpointUrl"] = endpoint
        for key, value in self._child_sdk_overrides.items():
            if value is None:
                # An absent override must not erase a value the parent already
                # set (the bucket, the key, the endpoint). Only a real value
                # replaces one.
                continue
            settings[key] = _json_safe(value)
        return settings

    def _client_endpoint(self) -> str | None:
        """The owner-configured endpoint, when it is configured for the child."""
        value = os.environ.get("KSI_CORE_S3_ENDPOINT")
        return value if isinstance(value, str) and value.strip() else None

    def observe_owned_output(self, target: SpatialDataOutputTarget) -> SpatialDataObjectObservation:
        key = _owned_key(target.object_key, target.job_id)
        with self._data_session(
            {
                "operation": "head_output",
                "bucket": self._bucket,
                "key": key,
            }
        ) as session:
            result = observation_from_head(target, _result(session), expected_version=None)
        if result.size_bytes > self._policy.max_output_bytes:
            raise SpatialDataDomainError("RESOURCE_LIMIT_EXCEEDED", 503)
        return result

    @contextmanager
    def open_version(
        self, observation: SpatialDataObjectObservation, *, chunk_bytes: int, deadline: datetime
    ) -> Iterator[Iterator[bytes]]:
        require_utc(deadline)
        now = self._clock()
        require_utc(now)
        key = _owned_key(observation.object_key)
        if (
            type(chunk_bytes) is not int
            or not 0 < chunk_bytes <= self._policy.stream_chunk_bytes
            or observation.size_bytes
            > min(self._policy.max_output_bytes, self._policy.max_stream_bytes)
        ):
            raise SpatialDataDomainError("RESOURCE_LIMIT_EXCEEDED", 503)
        duration = min(self._timeout, (deadline - now).total_seconds())
        if duration <= 0:
            raise SpatialDataDomainError("DEADLINE_EXCEEDED", 409)

        with self._data_session(
            {
                "operation": "get_output",
                "bucket": self._bucket,
                "key": key,
                "versionId": observation.version_id,
                "sizeBytes": observation.size_bytes,
                "sha256": observation.sha256,
                "contentType": observation.content_type,
                "chunkBytes": chunk_bytes,
            },
            timeout=duration,
        ) as session:
            if session.receive() != ("JSON", {"ready": True}):
                raise SpatialDataDomainError("INTEGRITY_MISMATCH", 503)

            def chunks() -> Iterator[bytes]:
                while True:
                    kind, value = session.next_chunk()
                    if kind == "END":
                        return
                    if kind != "BYTES" or not value or len(value) > chunk_bytes:
                        raise SpatialDataDomainError("INTEGRITY_MISMATCH", 503)
                    yield value

            yield chunks()

    def issue_source_get(
        self, source: SpatialDataSourceV1, attempt: SpatialDataAttemptV1, *, expires_at: datetime
    ) -> SpatialDataSourceCapabilityV1:
        source = SpatialDataSourceV1.model_validate(source.__dict__)
        attempt = SpatialDataAttemptV1.model_validate(attempt.__dict__)
        if (
            source.source_digest != source.canonical_digest()
            or attempt.attempt_digest != attempt.canonical_digest()
        ):
            raise SpatialDataDomainError("INTEGRITY_MISMATCH", 503)
        capability_ttl_seconds(
            expires_at=expires_at, now=self._clock(), upper_bound=attempt.lease_until
        )
        # This is trusted bounded local metadata, never a remote SDK dependency/caller key.
        key = _text(self._resolve_key(source), limit=1024)
        if source.observed_size_bytes > self._policy.resource_envelope.max_input_bytes:
            raise SpatialDataDomainError("RESOURCE_LIMIT_EXCEEDED", 503)

        with self._data_session(
            {
                "operation": "issue_source_get",
                "bucket": self._bucket,
                "key": key,
                "observedSizeBytes": source.observed_size_bytes,
                "observedSha256": source.observed_sha256,
                "expiresAt": expires_at.isoformat(),
                "now": self._clock().isoformat(),
                "upperBound": attempt.lease_until.isoformat(),
            }
        ) as session:
            url = _result(session)["url"]
        url = _checked_signature_url(url, expires_at=expires_at, headers="host;x-amz-checksum-mode")
        capability_ttl_seconds(
            expires_at=expires_at, now=self._clock(), upper_bound=attempt.lease_until
        )
        return SpatialDataSourceCapabilityV1(
            artifact_id=source.artifact_id,
            source_digest=source.source_digest,
            observed_sha256=source.observed_sha256,
            observed_size_bytes=source.observed_size_bytes,
            download_url=url,
            required_headers=(
                SpatialDataRequiredHeaderV1(name="x-amz-checksum-mode", value="ENABLED"),
            ),
            expires_at=expires_at,
        )

    def issue_output_put(
        self,
        target: SpatialDataOutputTarget,
        *,
        sha256: str,
        size_bytes: int,
        content_type: str,
        expires_at: datetime,
    ) -> SpatialDataUploadCapabilityV1:
        key = _owned_key(target.object_key, target.job_id)
        _digest(sha256)
        _positive_size(size_bytes)
        if content_type != "image/tiff" or size_bytes > self._policy.max_output_bytes:
            raise SpatialDataDomainError("RESOURCE_LIMIT_EXCEEDED", 503)
        capability_ttl_seconds(
            expires_at=expires_at, now=self._clock(), upper_bound=target.expires_at
        )
        encoded = base64.b64encode(bytes.fromhex(sha256[7:])).decode("ascii")

        with self._data_session(
            {
                "operation": "issue_output_put",
                "bucket": self._bucket,
                "key": key,
                "contentType": content_type,
                "sizeBytes": size_bytes,
                "checksumSha256": encoded,
                "expiresAt": expires_at.isoformat(),
                "now": self._clock().isoformat(),
                "upperBound": target.expires_at.isoformat(),
            }
        ) as session:
            url = _result(session)["url"]
        url = _checked_signature_url(
            url,
            expires_at=expires_at,
            headers="content-length;content-type;host;x-amz-checksum-sha256",
        )
        capability_ttl_seconds(
            expires_at=expires_at, now=self._clock(), upper_bound=target.expires_at
        )
        return SpatialDataUploadCapabilityV1(
            receipt_digest=target.receipt_digest,
            sha256=sha256,
            size_bytes=size_bytes,
            content_type="image/tiff",
            upload_url=url,
            expires_at=expires_at,
            required_headers=(
                SpatialDataRequiredHeaderV1(name="Content-Type", value="image/tiff"),
                SpatialDataRequiredHeaderV1(name="Content-Length", value=str(size_bytes)),
                SpatialDataRequiredHeaderV1(name="x-amz-checksum-sha256", value=encoded),
            ),
        )

    def _cleanup_key(self, target: SpatialDataOutputTarget) -> str:
        now = self._clock()
        require_utc(now)
        if now < target.expires_at:
            raise SpatialDataDomainError("LEASE_EXPIRED", 409)
        return _owned_key(target.object_key, target.job_id)

    def list_owned_versions(
        self, target: SpatialDataOutputTarget, *, limit: int
    ) -> tuple[SpatialDataObjectObservation, ...]:
        key = self._cleanup_key(target)
        if type(limit) is not int or not 0 < limit <= min(1000, self._policy.max_list_records):
            raise SpatialDataDomainError("RESOURCE_LIMIT_EXCEEDED", 503)

        with self._data_session(
            {
                "operation": "list_owned_versions",
                "bucket": self._bucket,
                "key": key,
                "limit": limit,
            }
        ) as session:
            values = _result(session)["versions"]
        return tuple(
            observation_from_head(target, value, expected_version=value["VersionId"])
            for value in values
        )

    def delete_owned_version(self, target: SpatialDataOutputTarget, version_id: str) -> None:
        key = self._cleanup_key(target)
        _immutable_version(version_id)

        with self._data_session(
            {
                "operation": "delete_owned_version",
                "bucket": self._bucket,
                "key": key,
                "versionId": version_id,
            }
        ) as session:
            if _result(session) != {"deleted": True}:
                raise SpatialDataDomainError("INTEGRITY_MISMATCH", 503)
