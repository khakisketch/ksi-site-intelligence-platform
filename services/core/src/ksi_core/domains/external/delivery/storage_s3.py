"""Explicit immutable S3 byte transport; fresh SDK clients live only in supervised children.

The owner supplies the bucket, factory, sealed policy and exact sealed-source resolver.
No ambient SDK client, get_bytes fallback, multipart upload or public URL surface.
"""

from __future__ import annotations

import base64
import hashlib
import math
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
    versioned_head_identity,
)
from ksi_core.domains.external.delivery.storage_supervisor import (
    SpatialDataStorageSupervisor,
    StorageChildChannel,
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

    def _session(
        self, work: Callable[[StorageChildChannel], None], *, timeout: float | None = None
    ) -> AbstractContextManager[StorageParentSession]:
        return self._supervisor.session(
            work,
            timeout_seconds=timeout or self._timeout,
            max_frame_bytes=max(self._policy.max_json_bytes, self._policy.stream_chunk_bytes + 1),
        )

    def observe_owned_output(self, target: SpatialDataOutputTarget) -> SpatialDataObjectObservation:
        key = _owned_key(target.object_key, target.job_id)

        def work(channel: StorageChildChannel) -> None:
            response = self._client().head_object(
                Bucket=self._bucket, Key=key, ChecksumMode="ENABLED"
            )
            channel.send_json(_metadata(response))

        with self._session(work) as session:
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

        def work(channel: StorageChildChannel) -> None:
            response = self._client().get_object(
                Bucket=self._bucket,
                Key=key,
                VersionId=observation.version_id,
                ChecksumMode="ENABLED",
            )
            body = response["Body"]
            try:
                version, size, checksum = versioned_head_identity(
                    response, expected_version=observation.version_id
                )
                if (version, size, checksum, response.get("ContentType")) != (
                    observation.version_id,
                    observation.size_bytes,
                    observation.sha256,
                    observation.content_type,
                ):
                    raise SpatialDataDomainError("INTEGRITY_MISMATCH", 503)
                channel.send_json({"ready": True})
                count, digest = 0, hashlib.sha256()
                while channel.command() == "NEXT":
                    chunk = body.read(chunk_bytes)
                    if type(chunk) is not bytes or len(chunk) > chunk_bytes:
                        raise SpatialDataDomainError("INTEGRITY_MISMATCH", 503)
                    if not chunk:
                        if count != size or "sha256:" + digest.hexdigest() != checksum:
                            raise SpatialDataDomainError("INTEGRITY_MISMATCH", 503)
                        break
                    count += len(chunk)
                    if count > size:
                        raise SpatialDataDomainError("INTEGRITY_MISMATCH", 503)
                    digest.update(chunk)
                    channel.send_bytes(chunk)
            finally:
                body.close()

        with self._session(work, timeout=duration) as session:
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

        def work(channel: StorageChildChannel) -> None:
            client = self._client()
            response = client.head_object(Bucket=self._bucket, Key=key, ChecksumMode="ENABLED")
            version, size, checksum = versioned_head_identity(response, expected_version=None)
            if (size, checksum) != (source.observed_size_bytes, source.observed_sha256):
                raise SpatialDataDomainError("INTEGRITY_MISMATCH", 503)
            ttl = capability_ttl_seconds(
                expires_at=expires_at, now=self._clock(), upper_bound=attempt.lease_until
            )
            url = client.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": self._bucket,
                    "Key": key,
                    "VersionId": version,
                    "ChecksumMode": "ENABLED",
                },
                ExpiresIn=ttl,
                HttpMethod="GET",
            )
            channel.send_json({"url": url})

        with self._session(work) as session:
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

        def work(channel: StorageChildChannel) -> None:
            client = self._client()
            ttl = capability_ttl_seconds(
                expires_at=expires_at, now=self._clock(), upper_bound=target.expires_at
            )
            url = client.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": self._bucket,
                    "Key": key,
                    "ContentType": content_type,
                    "ContentLength": size_bytes,
                    "ChecksumSHA256": encoded,
                },
                ExpiresIn=ttl,
                HttpMethod="PUT",
            )
            channel.send_json({"url": url})

        with self._session(work) as session:
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

        def work(channel: StorageChildChannel) -> None:
            client = self._client()
            response = client.list_object_versions(Bucket=self._bucket, Prefix=key, MaxKeys=limit)
            if response.get("ResponseMetadata", {}).get("HTTPStatusCode") != 200:
                raise SpatialDataDomainError("STORAGE_UNAVAILABLE", 503, True)
            # A partial page is never mistaken for a complete cleanup inventory.
            if response.get("IsTruncated") is not False:
                raise SpatialDataDomainError("RESOURCE_LIMIT_EXCEEDED", 503)
            versions = response.get("Versions", [])
            markers = response.get("DeleteMarkers", [])
            if (
                type(versions) is not list
                or type(markers) is not list
                or len(versions) + len(markers) > limit
            ):
                raise SpatialDataDomainError("INTEGRITY_MISMATCH", 503)
            observed = []
            for item in versions:
                if item["Key"] != key:
                    continue
                version = _immutable_version(item["VersionId"])
                result = client.head_object(
                    Bucket=self._bucket, Key=key, VersionId=version, ChecksumMode="ENABLED"
                )
                observation_from_head(target, result, expected_version=version)
                observed.append(_metadata(result))
            channel.send_json({"versions": observed})

        with self._session(work) as session:
            values = _result(session)["versions"]
        return tuple(
            observation_from_head(target, value, expected_version=value["VersionId"])
            for value in values
        )

    def delete_owned_version(self, target: SpatialDataOutputTarget, version_id: str) -> None:
        key = self._cleanup_key(target)
        _immutable_version(version_id)

        def work(channel: StorageChildChannel) -> None:
            result = self._client().delete_object(
                Bucket=self._bucket, Key=key, VersionId=version_id
            )
            if (
                result.get("VersionId") != version_id
                or result.get("ResponseMetadata", {}).get("HTTPStatusCode") != 204
            ):
                raise SpatialDataDomainError("INTEGRITY_MISMATCH", 503)
            channel.send_json({"deleted": True})

        with self._session(work) as session:
            if _result(session) != {"deleted": True}:
                raise SpatialDataDomainError("INTEGRITY_MISMATCH", 503)
