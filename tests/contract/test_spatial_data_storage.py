"""Immutable full-object SDK metadata checks, not provider or total supervision evidence."""

import base64
import hashlib
import json
import os
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from typing import Any

import pytest
from ksi_core.domains.external.delivery.errors import SpatialDataDomainError
from ksi_core.domains.external.delivery.storage_types import SpatialDataOutputTarget
from spatial_data_fixture import DIGEST, JOB_ID, NOW, make_attempt, make_policy, make_source


def target() -> SpatialDataOutputTarget:
    return SpatialDataOutputTarget(
        f"spatial-data/v1/org-local/{JOB_ID}/{DIGEST[7:]}/result.tif",
        JOB_ID,
        DIGEST,
        DIGEST,
        NOW + timedelta(seconds=1),
    )


def test_dotted_organization_owned_storage_operation_matrix(tmp_path: Path) -> None:
    """A Core-permitted dotted org survives signing, versioned reads and exact cleanup."""
    owned = replace(target(), object_key=target().object_key.replace("org-local", "org.example"))
    storage, supervisor = sdk_storage(tmp_path)
    try:
        storage.issue_output_put(
            owned, sha256=DIGEST, size_bytes=64, content_type="image/tiff",
            expires_at=owned.expires_at,
        )
        observed = storage.observe_owned_output(owned)
        with storage.open_version(observed, chunk_bytes=3, deadline=owned.expires_at) as chunks:
            assert b"".join(chunks) == b"abcdefgh"
        expired = replace(owned, expires_at=NOW)
        versions = storage.list_owned_versions(expired, limit=2)
        assert len(versions) == 1 and versions[0].version_id == "version-1"
        storage.delete_owned_version(expired, "version-1")
        events = sdk_events(tmp_path)
        assert all(
            event.get("Key", event.get("Prefix", owned.object_key)) == owned.object_key
            for event in events
        )
        assert (
            next(event for event in events if event["operation"] == "delete")["VersionId"]
            == "version-1"
        )
    finally:
        assert supervisor.wait_for_idle(timeout_seconds=1)
    assert supervisor.wait_for_idle(timeout_seconds=1)


@pytest.mark.parametrize("organization", [".hidden", "..", "org/other", "org%2Fother", "org space"])
def test_owned_key_rejects_invalid_organization_segments(organization: str) -> None:
    """Supporting dots is not permission to access arbitrary prefixes or decoded paths."""
    from ksi_core.domains.external.delivery.storage_s3 import _owned_key

    with pytest.raises(SpatialDataDomainError) as error:
        _owned_key(target().object_key.replace("org-local", organization), JOB_ID)
    assert error.value.reason == "INTEGRITY_MISMATCH"


def head(**changes: Any) -> dict[str, Any]:
    return {
        "VersionId": "version-1",
        "ChecksumType": "FULL_OBJECT",
        "ChecksumSHA256": base64.b64encode(bytes.fromhex(DIGEST[7:])).decode(),
        "ContentLength": 64,
        "ContentType": "image/tiff",
        "ResponseMetadata": {"HTTPStatusCode": 200},
        **changes,
    }


def test_observed_full_object_requires_exact_immutable_metadata_and_version() -> None:
    """An ETag/latest alias or unchecked length must not create a downloadable observation."""
    from ksi_core.domains.external.delivery.storage import observation_from_head

    observed = observation_from_head(target(), head(), expected_version="version-1")
    assert observed.object_key == target().object_key
    assert (observed.version_id, observed.size_bytes, observed.sha256, observed.content_type) == (
        "version-1",
        64,
        DIGEST,
        "image/tiff",
    )


@pytest.mark.parametrize(
    "change",
    [
        {"VersionId": "version-2"},
        {"VersionId": "null"},
        {"VersionId": None},
        {"VersionId": ""},
        {"VersionId": True},
        {"VersionId": "version\n1"},
        {"ChecksumType": "COMPOSITE"},
        {"ChecksumType": None},
        {"ChecksumSHA256": None},
        {"ChecksumSHA256": "etag"},
        {"ChecksumSHA256": base64.b64encode(b"short").decode()},
        {"ChecksumSHA256": base64.b64encode(b"f" * 32).decode() + "\n"},
        {"ContentLength": True},
        {"ContentLength": 0},
        {"ContentLength": -1},
        {"ContentLength": "64"},
        {"ContentLength": 64.0},
        {"ContentLength": 2**63},
        {"ContentType": "application/octet-stream"},
        {"ContentType": None},
        {"ResponseMetadata": {"HTTPStatusCode": 302}},
        {"ResponseMetadata": {}},
    ],
)
def test_substituted_or_unsupported_head_metadata_refuses_observation(change: dict) -> None:
    """Incomplete/composite checksums, mutable versions and coercion cannot authorize bytes."""
    from ksi_core.domains.external.delivery.storage import observation_from_head

    with pytest.raises(SpatialDataDomainError) as error:
        observation_from_head(target(), head(**change), expected_version="version-1")
    assert error.value.reason == "INTEGRITY_MISMATCH"


def test_missing_checksum_cannot_be_replaced_with_etag() -> None:
    """An SDK ETag does not establish a full-object SHA-256 even for a single upload."""
    from ksi_core.domains.external.delivery.storage import observation_from_head

    metadata = head()
    metadata.pop("ChecksumSHA256")
    metadata["ETag"] = '"' + "f" * 64 + '"'
    with pytest.raises(SpatialDataDomainError):
        observation_from_head(target(), metadata, expected_version=None)


def test_latest_owned_head_still_requires_explicit_returned_version() -> None:
    """First observation can discover a version, but must never manufacture an unpinned result."""
    from ksi_core.domains.external.delivery.storage import observation_from_head

    assert observation_from_head(target(), head(), expected_version=None).version_id == "version-1"


@pytest.mark.parametrize("seconds,expected", [(1.0, 1), (1.9, 1), (5.0, 5)])
def test_signed_expiry_never_rounds_up_beyond_requested_permission(
    seconds: float, expected: int
) -> None:
    """SDK integer TTL rounding must not extend a source/upload write permission."""
    from ksi_core.domains.external.delivery.storage import capability_ttl_seconds

    assert (
        capability_ttl_seconds(
            expires_at=NOW + timedelta(seconds=seconds),
            now=NOW,
            upper_bound=NOW + timedelta(seconds=5),
        )
        == expected
    )


@pytest.mark.parametrize("seconds", [-1, 0, 0.9, 5.1])
def test_expired_unrepresentable_or_unbounded_capability_ttl_is_refused(seconds: float) -> None:
    """Zero/subsecond or beyond-lease TTL must fail instead of granting a minimum longer write."""
    from ksi_core.domains.external.delivery.storage import capability_ttl_seconds

    with pytest.raises(SpatialDataDomainError):
        capability_ttl_seconds(
            expires_at=NOW + timedelta(seconds=seconds),
            now=NOW,
            upper_bound=NOW + timedelta(seconds=5),
        )


class SDKStub:
    """Finite SDK-level remote substitute; actual child/process/framing stays real."""

    def __init__(
        self,
        log: Path,
        *,
        body: bytes = b"abcdefgh",
        response_changes: dict[str, Any] | None = None,
        behavior: str | None = None,
    ) -> None:
        self.log = log
        self.bytes = body
        self.changes = response_changes or {}
        self.behavior = behavior
        self.meta = SimpleNamespace(
            config=SimpleNamespace(
                connect_timeout=0.05,
                read_timeout=0.05,
                retries={"total_max_attempts": 1},
                signature_version="s3v4",
            )
        )

    def record(self, name: str, **arguments: Any) -> None:
        with self.log.open("a") as output:
            output.write(json.dumps({"pid": os.getpid(), "operation": name, **arguments}) + "\n")

    def metadata(self) -> dict[str, Any]:
        return {
            **head(
                ContentLength=len(self.bytes),
                ChecksumSHA256=base64.b64encode(hashlib.sha256(self.bytes).digest()).decode(),
            ),
            **self.changes,
        }

    def head_object(self, **arguments: Any) -> dict[str, Any]:
        self.record("head", **arguments)
        if self.behavior == "head-hang":
            Event().wait(10)
        return self.metadata()

    def get_object(self, **arguments: Any) -> dict[str, Any]:
        self.record("get", **arguments)
        if self.behavior == "get-hang":
            Event().wait(10)
        owner = self

        class Body:
            cursor = 0

            def read(self, size: int) -> bytes:
                owner.record("read", size=size)
                if owner.behavior == "read-hang":
                    Event().wait(10)
                value = owner.bytes[self.cursor : self.cursor + size]
                self.cursor += len(value)
                return value

            def close(self) -> None:
                owner.record("close")

        return {**self.metadata(), "Body": Body()}

    def generate_presigned_url(self, operation: str, **arguments: Any) -> str:
        self.record("sign", client_method=operation, **arguments)
        signed_at = "20261001T000001Z" if self.behavior == "sign-late" else "20261001T000000Z"
        headers = (
            "content-length;content-type;host;x-amz-checksum-sha256"
            if operation == "put_object"
            else "host;x-amz-checksum-mode"
        )
        return (
            "https://store.invalid/exact-version?X-Amz-Algorithm=AWS4-HMAC-SHA256"
            f"&X-Amz-Date={signed_at}&X-Amz-Expires={arguments['ExpiresIn']}"
            f"&X-Amz-SignedHeaders={headers}&X-Amz-Signature=local-fixture"
        )

    def list_object_versions(self, **arguments: Any) -> dict[str, Any]:
        self.record("list", **arguments)
        return {
            "Versions": [{"Key": arguments["Prefix"], "VersionId": "version-1"}],
            "IsTruncated": False,
            "ResponseMetadata": {"HTTPStatusCode": 200},
        }

    def delete_object(self, **arguments: Any) -> dict[str, Any]:
        self.record("delete", **arguments)
        return {"VersionId": arguments["VersionId"], "ResponseMetadata": {"HTTPStatusCode": 204}}


def sdk_storage(
    path: Path,
    *,
    behavior: str | None = None,
    response_changes: dict[str, Any] | None = None,
    body: bytes = b"abcdefgh",
    listing_changes: dict[str, Any] | None = None,
    deletion_changes: dict[str, Any] | None = None,
    config_changes: dict[str, Any] | None = None,
) -> Any:
    from ksi_core.domains.external.delivery.storage_s3 import SpatialDataS3Storage
    from ksi_core.domains.external.delivery.storage_supervisor import SpatialDataStorageSupervisor

    supervisor = SpatialDataStorageSupervisor(max_concurrency=2)

    def factory() -> SDKStub:
        client = SDKStub(
            path / "sdk.jsonl", body=body, response_changes=response_changes, behavior=behavior
        )
        operations: dict[str, Any] = {}
        if listing_changes is not None:
            original_list = client.list_object_versions
            operations["list_object_versions"] = lambda **kwargs: {
                **original_list(**kwargs),
                **listing_changes,
            }
        if deletion_changes is not None:
            original_delete = client.delete_object
            operations["delete_object"] = lambda **kwargs: {
                **original_delete(**kwargs),
                **deletion_changes,
            }
        for name, operation in operations.items():
            setattr(client, name, operation)
        for name, value in (config_changes or {}).items():
            setattr(client.meta.config, name, value)
        return client

    storage = SpatialDataS3Storage(
        client_factory=factory,
        bucket="local-store",
        source_key_resolver=lambda source: "external-reconstruction/v1/exact-source",
        clock=lambda: NOW,
        policy=make_policy(),
        supervisor=supervisor,
        operation_timeout_seconds=0.2,
    )
    return storage, supervisor


def sdk_events(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (path / "sdk.jsonl").read_text().splitlines()]


def test_s3_head_observes_full_hash_version_without_body_reads(tmp_path: Path) -> None:
    """HEAD observation cannot download/buffer bytes or publish a checksum-less latest alias."""
    storage, supervisor = sdk_storage(tmp_path)
    observed = storage.observe_owned_output(target())
    assert (
        observed.version_id == "version-1"
        and observed.sha256 == "sha256:" + hashlib.sha256(b"abcdefgh").hexdigest()
    )
    assert supervisor.wait_for_idle(timeout_seconds=1)
    events = sdk_events(tmp_path)
    assert [event["operation"] for event in events] == ["head"]
    assert events[0]["Bucket"] == "local-store" and events[0]["ChecksumMode"] == "ENABLED"
    assert events[0]["Key"] == target().object_key and events[0]["pid"] != os.getpid()


def test_s3_get_pins_request_and_response_version_and_bounds_reads(tmp_path: Path) -> None:
    """A versioned observation must not silently read latest bytes or request an unbounded body."""
    storage, supervisor = sdk_storage(tmp_path)
    observed = storage.observe_owned_output(target())
    with storage.open_version(
        observed, chunk_bytes=3, deadline=NOW + timedelta(seconds=1)
    ) as chunks:
        assert list(chunks) == [b"abc", b"def", b"gh"]
    assert supervisor.wait_for_idle(timeout_seconds=1)
    events = sdk_events(tmp_path)
    get = next(event for event in events if event["operation"] == "get")
    assert get["VersionId"] == "version-1" and get["ChecksumMode"] == "ENABLED"
    assert all(event["size"] == 3 for event in events if event["operation"] == "read")
    assert events[-1]["operation"] == "close"


@pytest.mark.parametrize(
    "change",
    [
        {"VersionId": "version-2"},
        {"ChecksumType": "COMPOSITE"},
        {"ChecksumSHA256": base64.b64encode(b"f" * 32).decode()},
        {"ContentLength": 9},
    ],
)
def test_s3_get_substitution_fails_and_closes_body(tmp_path: Path, change: dict) -> None:
    """Substituted GET metadata cannot authorize even the first byte; cleanup still closes Body."""
    storage, supervisor = sdk_storage(tmp_path)
    observed = storage.observe_owned_output(target())
    mutated, child_supervisor = sdk_storage(tmp_path, response_changes=change)
    with (
        pytest.raises(SpatialDataDomainError),
        mutated.open_version(
            observed, chunk_bytes=3, deadline=NOW + timedelta(seconds=1)
        ) as chunks,
    ):
        list(chunks)
    assert child_supervisor.wait_for_idle(timeout_seconds=1)
    assert sdk_events(tmp_path)[-1]["operation"] == "close"


def test_s3_stream_checks_full_hash_not_only_metadata(tmp_path: Path) -> None:
    """Same length/header hash with substituted data must fail before a spool is publishable."""
    storage, supervisor = sdk_storage(tmp_path)
    observed = storage.observe_owned_output(target())
    mutated, owner = sdk_storage(
        tmp_path,
        body=b"wrongbyt",
        response_changes={
            "ChecksumSHA256": base64.b64encode(hashlib.sha256(b"abcdefgh").digest()).decode()
        },
    )
    with (
        pytest.raises(SpatialDataDomainError) as error,
        mutated.open_version(
            observed, chunk_bytes=3, deadline=NOW + timedelta(seconds=1)
        ) as chunks,
    ):
        list(chunks)
    assert error.value.reason == "INTEGRITY_MISMATCH"
    assert owner.wait_for_idle(timeout_seconds=1)


def test_s3_output_signature_binds_length_type_checksum_and_exact_owned_target(
    tmp_path: Path,
) -> None:
    """A PUT must bind exact bytes/key and cannot extend reserved expiry."""
    storage, supervisor = sdk_storage(tmp_path)
    capability = storage.issue_output_put(
        target(),
        sha256=DIGEST,
        size_bytes=64,
        content_type="image/tiff",
        expires_at=target().expires_at,
    )
    assert capability.receipt_digest == DIGEST
    assert capability.header_mapping() == {
        "Content-Type": "image/tiff",
        "Content-Length": "64",
        "x-amz-checksum-sha256": base64.b64encode(bytes.fromhex(DIGEST[7:])).decode(),
    }
    assert supervisor.wait_for_idle(timeout_seconds=1)
    signed = sdk_events(tmp_path)[0]
    assert signed["client_method"] == "put_object" and signed["ExpiresIn"] == 1
    assert signed["Params"] == {
        "Bucket": "local-store",
        "Key": target().object_key,
        "ContentType": "image/tiff",
        "ContentLength": 64,
        "ChecksumSHA256": base64.b64encode(bytes.fromhex(DIGEST[7:])).decode(),
    }


def test_s3_source_get_is_observed_pinned_and_not_limited_to_output_media_type(
    tmp_path: Path,
) -> None:
    """Octet-stream source declarations still need exact hash/size/version."""
    source = make_source()
    storage, supervisor = sdk_storage(
        tmp_path,
        body=b"f" * source.observed_size_bytes,
        response_changes={
            "ContentType": "application/octet-stream",
            "ChecksumSHA256": base64.b64encode(bytes.fromhex(source.observed_sha256[7:])).decode(),
        },
    )
    attempt = make_attempt()
    capability = storage.issue_source_get(source, attempt, expires_at=NOW + timedelta(seconds=1))
    assert (
        capability.observed_sha256 == source.observed_sha256
        and capability.source_digest == source.source_digest
    )
    assert supervisor.wait_for_idle(timeout_seconds=1)
    signed = next(event for event in sdk_events(tmp_path) if event["operation"] == "sign")
    assert signed["Params"] == {
        "Bucket": "local-store",
        "Key": "external-reconstruction/v1/exact-source",
        "VersionId": "version-1",
        "ChecksumMode": "ENABLED",
    }


def test_s3_cleanup_lists_and_deletes_only_exact_owned_versions(tmp_path: Path) -> None:
    """Cleanup cannot enumerate a bucket broadly or issue an unversioned delete marker."""
    storage, supervisor = sdk_storage(tmp_path)
    from dataclasses import replace

    expired = replace(target(), expires_at=NOW)
    versions = storage.list_owned_versions(expired, limit=2)
    assert len(versions) == 1 and versions[0].version_id == "version-1"
    assert supervisor.wait_for_idle(timeout_seconds=1)
    storage.delete_owned_version(expired, "version-1")
    assert supervisor.wait_for_idle(timeout_seconds=1)
    events = sdk_events(tmp_path)
    listing = next(event for event in events if event["operation"] == "list")
    deletion = next(event for event in events if event["operation"] == "delete")
    assert listing["Prefix"] == target().object_key and listing["MaxKeys"] == 2
    assert deletion["Key"] == target().object_key and deletion["VersionId"] == "version-1"


@pytest.mark.parametrize("behavior", ["head-hang", "get-hang", "read-hang"])
def test_s3_blocking_sdk_call_returns_within_outer_total_deadline(
    tmp_path: Path, behavior: str
) -> None:
    """Connect/read SDK timeouts alone do not bound launch, DNS, factory or stalled Body.read."""
    import time

    storage, supervisor = sdk_storage(tmp_path)
    observed = storage.observe_owned_output(target())
    stalled, owner = sdk_storage(tmp_path, behavior=behavior)
    started = time.monotonic()
    with pytest.raises(SpatialDataDomainError):
        if behavior == "head-hang":
            stalled.observe_owned_output(target())
        else:
            with stalled.open_version(
                observed, chunk_bytes=3, deadline=NOW + timedelta(seconds=1)
            ) as chunks:
                list(chunks)
    assert time.monotonic() - started < 0.7
    assert owner.wait_for_idle(timeout_seconds=1)


def test_real_botocore_model_signs_exact_put_headers_without_remote_io(tmp_path: Path) -> None:
    """A permissive SDK double cannot prove real PUT signing accepts and binds our parameters."""
    from urllib.parse import parse_qs, urlsplit

    boto3 = pytest.importorskip("boto3")
    from dataclasses import replace
    from datetime import UTC, datetime

    from botocore.config import Config
    from ksi_core.domains.external.delivery.storage_s3 import SpatialDataS3Storage
    from ksi_core.domains.external.delivery.storage_supervisor import SpatialDataStorageSupervisor

    def factory() -> Any:
        return boto3.client(
            "s3",
            endpoint_url="https://store.invalid",
            region_name="us-east-1",
            aws_access_key_id="local-test-only",
            aws_secret_access_key="local-test-only",
            config=Config(
                connect_timeout=0.1,
                read_timeout=0.1,
                signature_version="s3v4",
                retries={"total_max_attempts": 1},
            ),
        )

    supervisor = SpatialDataStorageSupervisor(max_concurrency=1)
    storage = SpatialDataS3Storage(
        client_factory=factory,
        bucket="local-store",
        clock=lambda: datetime.now(UTC),
        source_key_resolver=lambda _: "unused",
        policy=make_policy(),
        supervisor=supervisor,
        operation_timeout_seconds=1,
    )
    current_target = replace(target(), expires_at=datetime.now(UTC) + timedelta(seconds=2))
    capability = storage.issue_output_put(
        current_target,
        sha256=DIGEST,
        size_bytes=64,
        content_type="image/tiff",
        expires_at=current_target.expires_at,
    )
    query = parse_qs(urlsplit(capability.upload_url).query)
    assert query["X-Amz-SignedHeaders"] == [
        "content-length;content-type;host;x-amz-checksum-sha256"
    ]
    assert query["X-Amz-Expires"] == ["1"]
    assert supervisor.wait_for_idle(timeout_seconds=1)


def test_late_signing_cannot_extend_actual_storage_authority_past_owned_expiry(
    tmp_path: Path,
) -> None:
    """A stalled SDK signer cannot outlive the advertised expiry/cleanup boundary."""
    storage, supervisor = sdk_storage(tmp_path, behavior="sign-late")
    with pytest.raises(SpatialDataDomainError) as error:
        storage.issue_output_put(
            target(),
            sha256=DIGEST,
            size_bytes=64,
            content_type="image/tiff",
            expires_at=target().expires_at,
        )
    assert error.value.reason == "LEASE_EXPIRED"
    assert supervisor.wait_for_idle(timeout_seconds=1)


@pytest.mark.parametrize(
    "config",
    [
        {"connect_timeout": 0},
        {"read_timeout": float("inf")},
        {"connect_timeout": 60},
        {"retries": {"total_max_attempts": 2}},
        {"signature_version": "s3"},
    ],
)
def test_sdk_unbounded_timeouts_retries_or_weak_signature_are_refused(
    tmp_path: Path, config: dict
) -> None:
    """An assembly-supplied client must not bypass explicit timeout/single-attempt/SigV4 policy."""
    storage, supervisor = sdk_storage(tmp_path, config_changes=config)
    with pytest.raises(SpatialDataDomainError) as error:
        storage.observe_owned_output(target())
    assert error.value.reason == "STORAGE_UNAVAILABLE"
    assert supervisor.wait_for_idle(timeout_seconds=1)
    assert not (tmp_path / "sdk.jsonl").exists()


@pytest.mark.parametrize(
    "changes",
    [
        {"IsTruncated": True},
        {"IsTruncated": None},
        {"Versions": [{"Key": target().object_key, "VersionId": "null"}]},
        {"ResponseMetadata": {"HTTPStatusCode": 302}},
    ],
)
def test_cleanup_does_not_mistake_partial_invalid_inventory_for_complete(
    tmp_path: Path, changes: dict
) -> None:
    """Ignoring pagination or null versions would silently abandon bytes or delete latest."""
    from dataclasses import replace

    storage, supervisor = sdk_storage(tmp_path, listing_changes=changes)
    with pytest.raises(SpatialDataDomainError):
        storage.list_owned_versions(replace(target(), expires_at=NOW), limit=2)
    assert supervisor.wait_for_idle(timeout_seconds=1)
    assert all(item["operation"] != "delete" for item in sdk_events(tmp_path))


def test_cleanup_ignores_neighbor_with_same_prefix_and_never_deletes_live_target(
    tmp_path: Path,
) -> None:
    """Exact-prefix provider listings may include other keys; owned cleanup cannot adopt them."""
    from dataclasses import replace

    storage, supervisor = sdk_storage(
        tmp_path,
        listing_changes={
            "Versions": [{"Key": target().object_key + "-neighbor", "VersionId": "version-2"}]
        },
    )
    assert storage.list_owned_versions(replace(target(), expires_at=NOW), limit=2) == ()
    with pytest.raises(SpatialDataDomainError):
        storage.delete_owned_version(target(), "version-1")
    assert supervisor.wait_for_idle(timeout_seconds=1)
    assert [item["operation"] for item in sdk_events(tmp_path)] == ["list"]


def test_cleanup_delete_refuses_provider_version_substitution(tmp_path: Path) -> None:
    """A successful response for another version cannot discharge the owned deletion obligation."""
    from dataclasses import replace

    storage, supervisor = sdk_storage(tmp_path, deletion_changes={"VersionId": "version-2"})
    with pytest.raises(SpatialDataDomainError) as error:
        storage.delete_owned_version(replace(target(), expires_at=NOW), "version-1")
    assert error.value.reason == "INTEGRITY_MISMATCH"
    assert supervisor.wait_for_idle(timeout_seconds=1)


@pytest.mark.parametrize("body", [b"abc", b"abcdefgh-more"])
def test_get_refuses_early_eof_and_trailing_bytes(tmp_path: Path, body: bytes) -> None:
    """Matching declared headers must not hide truncation or additional bytes past exact size."""
    storage, _ = sdk_storage(tmp_path)
    observed = storage.observe_owned_output(target())
    mutated, supervisor = sdk_storage(
        tmp_path,
        body=body,
        response_changes={
            "ContentLength": 8,
            "ChecksumSHA256": base64.b64encode(hashlib.sha256(b"abcdefgh").digest()).decode(),
        },
    )
    with (
        pytest.raises(SpatialDataDomainError) as error,
        mutated.open_version(
            observed, chunk_bytes=3, deadline=NOW + timedelta(seconds=1)
        ) as chunks,
    ):
        list(chunks)
    assert error.value.reason == "INTEGRITY_MISMATCH"
    assert supervisor.wait_for_idle(timeout_seconds=1)
