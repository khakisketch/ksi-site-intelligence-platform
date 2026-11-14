"""Replay-only historical processing-profile facts (Task 2 retirement).

Core no longer owns an executable processing recipe: the ODM recipe factory
(``ksi_odm_civil_v1``), its built-in image/digest, and the issuing registry are
gone. What remains for the historical ledger is this opaque binding table —
``(historical profile ID, historical digest) -> required artifact kinds`` —
used exclusively by manifest-aware ``SUCCEEDED`` replay to re-apply the exact
gate the live ``_assert_profile_required_artifacts`` once enforced.

Deliberately absent: image, engine version, processing params, preprocessing
policy, license basis, profile snapshots, factories, and any issuance
interface. A lookup miss (unknown profile ID or tampered digest) is
fail-closed — replay must refuse the journal, never fall back to a default.

Provenance: the single sealed binding below was recomputed from the retired
``ksi_odm_civil_v1().sealed()`` snapshot at removal time
(``profile_digest == canonical_digest()`` held) and pinned here as an opaque
fact. ``("point_cloud", "dsm", "dtm")`` is its recorded required set.
"""

from __future__ import annotations

HISTORICAL_KSI_ODM_CIVIL_V1_ID = "ksi-odm-civil-v1"
HISTORICAL_KSI_ODM_CIVIL_V1_DIGEST = (
    "sha256:d19e3ce42e9cfd34cc504c651a8cc78d781a94f36040a58d525a5cfbd7586dc1"
)
HISTORICAL_KSI_ODM_CIVIL_V1_REQUIRED_ARTIFACTS = (
    "point_cloud",
    "dsm",
    "dtm",
)

_FACTS: dict[tuple[str, str], tuple[str, ...]] = {
    (
        HISTORICAL_KSI_ODM_CIVIL_V1_ID,
        HISTORICAL_KSI_ODM_CIVIL_V1_DIGEST,
    ): HISTORICAL_KSI_ODM_CIVIL_V1_REQUIRED_ARTIFACTS,
}


class UnknownHistoricalProcessingProfileError(LookupError):
    """No recorded historical profile matches the (id, digest) binding."""


def historical_required_artifacts(
    profile_id: str, profile_digest: str
) -> tuple[str, ...]:
    """Return the required artifact kinds for one sealed historical binding.

    Raises :class:`UnknownHistoricalProcessingProfileError` for unknown IDs
    and tampered digests alike — the caller must fail the replay closed.
    """
    try:
        return _FACTS[(profile_id, profile_digest)]
    except KeyError as exc:
        raise UnknownHistoricalProcessingProfileError(
            f"기록되지 않은 historical processing profile binding: {profile_id!r}"
        ) from exc


__all__ = [
    "HISTORICAL_KSI_ODM_CIVIL_V1_DIGEST",
    "HISTORICAL_KSI_ODM_CIVIL_V1_ID",
    "HISTORICAL_KSI_ODM_CIVIL_V1_REQUIRED_ARTIFACTS",
    "UnknownHistoricalProcessingProfileError",
    "historical_required_artifacts",
]
