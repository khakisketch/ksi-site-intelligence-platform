"""Neutral Site spatial types and external observation identity (Task 3).

Pre-extraction wire/schema literals below were captured from the legacy owners
before any move (see ``task3-logs/pre-extraction-baseline.txt``) and are frozen
here so a post-extraction accept/reject difference fails loudly:

- ``SiteFrame`` wire/JSON/schema from ``ksi_mission_contracts.models``.
- ``AreaOfInterest`` triangle wire/area from ``ksi_mission_planning.geometry``.
- ``observation_epoch_id`` vectors from ``ksi_core.acquisition.analysis_readiness``,
  with fixed literals cross-checked against coreutils ``sha256sum``.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import ValidationError

if TYPE_CHECKING:
    from ksi_event_contracts.observation_work_order import ObservationWorkOrder
    from ksi_geo_core.aoi import AreaOfInterest as NeutralAreaOfInterest
    from ksi_mission_planning.geometry import AreaOfInterest as LegacyAreaOfInterest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOTS = (
    REPOSITORY_ROOT / "services/core/src",
    REPOSITORY_ROOT / "packages/event-contracts/src",
    REPOSITORY_ROOT / "packages/geo-core/src",
    REPOSITORY_ROOT / "packages/domain/src",
    REPOSITORY_ROOT / "packages/mission-contracts/src",
    REPOSITORY_ROOT / "packages/mission-planning/src",
)

# Captured pre-extraction from ksi_mission_contracts.models.SiteFrame.
SITEFRAME_WIRE = {
    "crs": "EPSG:5186",
    "transformVersion": "v1.0",
    "unit": "meter",
    "verticalDatum": "KNGEO2000",
}
SITEFRAME_JSON = (
    '{"crs":"EPSG:5186","verticalDatum":"KNGEO2000","unit":"meter","transformVersion":"v1.0"}'
)
SITEFRAME_SCHEMA: dict[str, Any] = {
    "additionalProperties": False,
    "description": ("INV-020 — 모든 세계좌표는 CRS·수직기준·unit·transformVersion을 갖는다."),
    "properties": {
        "crs": {"title": "Crs", "type": "string"},
        "transformVersion": {"title": "Transformversion", "type": "string"},
        "unit": {"const": "meter", "title": "Unit", "type": "string"},
        "verticalDatum": {"title": "Verticaldatum", "type": "string"},
    },
    "required": ["crs", "verticalDatum", "unit", "transformVersion"],
    "title": "SiteFrame",
    "type": "object",
}
SITEFRAME_SAMPLE: dict[str, Any] = {
    "crs": "EPSG:5186",
    "vertical_datum": "KNGEO2000",
    "unit": "meter",
    "transform_version": "v1.0",
}

# Captured pre-extraction from ksi_mission_planning.geometry (37.5,127.0 triangle).
AOI_TRIANGLE_WIRE: dict[str, Any] = {
    "vertices": [
        {"latDeg": 37.5, "lonDeg": 127.0},
        {"latDeg": 37.5009, "lonDeg": 127.0},
        {"latDeg": 37.5, "lonDeg": 127.0012},
    ]
}
AOI_TRIANGLE_AREA_M2 = 5308.857787490328

# Captured pre-extraction from ksi_mission_planning.geometry. Independent of
# any same-object alias: post-extraction outputs must equal these literals.
GEOPOINT_SCHEMA = {
    "additionalProperties": False,
    "description": ("WGS84 좌표 한 점. 순서 혼동(lat/lon ↔ lon/lat)을 필드명으로 차단한다."),
    "properties": {
        "latDeg": {"maximum": 90.0, "minimum": -90.0, "title": "Latdeg", "type": "number"},
        "lonDeg": {
            "maximum": 180.0,
            "minimum": -180.0,
            "title": "Londeg",
            "type": "number",
        },
    },
    "required": ["latDeg", "lonDeg"],
    "title": "GeoPoint",
    "type": "object",
}
AOI_FULL_SCHEMA = {
    "$defs": {"GeoPoint": GEOPOINT_SCHEMA},
    "additionalProperties": False,
    "description": ("닫힌 단순 폴리곤 구역 — 마지막 꼭짓점→첫 꼭짓점 변이 암묵적으로 닫는다."),
    "properties": {
        "vertices": {
            "items": {"$ref": "#/$defs/GeoPoint"},
            "maxItems": 256,
            "minItems": 3,
            "title": "Vertices",
            "type": "array",
        }
    },
    "required": ["vertices"],
    "title": "AreaOfInterest",
    "type": "object",
}

# Fixed epoch literals, independently hand-calculated:
#   printf 'org\x00work-order\x00cycle' | sha256sum  (first 24 hex, obs-epoch- prefix)
# cross-checked against hashlib.sha256 in task3-logs/pre-extraction-baseline.txt.
EPOCH_ORG = "org-neutral-epoch"
EPOCH_WORK_ORDER = "wo-neutral-0001"
EPOCH_CYCLE_1 = "obs-epoch-e712c566b654689709de73fe"
EPOCH_CYCLE_2 = "obs-epoch-5fc26ce6484ec139fb17a2cc"
EPOCH_OTHER_TENANT_CYCLE_1 = "obs-epoch-bf64b4f13b2c1c3d4ed669b4"


def _run_python(script: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    existing = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(root) for root in SOURCE_ROOTS] + ([existing] if existing else [])
    )
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        check=False,
        env=environment,
        text=True,
        timeout=60,
    )


def _assert_subprocess_ok(script: str) -> None:
    completed = _run_python(script)
    assert completed.returncode == 0, completed.stdout + completed.stderr


def _valid_triangle() -> NeutralAreaOfInterest:
    from ksi_geo_core.aoi import AreaOfInterest, GeoPoint

    return AreaOfInterest(
        vertices=[
            GeoPoint(lat_deg=37.5, lon_deg=127.0),
            GeoPoint(lat_deg=37.5009, lon_deg=127.0),
            GeoPoint(lat_deg=37.5, lon_deg=127.0012),
        ]
    )


def _legacy_triangle() -> LegacyAreaOfInterest:
    from ksi_mission_planning.geometry import AreaOfInterest, GeoPoint

    return AreaOfInterest(
        vertices=[
            GeoPoint(lat_deg=37.5, lon_deg=127.0),
            GeoPoint(lat_deg=37.5009, lon_deg=127.0),
            GeoPoint(lat_deg=37.5, lon_deg=127.0012),
        ]
    )


def _vectors() -> dict[str, list[dict[str, float]]]:
    ok = [
        {"lat_deg": 37.5, "lon_deg": 127.0},
        {"lat_deg": 37.5009, "lon_deg": 127.0},
        {"lat_deg": 37.5, "lon_deg": 127.0012},
    ]
    return {
        "bowtie": [
            {"lat_deg": 37.5, "lon_deg": 127.0},
            {"lat_deg": 37.5009, "lon_deg": 127.0012},
            {"lat_deg": 37.5, "lon_deg": 127.0012},
            {"lat_deg": 37.5009, "lon_deg": 127.0},
        ],
        "collinear": [
            {"lat_deg": 37.5, "lon_deg": 127.0},
            {"lat_deg": 37.5005, "lon_deg": 127.0},
            {"lat_deg": 37.501, "lon_deg": 127.0},
        ],
        "duplicate": [ok[0], ok[1], ok[2], dict(ok[0])],
        "polar": [
            {"lat_deg": 80.5, "lon_deg": 0.0},
            {"lat_deg": 80.6, "lon_deg": 0.001},
            {"lat_deg": 80.5, "lon_deg": 0.002},
        ],
        "far": [
            {"lat_deg": 37.5, "lon_deg": 127.0},
            {"lat_deg": 37.5009, "lon_deg": 127.0},
            {"lat_deg": 38.5, "lon_deg": 127.0},
        ],
        "dateline": [
            {"lat_deg": 37.5, "lon_deg": 179.999},
            {"lat_deg": 37.5009, "lon_deg": 179.999},
            {"lat_deg": 37.5, "lon_deg": -179.999},
        ],
    }


# ── SiteFrame parity ──────────────────────────────────────────────────────


def test_neutral_siteframe_matches_captured_wire_schema_and_json() -> None:
    from ksi_event_contracts.site_frame import SiteFrame

    frame = SiteFrame(**SITEFRAME_SAMPLE)
    assert frame.model_dump(by_alias=True, mode="json") == SITEFRAME_WIRE
    assert frame.model_dump_json(by_alias=True) == SITEFRAME_JSON
    assert SiteFrame.model_json_schema() == SITEFRAME_SCHEMA
    assert SiteFrame.model_validate(dict(SITEFRAME_SAMPLE)) == frame
    assert SiteFrame.model_validate(SITEFRAME_WIRE) == frame


def test_legacy_siteframe_is_the_neutral_class() -> None:
    from ksi_event_contracts.site_frame import SiteFrame as NeutralSiteFrame
    from ksi_mission_contracts.models import SiteFrame as LegacySiteFrame

    assert LegacySiteFrame is NeutralSiteFrame
    assert LegacySiteFrame(**SITEFRAME_SAMPLE).model_dump(by_alias=True) == SITEFRAME_WIRE


def test_siteframe_validation_semantics_are_preserved() -> None:
    from ksi_event_contracts.site_frame import SiteFrame

    # Current semantics: the shared contract model enforces types/aliases/extras
    # only; non-blank INV-020 gating lives in the Site store boundary, so a
    # blank crs still parses here exactly as before extraction.
    assert SiteFrame.model_validate({**SITEFRAME_WIRE, "crs": " "}).crs == " "
    with pytest.raises(ValidationError):
        SiteFrame.model_validate({**SITEFRAME_WIRE, "unit": "kilometer"})
    with pytest.raises(ValidationError):
        SiteFrame.model_validate({**SITEFRAME_WIRE, "unexpected": "x"})
    with pytest.raises(ValidationError):
        SiteFrame.model_validate({"crs": "EPSG:5186"})
    config = SiteFrame.model_config
    assert config.get("extra") == "forbid"
    assert config.get("populate_by_name") is True
    assert "alias_generator" in config


def test_neutral_siteframe_config_is_exact_legacy_config() -> None:
    """The neutral owner keeps the full legacy Pydantic config, key for key.

    Captured pre-extraction from ``ksi_mission_contracts.models.SiteFrame``;
    the event-contracts shared base adds ``allow_inf_nan=False``, which the
    legacy model never had, so the neutral module carries its own base.
    """

    from ksi_event_contracts.site_frame import SiteFrame
    from pydantic.alias_generators import to_camel

    config = dict(SiteFrame.model_config)
    assert set(config) == {
        "alias_generator",
        "extra",
        "populate_by_name",
        "validate_by_alias",
        "validate_by_name",
    }
    assert config["alias_generator"] is to_camel
    assert config["extra"] == "forbid"
    assert config["populate_by_name"] is True
    assert config["validate_by_alias"] is True
    assert config["validate_by_name"] is True
    assert "allow_inf_nan" not in config


# ── AOI parity ────────────────────────────────────────────────────────────


def test_neutral_aoi_matches_captured_wire_and_area() -> None:
    triangle = _valid_triangle()
    assert triangle.model_dump(by_alias=True, mode="json") == AOI_TRIANGLE_WIRE
    assert triangle.area_m2() == AOI_TRIANGLE_AREA_M2
    assert _legacy_triangle().model_dump(by_alias=True, mode="json") == AOI_TRIANGLE_WIRE
    assert _legacy_triangle().area_m2() == AOI_TRIANGLE_AREA_M2


def test_neutral_aoi_and_geopoint_schemas_match_captured_baseline() -> None:
    from ksi_geo_core.aoi import AreaOfInterest, GeoPoint
    from ksi_mission_planning.geometry import (
        AreaOfInterest as LegacyAOI,
    )
    from ksi_mission_planning.geometry import (
        GeoPoint as LegacyPoint,
    )

    assert GeoPoint.model_json_schema() == GEOPOINT_SCHEMA
    assert AreaOfInterest.model_json_schema() == AOI_FULL_SCHEMA
    assert LegacyPoint.model_json_schema() == GEOPOINT_SCHEMA
    assert LegacyAOI.model_json_schema() == AOI_FULL_SCHEMA
    assert json.loads(json.dumps(AOI_FULL_SCHEMA)) == AOI_FULL_SCHEMA


def test_legacy_geometry_module_is_the_neutral_module_object() -> None:
    import sys

    import ksi_geo_core.aoi as neutral
    import ksi_mission_planning.geometry as legacy

    assert legacy is neutral
    assert sys.modules["ksi_mission_planning.geometry"] is neutral
    assert sys.modules["ksi_geo_core.aoi"] is neutral
    assert legacy.AreaOfInterest is neutral.AreaOfInterest
    assert legacy.GeoPoint is neutral.GeoPoint
    assert legacy._segments_intersect is neutral._segments_intersect
    assert legacy._MAX_VERTICES == neutral._MAX_VERTICES == 256
    assert legacy._MAX_EXTENT_M == neutral._MAX_EXTENT_M == 10_000.0
    assert legacy._MAX_ABS_LATITUDE_DEG == neutral._MAX_ABS_LATITUDE_DEG == 80.0
    assert legacy._EPSILON_M == neutral._EPSILON_M == 1e-6
    assert legacy._EPSILON_M2 == neutral._EPSILON_M2 == 1e-6


def test_geometry_module_alias_shares_state_both_import_orders() -> None:
    _assert_subprocess_ok(
        dedent(
            """
            import importlib

            canonical = importlib.import_module("ksi_geo_core.aoi")
            legacy = importlib.import_module("ksi_mission_planning.geometry")
            assert legacy is canonical

            marker = object()
            legacy._TASK3_ALIAS_PROBE = marker
            assert canonical._TASK3_ALIAS_PROBE is marker
            del canonical._TASK3_ALIAS_PROBE
            assert not hasattr(legacy, "_TASK3_ALIAS_PROBE")
            """
        )
    )
    _assert_subprocess_ok(
        dedent(
            """
            import importlib

            legacy = importlib.import_module("ksi_mission_planning.geometry")
            canonical = importlib.import_module("ksi_geo_core.aoi")
            assert legacy is canonical
            assert legacy.AreaOfInterest is canonical.AreaOfInterest
            """
        )
    )


@pytest.mark.parametrize("name", sorted(_vectors()))
def test_invalid_geometry_vectors_stay_rejected(name: str) -> None:
    from ksi_geo_core.aoi import AreaOfInterest, GeoPoint

    vertices = [GeoPoint(**point) for point in _vectors()[name]]
    with pytest.raises(ValidationError):
        AreaOfInterest(vertices=vertices)


def test_invalid_geometry_vectors_match_legacy_rejections() -> None:
    from ksi_geo_core.aoi import AreaOfInterest as NeutralAOI
    from ksi_geo_core.aoi import GeoPoint as NeutralPoint
    from ksi_mission_planning.geometry import AreaOfInterest as LegacyAOI
    from ksi_mission_planning.geometry import GeoPoint as LegacyPoint

    for points in _vectors().values():
        with pytest.raises(ValidationError):
            NeutralAOI(vertices=[NeutralPoint(**point) for point in points])
        with pytest.raises(ValidationError):
            LegacyAOI(vertices=[LegacyPoint(**point) for point in points])


def test_vertex_count_and_finite_bounds_are_preserved() -> None:
    from ksi_geo_core.aoi import AreaOfInterest, GeoPoint

    base = {"lat_deg": 37.5, "lon_deg": 127.0}
    with pytest.raises(ValidationError):
        AreaOfInterest(vertices=[GeoPoint(**base), GeoPoint(**{**base, "lon_deg": 127.001})])
    ring = [
        GeoPoint(lat_deg=37.5 + (i % 16) * 0.0001, lon_deg=127.0 + (i // 16) * 0.0001)
        for i in range(257)
    ]
    with pytest.raises(ValidationError):
        AreaOfInterest(vertices=ring)
    with pytest.raises(ValidationError):
        GeoPoint(lat_deg=float("inf"), lon_deg=127.0)
    with pytest.raises(ValidationError):
        GeoPoint(lat_deg=37.5, lon_deg=float("nan"))
    with pytest.raises(ValidationError):
        GeoPoint(lat_deg=91.0, lon_deg=127.0)
    with pytest.raises(ValidationError):
        GeoPoint(lat_deg=37.5, lon_deg=127.0, extra_field=1.0)  # type: ignore[call-arg]


# ── Epoch identity ────────────────────────────────────────────────────────


def _work_order(
    *, organization_id: str, work_order_id: str, cycle_number: int
) -> ObservationWorkOrder:
    from ksi_event_contracts.observation_work_order import ObservationWorkOrder

    return ObservationWorkOrder.model_validate(
        {
            "schemaVersion": "1.0",
            "workOrderId": work_order_id,
            "organizationId": organization_id,
            "siteId": "site-neutral-1",
            "purpose": "PROGRESS_QUANTITY",
            "name": "중립 원시 검증",
            "workAreaIds": ["wa-neutral-1"],
            "cycleNumber": cycle_number,
            "status": "APPROVED",
            "version": 1,
            "createdAt": "2026-10-07T00:00:00Z",
            "updatedAt": "2026-10-07T00:00:00Z",
            "createdBy": "operator-neutral",
            "approvedAt": "2026-10-07T00:00:00Z",
            "approvedBy": "operator-neutral",
        }
    )


def test_epoch_matches_independently_calculated_fixed_literals() -> None:
    from ksi_core.domains.observations.epoch_identity import observation_epoch_id

    first = observation_epoch_id(
        _work_order(organization_id=EPOCH_ORG, work_order_id=EPOCH_WORK_ORDER, cycle_number=1)
    )
    assert first == EPOCH_CYCLE_1
    assert (
        observation_epoch_id(
            _work_order(organization_id=EPOCH_ORG, work_order_id=EPOCH_WORK_ORDER, cycle_number=2)
        )
        == EPOCH_CYCLE_2
    )
    assert (
        observation_epoch_id(
            _work_order(
                organization_id="org-other-tenant",
                work_order_id=EPOCH_WORK_ORDER,
                cycle_number=1,
            )
        )
        == EPOCH_OTHER_TENANT_CYCLE_1
    )
    # Deterministic and tenant/cycle sensitive.
    assert (
        observation_epoch_id(
            _work_order(organization_id=EPOCH_ORG, work_order_id=EPOCH_WORK_ORDER, cycle_number=1)
        )
        == EPOCH_CYCLE_1
    )
    assert len({EPOCH_CYCLE_1, EPOCH_CYCLE_2, EPOCH_OTHER_TENANT_CYCLE_1}) == 3


def test_epoch_recipe_bytes_are_unchanged() -> None:
    raw = "\0".join([EPOCH_ORG, EPOCH_WORK_ORDER, "1"]).encode()
    assert f"obs-epoch-{hashlib.sha256(raw).hexdigest()[:24]}" == EPOCH_CYCLE_1


def test_legacy_readiness_reexports_the_neutral_epoch_function() -> None:
    from ksi_core.acquisition.analysis_readiness import (
        observation_epoch_id as legacy_epoch_id,
    )
    from ksi_core.domains.observations.epoch_identity import (
        observation_epoch_id as neutral_epoch_id,
    )

    assert legacy_epoch_id is neutral_epoch_id
    assert (
        legacy_epoch_id(
            _work_order(organization_id=EPOCH_ORG, work_order_id=EPOCH_WORK_ORDER, cycle_number=1)
        )
        == EPOCH_CYCLE_1
    )


def test_external_reconstruction_replay_keeps_fixed_epoch() -> None:
    from ksi_core.domains.external.ingress.external_reconstruction import (
        ExternalReconstructionStore,
        ExternalReconstructionVerdict,
    )
    from ksi_core.foundation.durable_journal import DurableJournal
    from ksi_event_contracts.external_reconstruction import (
        ExternalReconstructionSubmissionV1,
    )

    work_order = _work_order(
        organization_id=EPOCH_ORG, work_order_id=EPOCH_WORK_ORDER, cycle_number=1
    )
    wire = {
        "submissionId": "external-neutral-1",
        "revision": 1,
        "organizationId": EPOCH_ORG,
        "siteId": "site-neutral-1",
        "observationEpochId": EPOCH_CYCLE_1,
        "submittedAt": "2026-10-07T00:00:00Z",
        "submittedBy": "operator-neutral",
        "executionResponsibility": "customer_operator",
        "executionLocus": "customer_workstation",
        "producerDeclaration": {
            "softwareName": "Customer Mapper",
            "softwareVersion": "1.0",
            "buildIdentifier": None,
            "producerRunIdentifier": None,
            "configurationDigest": None,
            "completedAt": None,
        },
        "inputDeclaration": {
            "rawMediaStoredByKsi": False,
            "originalRetentionLocus": "customer_workstation",
            "localInputManifestDigest": None,
            "imageCount": None,
            "captureStartedAt": None,
            "captureEndedAt": None,
        },
        "artifacts": [
            {
                "artifactId": "ortho",
                "kind": "ortho",
                "fileName": "ortho.tif",
                "format": "GeoTIFF",
                "contentType": "application/octet-stream",
                "declaredSha256": hashlib.sha256(b"ortho bytes").hexdigest(),
                "declaredSizeBytes": len(b"ortho bytes"),
                "declaredCrs": None,
                "declaredVerticalReference": None,
                "declaredGsdM": None,
            }
        ],
    }
    wire["submissionDigest"] = ExternalReconstructionSubmissionV1.digest_for_wire(wire)
    submission = ExternalReconstructionSubmissionV1.model_validate(wire)

    with tempfile.TemporaryDirectory() as directory:
        journal_path = Path(directory) / "external-reconstruction.jsonl"
        journal = DurableJournal(journal_path)
        store = ExternalReconstructionStore(journal)
        result = store.register(
            submission,
            work_order=work_order,
            registered_by="operator-neutral",
            now=datetime(2026, 10, 7, tzinfo=UTC),
        )
        assert result.verdict is ExternalReconstructionVerdict.REGISTERED
        assert result.revision is not None
        assert result.revision.observation_epoch_id == EPOCH_CYCLE_1
        journal.close()

        replayed = ExternalReconstructionStore(DurableJournal(journal_path))
        record = replayed.get(
            EPOCH_WORK_ORDER,
            "external-neutral-1",
            1,
            organization_id=EPOCH_ORG,
            site_id="site-neutral-1",
        )
        assert record is not None
        assert record.observation_epoch_id == EPOCH_CYCLE_1
        assert record.submission.submission_digest == submission.submission_digest


# ── Fresh-process isolation ───────────────────────────────────────────────


def _blocker_prelude(denied: tuple[str, ...]) -> str:
    return dedent(
        """
        import importlib.abc
        import sys

        _DENIED_PREFIXES = %r

        class _DenyPrefixes(importlib.abc.MetaPathFinder):
            def find_spec(self, name, path=None, target=None):
                if name in _DENIED_PREFIXES or any(
                    name.startswith(prefix + ".") for prefix in _DENIED_PREFIXES
                ):
                    raise ImportError(f"task3 isolation probe denies {name}")
                return None

        sys.meta_path.insert(0, _DenyPrefixes())
        for _module in list(sys.modules):
            assert _module not in _DENIED_PREFIXES and not any(
                _module.startswith(prefix + ".") for prefix in _DENIED_PREFIXES
            ), _module
        """
    ) % (denied,)


_BLOCKER_PREAMBLE = _blocker_prelude(("ksi_core.acquisition",))
_NEUTRAL_DENIED = ("ksi_core.acquisition", "ksi_mission_contracts", "ksi_mission_planning")


def test_neutral_site_types_import_without_acquisition_or_mission() -> None:
    _assert_subprocess_ok(
        _blocker_prelude(_NEUTRAL_DENIED)
        + dedent(
            """
            import sys

            from ksi_event_contracts.site_frame import SiteFrame
            from ksi_geo_core.aoi import AreaOfInterest, GeoPoint
            from ksi_core.domains.observations.epoch_identity import observation_epoch_id

            frame = SiteFrame(
                crs="EPSG:5186",
                vertical_datum="KNGEO2000",
                unit="meter",
                transform_version="v1.0",
            )
            assert frame.model_dump(by_alias=True, mode="json") == %r
            triangle = AreaOfInterest(
                vertices=[
                    GeoPoint(lat_deg=37.5, lon_deg=127.0),
                    GeoPoint(lat_deg=37.5009, lon_deg=127.0),
                    GeoPoint(lat_deg=37.5, lon_deg=127.0012),
                ]
            )
            assert triangle.area_m2() == %r
            for _denied in ("ksi_core.acquisition", "ksi_mission_contracts",
                            "ksi_mission_planning"):
                assert _denied not in sys.modules
                assert not any(
                    module == _denied or module.startswith(_denied + ".")
                    for module in sys.modules
                )
            """
        )
        % (SITEFRAME_WIRE, AOI_TRIANGLE_AREA_M2)
    )


def test_external_ingress_imports_without_acquisition() -> None:
    _assert_subprocess_ok(
        _BLOCKER_PREAMBLE
        + dedent(
            """
            import sys

            import ksi_core.domains.external.ingress.external_reconstruction as ingress
            from ksi_core.domains.observations import epoch_identity

            assert ingress.observation_epoch_id is epoch_identity.observation_epoch_id
            assert "ksi_core.acquisition" not in sys.modules
            assert not any(
                module.startswith("ksi_core.acquisition.") for module in sys.modules
            )
            """
        )
    )


def test_neutral_site_frame_does_not_import_mission_or_acquisition() -> None:
    _assert_subprocess_ok(
        _blocker_prelude(_NEUTRAL_DENIED)
        + dedent(
            """
            import sys

            from ksi_event_contracts.site_frame import SiteFrame

            assert SiteFrame.__module__ == "ksi_event_contracts.site_frame"
            assert "ksi_core.acquisition" not in sys.modules
            """
        )
    )


def test_captured_schema_literals_are_frozen() -> None:
    assert json.loads(json.dumps(SITEFRAME_SCHEMA)) == SITEFRAME_SCHEMA
    assert SITEFRAME_SCHEMA["properties"]["unit"] == {
        "const": "meter",
        "title": "Unit",
        "type": "string",
    }
    assert AOI_TRIANGLE_WIRE["vertices"][0] == {"latDeg": 37.5, "lonDeg": 127.0}
