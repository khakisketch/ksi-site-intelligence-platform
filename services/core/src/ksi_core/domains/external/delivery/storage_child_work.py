"""Data-described storage operations executed inside a fresh child interpreter.

The supervisor's child used to be a ``fork()`` of the running ASGI server, which
inherited the parent's threads, locks and descriptors. The description below is the
replacement boundary: every operation is expressed as PLAIN DATA (an operation name
plus its exact parameters), so the child can be started as a new interpreter and
rebuild its own SDK client from the owner's ambient credential environment.

Nothing here widens authority. The parent still decides what the child may touch
(bucket, key, version, bounds); the child only performs the named read/write the
parent already authorised, and reports back exactly what it observed. The child
never sees a parent callable, closure, client, or credential object.
"""

from __future__ import annotations

import hashlib
import math
import os
from typing import Any

from ksi_core.domains.external.delivery.errors import SpatialDataDomainError
from ksi_core.domains.external.delivery.storage import (
    capability_ttl_seconds,
    versioned_head_identity,
)
from ksi_core.domains.external.delivery.storage_supervisor import StorageChildChannel
from ksi_core.domains.external.delivery.storage_types import _immutable_version

#: The S3 endpoint the owner configured. The child reads it from its own environment
#: exactly like the parent did, so no endpoint is smuggled through the description.
S3_ENDPOINT_ENV = "KSI_CORE_S3_ENDPOINT"
S3_BUCKET_ENV = "KSI_CORE_S3_BUCKET"
#: Optional environment key naming the SDK client factory as ``module:attribute``.
#: The owner sets it (the contract suite points it at a finite local substitute);
#: the child never inherits a client object across the boundary.
S3_CLIENT_FACTORY_ENV = "KSI_CORE_S3_CLIENT_FACTORY"

_MAX_CHUNK_BYTES = 65536


def _text(value: Any, limit: int) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise SpatialDataDomainError("INTEGRITY_MISMATCH", 503)
    return value


def _json_safe(value: Any) -> Any:
    """Carry a client setting across the description without losing its meaning.

    A non-finite timeout is precisely the setting the child must refuse, so it
    must survive the description exactly — as a string, not as a JSON-invalid
    float that would break the whole operation.
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


def _number_value(value: Any) -> float:
    """Read back a possibly non-finite number the child received."""
    if isinstance(value, str):
        if value == "Infinity":
            return math.inf
        if value == "-Infinity":
            return -math.inf
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    raise SpatialDataDomainError("STORAGE_UNAVAILABLE", 503, True)
    return value


def _number(value: Any, *, minimum: int = 1) -> int:
    if type(value) is not int or value < minimum:
        raise SpatialDataDomainError("INTEGRITY_MISMATCH", 503)
    return value


def _verified_client(client: Any, operation_timeout_seconds: float) -> Any:
    """The child proves its own client honours the bounded, single-attempt policy.

    The parent cannot inspect the child's client, so the CHILD must refuse a
    client whose timeouts, retry count or signature version would exceed the
    policy it was given. An unbounded or weakly signed client is refused before
    any remote call happens.
    """
    config = getattr(getattr(client, "meta", None), "config", None)
    if config is None:
        raise SpatialDataDomainError("STORAGE_UNAVAILABLE", 503, True)
    for timeout in (
        getattr(config, "connect_timeout", None),
        getattr(config, "read_timeout", None),
    ):
        if not isinstance(timeout, (float, int)) or isinstance(timeout, bool):
            raise SpatialDataDomainError("STORAGE_UNAVAILABLE", 503, True)
        if not math.isfinite(timeout) or not 0 < timeout <= operation_timeout_seconds:
            raise SpatialDataDomainError("STORAGE_UNAVAILABLE", 503, True)
    retries = getattr(config, "retries", None)
    if not isinstance(retries, dict) or retries.get("total_max_attempts") != 1:
        raise SpatialDataDomainError("STORAGE_UNAVAILABLE", 503, True)
    if getattr(config, "signature_version", None) != "s3v4":
        raise SpatialDataDomainError("STORAGE_UNAVAILABLE", 503, True)
    return client


def _client(operation_timeout_seconds: float, work: dict[str, Any]) -> Any:
    """A fresh, bounded SDK client built inside the child only.

    The owner may point the child at a different client factory (the contract
    suite uses a finite local substitute). The factory and endpoint travel in the
    description, so the parent stays in control of what the child can reach; the
    child never inherits a client object.
    """
    factory_path = work.get("clientFactory") or os.environ.get(S3_CLIENT_FACTORY_ENV)
    if isinstance(factory_path, str) and factory_path.strip():
        client = _client_from_factory(factory_path, operation_timeout_seconds, work)
        return _verified_client(client, operation_timeout_seconds)
    import boto3  # noqa: PLC0415 -- lazy import keeps boto3 optional for Core
    from botocore.config import Config  # noqa: PLC0415 -- same lazy boundary

    endpoint = work.get("endpointUrl") or os.environ.get(S3_ENDPOINT_ENV)
    if not isinstance(endpoint, str) or not endpoint:
        raise SpatialDataDomainError("STORAGE_UNAVAILABLE", 503, True)
    connect_timeout = min(5.0, operation_timeout_seconds)
    return _verified_client(
        boto3.client(
            "s3",
            endpoint_url=endpoint,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                connect_timeout=connect_timeout,
                read_timeout=operation_timeout_seconds,
                retries={"total_max_attempts": 1},
            ),
        ),
        operation_timeout_seconds,
    )


def _client_from_factory(
    factory_path: str, operation_timeout_seconds: float, work: dict[str, Any]
) -> Any:
    """Load the owner's client factory by dotted path and call it with the timeout.

    The factory receives the timeout and the exact operation description, so a
    substitute can serve the precise bytes/behaviour this operation needs without
    the parent sharing any state with the child.
    """
    import importlib  # noqa: PLC0415 -- child-local import

    module_name, _, attribute = factory_path.partition(":")
    if not module_name or not attribute:
        raise SpatialDataDomainError("STORAGE_UNAVAILABLE", 503, True)
    try:
        module = importlib.import_module(module_name)
        factory = getattr(module, attribute)
    except (ImportError, AttributeError) as exc:
        raise SpatialDataDomainError("STORAGE_UNAVAILABLE", 503, True) from exc
    if not callable(factory):
        raise SpatialDataDomainError("STORAGE_UNAVAILABLE", 503, True)
    try:
        return factory(operation_timeout_seconds, work)
    except TypeError as exc:
        # A factory that only wants the timeout is still a valid owner choice.
        if "work" not in str(exc) and "argument" not in str(exc):
            raise
        return factory(operation_timeout_seconds)


def _metadata(response: dict[str, Any]) -> dict[str, Any]:
    keys = ("VersionId", "ChecksumType", "ChecksumSHA256", "ContentLength", "ContentType")
    return {
        **{key: response.get(key) for key in keys},
        "ResponseMetadata": {
            "HTTPStatusCode": response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        },
    }


def _head_output(channel: StorageChildChannel, work: dict[str, Any]) -> None:
    client = _client(float(work["operationTimeoutSeconds"]), work)
    response = client.head_object(
        Bucket=_text(work["bucket"], 255),
        Key=_text(work["key"], 1024),
        ChecksumMode="ENABLED",
    )
    channel.send_json(_metadata(response))


def _get_output(channel: StorageChildChannel, work: dict[str, Any]) -> None:
    client = _client(float(work["operationTimeoutSeconds"]), work)
    chunk_bytes = _number(work["chunkBytes"], minimum=1)
    if chunk_bytes > _MAX_CHUNK_BYTES:
        raise SpatialDataDomainError("RESOURCE_LIMIT_EXCEEDED", 503)
    response = client.get_object(
        Bucket=_text(work["bucket"], 255),
        Key=_text(work["key"], 1024),
        VersionId=_text(work["versionId"], 1024),
        ChecksumMode="ENABLED",
    )
    body = response["Body"]
    try:
        version, size, checksum = versioned_head_identity(
            response, expected_version=_text(work["versionId"], 1024)
        )
        expected = (
            work["versionId"],
            _number(work["sizeBytes"]),
            _text(work["sha256"], 128),
            work.get("contentType"),
        )
        if (version, size, checksum, response.get("ContentType")) != expected:
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


def _issue_source_get(channel: StorageChildChannel, work: dict[str, Any]) -> None:
    client = _client(float(work["operationTimeoutSeconds"]), work)
    response = client.head_object(
        Bucket=_text(work["bucket"], 255),
        Key=_text(work["key"], 1024),
        ChecksumMode="ENABLED",
    )
    version, size, checksum = versioned_head_identity(response, expected_version=None)
    if (size, checksum) != (
        _number(work["observedSizeBytes"]),
        _text(work["observedSha256"], 128),
    ):
        raise SpatialDataDomainError("INTEGRITY_MISMATCH", 503)
    ttl = capability_ttl_seconds(
        expires_at=_utc(work["expiresAt"]),
        now=_utc(work["now"]),
        upper_bound=_utc(work["upperBound"]),
    )
    url = client.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": _text(work["bucket"], 255),
            "Key": _text(work["key"], 1024),
            "VersionId": version,
            "ChecksumMode": "ENABLED",
        },
        ExpiresIn=ttl,
        HttpMethod="GET",
    )
    channel.send_json({"url": url})


def _issue_output_put(channel: StorageChildChannel, work: dict[str, Any]) -> None:
    client = _client(float(work["operationTimeoutSeconds"]), work)
    ttl = capability_ttl_seconds(
        expires_at=_utc(work["expiresAt"]),
        now=_utc(work["now"]),
        upper_bound=_utc(work["upperBound"]),
    )
    url = client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": _text(work["bucket"], 255),
            "Key": _text(work["key"], 1024),
            "ContentType": _text(work["contentType"], 128),
            "ContentLength": _number(work["sizeBytes"]),
            "ChecksumSHA256": _text(work["checksumSha256"], 128),
        },
        ExpiresIn=ttl,
        HttpMethod="PUT",
    )
    channel.send_json({"url": url})


def _list_owned_versions(channel: StorageChildChannel, work: dict[str, Any]) -> None:
    client = _client(float(work["operationTimeoutSeconds"]), work)
    limit = _number(work["limit"], minimum=1)
    key = _text(work["key"], 1024)
    response = client.list_object_versions(
        Bucket=_text(work["bucket"], 255), Prefix=key, MaxKeys=limit
    )
    if response.get("ResponseMetadata", {}).get("HTTPStatusCode") != 200:
        raise SpatialDataDomainError("STORAGE_UNAVAILABLE", 503, True)
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
            Bucket=_text(work["bucket"], 255), Key=key, VersionId=version, ChecksumMode="ENABLED"
        )
        # The child's own observation must be a full, exact object identity —
        # a null or substituted version is refused, never passed on as a
        # cleanup candidate.
        observed.append(_metadata(result))
    channel.send_json({"versions": observed})


def _delete_owned_version(channel: StorageChildChannel, work: dict[str, Any]) -> None:
    client = _client(float(work["operationTimeoutSeconds"]), work)
    version_id = _text(work["versionId"], 1024)
    result = client.delete_object(
        Bucket=_text(work["bucket"], 255),
        Key=_text(work["key"], 1024),
        VersionId=version_id,
    )
    if result.get("VersionId") != version_id or result.get("ResponseMetadata", {}).get(
        "HTTPStatusCode"
    ) != 204:
        raise SpatialDataDomainError("INTEGRITY_MISMATCH", 503)
    channel.send_json({"deleted": True})


def _utc(value: Any) -> Any:
    from datetime import UTC, datetime  # noqa: PLC0415 -- child-local import

    if not isinstance(value, str):
        raise SpatialDataDomainError("INTEGRITY_MISMATCH", 503)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise SpatialDataDomainError("INTEGRITY_MISMATCH", 503)
    return parsed.astimezone(UTC)


_OPERATIONS = {
    "head_output": _head_output,
    "get_output": _get_output,
    "issue_source_get": _issue_source_get,
    "issue_output_put": _issue_output_put,
    "list_owned_versions": _list_owned_versions,
    "delete_owned_version": _delete_owned_version,
}


def execute(channel: StorageChildChannel, work: dict[str, Any]) -> None:
    """Run the named operation described by ``work``."""
    operation = work.get("operation")
    handler = _OPERATIONS.get(operation) if isinstance(operation, str) else None
    if handler is None:
        raise SpatialDataDomainError("INTEGRITY_MISMATCH", 503)
    handler(channel, work)


__all__ = ["execute", "S3_BUCKET_ENV", "S3_ENDPOINT_ENV"]
