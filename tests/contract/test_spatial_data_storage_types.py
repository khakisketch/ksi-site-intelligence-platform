"""Private output state must never represent an unpinned or unchecked object."""

from collections.abc import Callable
from dataclasses import FrozenInstanceError, replace
from datetime import datetime
from typing import Any

import pytest
from ksi_core.domains.external.delivery.storage_types import (
    SpatialDataObjectObservation,
    SpatialDataOutputTarget,
)
from spatial_data_fixture import DIGEST, JOB_ID, NOW


def _observation(**changes: Any) -> SpatialDataObjectObservation:
    from ksi_core.domains.external.delivery.storage_types import SpatialDataObjectObservation

    return SpatialDataObjectObservation(
        **{
            "object_key": "spatial-data/v1/local/result.tif",
            "version_id": "immutable-version-1",
            "size_bytes": 64,
            "sha256": DIGEST,
            "content_type": "image/tiff",
            **changes,
        }
    )


def _target(**changes: Any) -> SpatialDataOutputTarget:
    from ksi_core.domains.external.delivery.storage_types import SpatialDataOutputTarget

    return SpatialDataOutputTarget(
        **{
            "object_key": "spatial-data/v1/local/result.tif",
            "job_id": JOB_ID,
            "attempt_digest": DIGEST,
            "receipt_digest": DIGEST,
            "expires_at": NOW,
            **changes,
        }
    )


@pytest.mark.parametrize(
    "version", [None, "", "null", "NULL", " null ", 1, True, "a\nb", "a\x00b", "x" * 1025]
)
def test_private_output_requires_explicit_immutable_version(version: object) -> None:
    """A mutable/null provider version must not become a downloadable output observation."""
    with pytest.raises(ValueError):
        _observation(version_id=version)


@pytest.mark.parametrize("size", [None, True, False, 0, -1, "64", 64.0, 2**63])
def test_private_output_size_is_strict_bounded_positive_integer(size: object) -> None:
    """Coercion or unrepresentable sizes must not bypass output length/resource checks."""
    with pytest.raises(ValueError):
        _observation(size_bytes=size)


@pytest.mark.parametrize(
    "digest", [None, "", "a" * 64, "sha256:" + "A" * 64, DIGEST + "\n", '"etag"']
)
def test_private_output_requires_full_prefixed_sha256(digest: object) -> None:
    """An ETag, bare digest or malformed checksum is not an observed full-object hash."""
    with pytest.raises(ValueError):
        _observation(sha256=digest)


@pytest.mark.parametrize(
    "content_type", [None, "", "application/octet-stream", "image/tiff; charset=utf-8"]
)
def test_private_output_content_type_is_exact(content_type: object) -> None:
    """Publication must not normalize a substituted media type into the GeoTIFF contract."""
    with pytest.raises(ValueError):
        _observation(content_type=content_type)


@pytest.mark.parametrize("factory", [_observation, _target])
@pytest.mark.parametrize("key", [None, "", True, "a\nb", "a\x00b", "x" * 1025])
def test_private_object_keys_are_bounded_and_control_free(
    factory: Callable[..., object], key: object
) -> None:
    """Private SDK keys must have a finite representation and no header/control injection."""
    with pytest.raises(ValueError):
        factory(object_key=key)


@pytest.mark.parametrize("field", ["attempt_digest", "receipt_digest"])
def test_output_target_requires_exact_attempt_and_receipt_binding(field: str) -> None:
    """Cleanup ownership must not be attributed to an unspecified fence or receipt."""
    with pytest.raises(ValueError):
        _target(**{field: "bad"})


@pytest.mark.parametrize("time", [None, "2026-10-01T00:00:00Z", datetime(2026, 10, 1)])
def test_output_target_requires_explicit_utc_expiry(time: object) -> None:
    """An ambiguous/missing capability expiry could permit premature orphan deletion."""
    with pytest.raises(ValueError):
        _target(expires_at=time)


def test_private_storage_state_is_immutable_but_detached_replacement_is_valid() -> None:
    """Changing accepted version or cleanup target in place would rewrite durable ownership."""
    observation = _observation()
    assert observation.version_id == "immutable-version-1" and observation.sha256 == DIGEST
    with pytest.raises(FrozenInstanceError):
        field = "version_id"
        setattr(observation, field, "substituted")
    newer = replace(observation, version_id="immutable-version-2")
    assert newer.version_id != observation.version_id
    assert _target().job_id == JOB_ID
