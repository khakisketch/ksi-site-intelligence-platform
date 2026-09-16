"""Pilot-export FlightArtifact candidates, deliberately outside execution authority.

This module is a narrow FIELD-0a preparation boundary.  A DJI Pilot-exported
KMZ may be structurally validated and retained with its exact bytes, but it is
never copied into :class:`MissionRecord`, a signed Mission Contract, dispatch,
or the active KMZ download route.  The only durable state here is an immutable
``VALIDATED_CANDIDATE_UNBOUND`` record.  A later, separately accepted field
decision may define comparison and binding; this module intentionally does not.

The parser is defensive rather than a DJI compatibility claim: it proves only
that the supplied archive has the minimum WPML shape needed for evidence review.
It does not prove that Pilot 2 will import, display, or execute the candidate.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import math
import stat
import threading
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from xml.etree import ElementTree as ET

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Response
from fastapi.responses import Response as BinaryResponse
from pydantic import Field, field_validator

from ksi_core.domains.artifacts.evidence import EvidenceStorage, EvidenceStorageError
from ksi_core.domains.missions.mission_records import MISSION_NOT_FOUND_DETAIL, MissionStore
from ksi_core.foundation.api_base import JOURNAL_SEALED_DETAIL, CamelModel, iso_utc
from ksi_core.foundation.durable_journal import DurableJournal, JournalSealedError
from ksi_core.foundation.identifiers import is_path_safe_identifier
from ksi_core.identity.auth import Permission, Principal, require_permission

if TYPE_CHECKING:
    from collections.abc import Iterable


_MAX_ARCHIVE_BYTES = 10 * 1024 * 1024
_MAX_MEMBERS = 64
_MAX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
_MAX_COMPRESSION_RATIO = 100
_REQUIRED_MEMBERS = frozenset({"wpmz/template.kml", "wpmz/waylines.wpml"})
_PILOT_EXPORT_SOURCE = "DJI_PILOT_EXPORT"
_CONTENT_TYPE = "application/octet-stream"
_STATUS = "VALIDATED_CANDIDATE_UNBOUND"
_VALIDATOR_VERSION = "1.0"


class FlightArtifactCandidateVerdict(StrEnum):
    RECORDED = "RECORDED"
    DUPLICATE = "DUPLICATE"
    UNKNOWN_MISSION = "UNKNOWN_MISSION"
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"


class FlightArtifactStoreRecoveryError(RuntimeError):
    """A FlightArtifact journal cannot be replayed without guessing."""


@dataclass(frozen=True, slots=True)
class PilotExportInspection:
    """Structural facts extracted from a bounded, hostile-input-safe archive."""

    placemark_count: int
    execute_heights_m: tuple[float, ...]
    execute_height_mode: str | None


@dataclass(frozen=True, slots=True)
class FlightArtifactCandidate:
    candidate_id: str
    revision: int
    organization_id: str
    mission_id: str
    site_id: str
    source: str
    status: str
    validator_version: str
    provenance_ref: str
    kmz_sha256: str
    size_bytes: int
    object_key: str
    placemark_count: int
    min_execute_height_m: float
    max_execute_height_m: float
    envelope_check: str
    validation_limitation: str | None
    validated_at: datetime
    validated_by: str


@dataclass(frozen=True, slots=True)
class FlightArtifactCandidateResult:
    verdict: FlightArtifactCandidateVerdict
    candidate: FlightArtifactCandidate | None = None
    detail: str | None = None


def build_flight_artifact_object_key(*, site_id: str, mission_id: str, candidate_id: str) -> str:
    """Return a server-owned, path-safe storage key for the exact KMZ bytes."""

    for field, value in (
        ("siteId", site_id),
        ("missionId", mission_id),
        ("candidateId", candidate_id),
    ):
        if not is_path_safe_identifier(value):
            raise ValueError(f"경로-안전하지 않은 {field}: {value!r}")
    return f"sites/{site_id}/missions/{mission_id}/flight-artifacts/{candidate_id}.kmz"


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _reject_unsafe_xml(raw: bytes, *, member: str) -> None:
    # stdlib ElementTree is not an authorization boundary.  Explicitly reject
    # DTD/entity declarations before parse so this parser cannot become an XML
    # entity-expansion compatibility exception as the implementation evolves.
    upper = raw.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise ValueError(f"{member}에 DTD/entity 선언은 허용하지 않는다")


def _parse_xml(raw: bytes, *, member: str) -> ET.Element:
    _reject_unsafe_xml(raw, member=member)
    try:
        return ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError(f"{member} XML 파싱 실패") from exc


def inspect_pilot_export_kmz(kmz_bytes: bytes) -> PilotExportInspection:
    """Strictly inspect an exported WPML archive before it reaches storage.

    This requires the two WPML members and permits only bounded, path-safe
    auxiliary members (for example ``wpmz/res/``).  It makes no assertion about
    DJI Pilot import compatibility or route safety beyond the contract-envelope
    comparison performed below.
    """

    if not kmz_bytes or len(kmz_bytes) > _MAX_ARCHIVE_BYTES:
        raise ValueError(f"KMZ는 1..{_MAX_ARCHIVE_BYTES} bytes여야 한다")
    try:
        archive = zipfile.ZipFile(io.BytesIO(kmz_bytes))
    except zipfile.BadZipFile as exc:
        raise ValueError("유효한 ZIP/KMZ 아카이브가 아니다") from exc
    with archive:
        members = archive.infolist()
        if not members or len(members) > _MAX_MEMBERS:
            raise ValueError(f"KMZ member 수는 1..{_MAX_MEMBERS}여야 한다")
        names: set[str] = set()
        uncompressed_total = 0
        for info in members:
            name = info.filename
            # ZIP creators commonly emit explicit directory entries such as
            # ``wpmz/res/``.  Treat the single trailing slash as directory
            # syntax, not as an empty path segment; double slashes and every
            # other empty/traversal segment still fail closed.
            normalized_name = name[:-1] if name.endswith("/") else name
            if (
                not normalized_name
                or "\x00" in name
                or name.startswith(("/", "\\"))
                or "\\" in name
                or name.endswith("//")
                or any(part in {"", ".", ".."} for part in normalized_name.split("/"))
            ):
                raise ValueError("KMZ member 경로가 안전하지 않다")
            if name in names:
                raise ValueError("KMZ에 중복 member 이름이 있다")
            names.add(name)
            if info.flag_bits & 0x1:
                raise ValueError("암호화된 KMZ member는 허용하지 않는다")
            if stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError("symlink KMZ member는 허용하지 않는다")
            if info.file_size < 0 or info.compress_size < 0:
                raise ValueError("KMZ member 크기가 유효하지 않다")
            uncompressed_total += info.file_size
            if uncompressed_total > _MAX_UNCOMPRESSED_BYTES:
                raise ValueError("KMZ 압축 해제 총 크기가 상한을 넘는다")
            if info.file_size and (
                info.compress_size == 0
                or info.file_size / max(info.compress_size, 1) > _MAX_COMPRESSION_RATIO
            ):
                raise ValueError("KMZ member 압축비가 상한을 넘는다")
        if not _REQUIRED_MEMBERS.issubset(names):
            raise ValueError("KMZ에 wpmz/template.kml 및 wpmz/waylines.wpml이 필요하다")
        try:
            template = _parse_xml(archive.read("wpmz/template.kml"), member="template.kml")
            waylines = _parse_xml(archive.read("wpmz/waylines.wpml"), member="waylines.wpml")
        except (KeyError, RuntimeError, zipfile.BadZipFile) as exc:
            raise ValueError("필수 KMZ member를 안전하게 읽을 수 없다") from exc

    placemark_count = sum(
        1 for element in template.iter() if _local_name(element.tag) == "Placemark"
    )
    if placemark_count < 1:
        raise ValueError("template.kml에는 Placemark가 하나 이상 필요하다")
    heights: list[float] = []
    height_mode: str | None = None
    for element in waylines.iter():
        name = _local_name(element.tag)
        if name == "executeHeight":
            text = (element.text or "").strip()
            try:
                height = float(text)
            except ValueError as exc:
                raise ValueError("waylines.wpml executeHeight가 숫자가 아니다") from exc
            if not math.isfinite(height):
                raise ValueError("waylines.wpml executeHeight는 finite여야 한다")
            heights.append(height)
        elif name == "executeHeightMode" and height_mode is None:
            height_mode = (element.text or "").strip() or None
    if not heights:
        raise ValueError("waylines.wpml에는 finite executeHeight가 하나 이상 필요하다")
    return PilotExportInspection(
        placemark_count=placemark_count,
        execute_heights_m=tuple(heights),
        execute_height_mode=height_mode,
    )


def _envelope_check(
    *, contract: dict[str, Any], inspection: PilotExportInspection
) -> tuple[str, str | None]:
    """Compare heights only when both vertical references are explicit/equal."""

    envelope = contract.get("flightEnvelope")
    if not isinstance(envelope, dict):
        return "NOT_COMPARABLE", "Mission Contract에 flightEnvelope가 없어 높이를 대조하지 못했다"
    if (
        envelope.get("altitudeReference") != "relativeToStartPoint"
        or inspection.execute_height_mode != "relativeToStartPoint"
    ):
        return (
            "NOT_COMPARABLE",
            "Contract와 Pilot export의 executeHeight 수직기준을 모두 "
            "relativeToStartPoint로 확인하지 못했다",
        )
    minimum = envelope.get("minAltitudeM")
    maximum = envelope.get("maxAltitudeM")
    if (
        not isinstance(minimum, (int, float))
        or isinstance(minimum, bool)
        or not isinstance(maximum, (int, float))
        or isinstance(maximum, bool)
        or not math.isfinite(float(minimum))
        or not math.isfinite(float(maximum))
    ):
        return "NOT_COMPARABLE", "flightEnvelope min/maxAltitudeM가 finite 수치가 아니다"
    low = min(inspection.execute_heights_m)
    high = max(inspection.execute_heights_m)
    if low < float(minimum) or high > float(maximum):
        raise ValueError(
            "Pilot export executeHeight가 Mission Contract flightEnvelope 고도 범위를 벗어난다"
        )
    return "COMPATIBLE", None


def _require_aware(value: datetime, *, field: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{field}은 tz-aware여야 한다")


def _require_provenance(value: str) -> None:
    if not value or len(value) > 512 or value != value.strip() or any(ord(ch) < 32 for ch in value):
        raise ValueError("provenanceRef는 공백만이 아닌 512자 이하의 제어문자 없는 참조여야 한다")
    try:
        value.encode("utf-8", "strict")
    except UnicodeEncodeError as exc:
        raise ValueError("provenanceRef는 UTF-8로 표현 가능해야 한다") from exc


def _sha256(kmz_bytes: bytes) -> str:
    return f"sha256:{hashlib.sha256(kmz_bytes).hexdigest()}"


def _candidate_from_raw(raw: dict[str, Any]) -> FlightArtifactCandidate:
    if raw.get("kind") != "flight-artifact-candidate-recorded":
        raise ValueError(f"unknown kind={raw.get('kind')!r}")
    candidate = FlightArtifactCandidate(
        candidate_id=str(raw["candidateId"]),
        revision=int(raw["revision"]),
        organization_id=str(raw["organizationId"]),
        mission_id=str(raw["missionId"]),
        site_id=str(raw["siteId"]),
        source=str(raw["source"]),
        status=str(raw["status"]),
        validator_version=str(raw["validatorVersion"]),
        provenance_ref=str(raw["provenanceRef"]),
        kmz_sha256=str(raw["kmzSha256"]),
        size_bytes=int(raw["sizeBytes"]),
        object_key=str(raw["objectKey"]),
        placemark_count=int(raw["placemarkCount"]),
        min_execute_height_m=float(raw["minExecuteHeightM"]),
        max_execute_height_m=float(raw["maxExecuteHeightM"]),
        envelope_check=str(raw["envelopeCheck"]),
        validation_limitation=(
            str(raw["validationLimitation"])
            if raw.get("validationLimitation") is not None
            else None
        ),
        validated_at=datetime.fromisoformat(str(raw["validatedAt"])),
        validated_by=str(raw["validatedBy"]),
    )
    if (
        candidate.source != _PILOT_EXPORT_SOURCE
        or candidate.status != _STATUS
        or candidate.validator_version != _VALIDATOR_VERSION
        or candidate.envelope_check not in {"COMPATIBLE", "NOT_COMPARABLE"}
        or candidate.revision < 1
        or candidate.size_bytes < 1
        or candidate.placemark_count < 1
        or not math.isfinite(candidate.min_execute_height_m)
        or not math.isfinite(candidate.max_execute_height_m)
        or candidate.min_execute_height_m > candidate.max_execute_height_m
        or not candidate.kmz_sha256.startswith("sha256:")
        or len(candidate.kmz_sha256) != 71
    ):
        raise ValueError("candidate record 값이 유효하지 않다")
    _require_aware(candidate.validated_at, field="validatedAt")
    _require_provenance(candidate.provenance_ref)
    for field, value in (
        ("candidateId", candidate.candidate_id),
        ("organizationId", candidate.organization_id),
        ("missionId", candidate.mission_id),
        ("siteId", candidate.site_id),
        ("validatedBy", candidate.validated_by),
    ):
        if not is_path_safe_identifier(value):
            raise ValueError(f"{field} is not path-safe")
    if candidate.object_key != build_flight_artifact_object_key(
        site_id=candidate.site_id,
        mission_id=candidate.mission_id,
        candidate_id=candidate.candidate_id,
    ):
        raise ValueError("candidate objectKey가 서버 생성 규칙과 다르다")
    return candidate


def _candidate_payload(candidate: FlightArtifactCandidate) -> dict[str, Any]:
    return {
        "kind": "flight-artifact-candidate-recorded",
        "ts": iso_utc(candidate.validated_at),
        "candidateId": candidate.candidate_id,
        "revision": candidate.revision,
        "organizationId": candidate.organization_id,
        "missionId": candidate.mission_id,
        "siteId": candidate.site_id,
        "source": candidate.source,
        "status": candidate.status,
        "validatorVersion": candidate.validator_version,
        "provenanceRef": candidate.provenance_ref,
        "kmzSha256": candidate.kmz_sha256,
        "sizeBytes": candidate.size_bytes,
        "objectKey": candidate.object_key,
        "placemarkCount": candidate.placemark_count,
        "minExecuteHeightM": candidate.min_execute_height_m,
        "maxExecuteHeightM": candidate.max_execute_height_m,
        "envelopeCheck": candidate.envelope_check,
        "validationLimitation": candidate.validation_limitation,
        "validatedAt": iso_utc(candidate.validated_at),
        "validatedBy": candidate.validated_by,
    }


class FlightArtifactStore:
    """Append-only candidate journal with exact-byte storage before durability.

    The store owns no mechanism to activate or dispatch a candidate.  Keeping
    the object store write before the journal append is intentional: a storage
    failure cannot create a durable record that promises bytes which do not
    exist.  An append failure may leave an unreachable content-addressed object,
    which is safer than inventing a candidate record and is handled by storage
    retention rather than a destructive compensating delete.
    """

    def __init__(
        self, journal: DurableJournal, *, mission_store: MissionStore, storage: EvidenceStorage
    ) -> None:
        self._journal = journal
        self._mission_store = mission_store
        self._storage = storage
        self._lock = threading.RLock()
        self._by_mission: dict[tuple[str, str], list[FlightArtifactCandidate]] = {}
        self._by_id: dict[tuple[str, str, str], FlightArtifactCandidate] = {}
        try:
            self._replay(journal.replay())
        except BaseException as exc:
            journal.close()
            if isinstance(exc, FlightArtifactStoreRecoveryError):
                raise
            raise FlightArtifactStoreRecoveryError(
                f"flight-artifact journal 재생 실패: {exc}"
            ) from exc

    @property
    def sealed_reason(self) -> str | None:
        return self._journal.sealed_reason

    def _replay(self, records: Iterable[dict[str, Any]]) -> None:
        for raw in records:
            try:
                candidate = _candidate_from_raw(raw)
                mission_key = (candidate.organization_id, candidate.mission_id)
                candidates = self._by_mission.setdefault(mission_key, [])
                if candidate.revision != len(candidates) + 1:
                    raise ValueError("revision sequence is not contiguous")
                if any(item.kmz_sha256 == candidate.kmz_sha256 for item in candidates):
                    raise ValueError("duplicate KMZ digest for mission")
                identity = (candidate.organization_id, candidate.mission_id, candidate.candidate_id)
                if identity in self._by_id:
                    raise ValueError("duplicate candidateId")
                candidates.append(candidate)
                self._by_id[identity] = candidate
            except (KeyError, TypeError, ValueError) as exc:
                raise FlightArtifactStoreRecoveryError(
                    f"flight-artifact journal 재생 실패: {exc}"
                ) from exc

    def ingest_pilot_export(
        self,
        mission_id: str,
        *,
        organization_id: str,
        provenance_ref: str,
        kmz_bytes: bytes,
        validated_by: str,
        now: datetime,
    ) -> FlightArtifactCandidateResult:
        """Store an immutable Pilot export after strict structure and envelope checks."""

        _require_aware(now, field="now")
        _require_provenance(provenance_ref)
        for field, value in (
            ("missionId", mission_id),
            ("organizationId", organization_id),
            ("validatedBy", validated_by),
        ):
            if not is_path_safe_identifier(value):
                raise ValueError(f"{field}은 경로-안전 식별자여야 한다")
        inspection = inspect_pilot_export_kmz(kmz_bytes)
        digest = _sha256(kmz_bytes)
        with self._lock:
            if self._journal.sealed_reason is not None:
                return FlightArtifactCandidateResult(
                    FlightArtifactCandidateVerdict.STORE_UNAVAILABLE, detail=JOURNAL_SEALED_DETAIL
                )
            mission = self._mission_store.get_scoped(mission_id, organization_id=organization_id)
            if mission is None:
                return FlightArtifactCandidateResult(
                    FlightArtifactCandidateVerdict.UNKNOWN_MISSION, detail=MISSION_NOT_FOUND_DETAIL
                )
            mission_key = (organization_id, mission_id)
            candidates = self._by_mission.get(mission_key, [])
            existing = next((item for item in candidates if item.kmz_sha256 == digest), None)
            if existing is not None:
                return FlightArtifactCandidateResult(
                    FlightArtifactCandidateVerdict.DUPLICATE, candidate=existing
                )
            envelope_check, limitation = _envelope_check(
                contract=mission.contract, inspection=inspection
            )
            # Full hash-derived identity is server-generated.  Revision still
            # orders distinct candidates for one mission, but never becomes a
            # substitute for content identity.
            candidate_id = f"pilot-{digest.removeprefix('sha256:')}"
            candidate = FlightArtifactCandidate(
                candidate_id=candidate_id,
                revision=len(candidates) + 1,
                organization_id=organization_id,
                mission_id=mission_id,
                site_id=mission.site_id,
                source=_PILOT_EXPORT_SOURCE,
                status=_STATUS,
                validator_version=_VALIDATOR_VERSION,
                provenance_ref=provenance_ref,
                kmz_sha256=digest,
                size_bytes=len(kmz_bytes),
                object_key=build_flight_artifact_object_key(
                    site_id=mission.site_id, mission_id=mission_id, candidate_id=candidate_id
                ),
                placemark_count=inspection.placemark_count,
                min_execute_height_m=min(inspection.execute_heights_m),
                max_execute_height_m=max(inspection.execute_heights_m),
                envelope_check=envelope_check,
                validation_limitation=limitation,
                validated_at=now,
                validated_by=validated_by,
            )
            try:
                self._storage.put_bytes(candidate.object_key, kmz_bytes, content_type=_CONTENT_TYPE)
            except EvidenceStorageError as exc:
                return FlightArtifactCandidateResult(
                    FlightArtifactCandidateVerdict.STORE_UNAVAILABLE,
                    detail=f"KMZ 보관 실패: {exc}",
                )
            try:
                self._journal.append(_candidate_payload(candidate))
            except JournalSealedError:
                return FlightArtifactCandidateResult(
                    FlightArtifactCandidateVerdict.STORE_UNAVAILABLE, detail=JOURNAL_SEALED_DETAIL
                )
            candidates.append(candidate)
            self._by_mission[mission_key] = candidates
            self._by_id[(organization_id, mission_id, candidate_id)] = candidate
            return FlightArtifactCandidateResult(
                FlightArtifactCandidateVerdict.RECORDED, candidate=candidate
            )

    def list_for_mission(
        self, mission_id: str, *, organization_id: str
    ) -> list[FlightArtifactCandidate]:
        if not is_path_safe_identifier(mission_id) or not is_path_safe_identifier(organization_id):
            return []
        with self._lock:
            return list(self._by_mission.get((organization_id, mission_id), []))

    def has_scoped_mission(self, mission_id: str, *, organization_id: str) -> bool:
        """Return only whether the caller's organization can see this Mission."""

        return (
            self._mission_store.get_scoped(mission_id, organization_id=organization_id) is not None
        )

    def get(
        self, mission_id: str, candidate_id: str, *, organization_id: str
    ) -> FlightArtifactCandidate | None:
        if not all(
            is_path_safe_identifier(value) for value in (mission_id, candidate_id, organization_id)
        ):
            return None
        with self._lock:
            return self._by_id.get((organization_id, mission_id, candidate_id))

    def read_exact_bytes(self, candidate: FlightArtifactCandidate) -> bytes:
        """Read only the exact recorded bytes; mismatches are never downloaded."""

        try:
            kmz_bytes = self._storage.get_bytes(candidate.object_key)
        except EvidenceStorageError:
            raise
        if _sha256(kmz_bytes) != candidate.kmz_sha256:
            raise ValueError("보관된 FlightArtifact KMZ digest가 원장 기록과 다르다")
        return kmz_bytes


class PilotExportIngestRequest(CamelModel):
    kmz_base64: str = Field(min_length=4, max_length=(_MAX_ARCHIVE_BYTES * 4 // 3) + 16)
    provenance_ref: str = Field(min_length=1, max_length=512)

    @field_validator("kmz_base64")
    @classmethod
    def _strict_base64(cls, value: str) -> str:
        try:
            decoded = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("kmzBase64는 strict base64여야 한다") from exc
        if not decoded or len(decoded) > _MAX_ARCHIVE_BYTES:
            raise ValueError(f"KMZ는 1..{_MAX_ARCHIVE_BYTES} bytes여야 한다")
        return value

    @field_validator("provenance_ref")
    @classmethod
    def _valid_provenance(cls, value: str) -> str:
        _require_provenance(value)
        return value


class FlightArtifactCandidateResponse(CamelModel):
    candidate_id: str
    revision: int
    source: str
    status: str
    validator_version: str
    provenance_ref: str
    kmz_sha256: str
    size_bytes: int
    placemark_count: int
    min_execute_height_m: float
    max_execute_height_m: float
    envelope_check: str
    validation_limitation: str | None
    validated_at: datetime
    validated_by: str
    executable: bool = False


class FlightArtifactIngestResponse(CamelModel):
    verdict: FlightArtifactCandidateVerdict
    detail: str | None = None
    candidate: FlightArtifactCandidateResponse | None = None


def _to_response(candidate: FlightArtifactCandidate) -> FlightArtifactCandidateResponse:
    return FlightArtifactCandidateResponse(
        candidate_id=candidate.candidate_id,
        revision=candidate.revision,
        source=candidate.source,
        status=candidate.status,
        validator_version=candidate.validator_version,
        provenance_ref=candidate.provenance_ref,
        kmz_sha256=candidate.kmz_sha256,
        size_bytes=candidate.size_bytes,
        placemark_count=candidate.placemark_count,
        min_execute_height_m=candidate.min_execute_height_m,
        max_execute_height_m=candidate.max_execute_height_m,
        envelope_check=candidate.envelope_check,
        validation_limitation=candidate.validation_limitation,
        validated_at=candidate.validated_at,
        validated_by=candidate.validated_by,
    )


_HTTP_STATUS = {
    FlightArtifactCandidateVerdict.RECORDED: 201,
    FlightArtifactCandidateVerdict.DUPLICATE: 200,
    FlightArtifactCandidateVerdict.UNKNOWN_MISSION: 404,
    FlightArtifactCandidateVerdict.STORE_UNAVAILABLE: 503,
}
_ISSUE_PERMISSION = require_permission(Permission.MISSIONS_ISSUE)
_READ_PERMISSION = require_permission(Permission.MISSIONS_READ)


def build_flight_artifacts_router(store: FlightArtifactStore) -> APIRouter:
    router = APIRouter(prefix="/v1/missions", tags=["flight-artifacts"])

    @router.post(
        "/{mission_id}/flight-artifacts/pilot-export",
        response_model=FlightArtifactIngestResponse,
    )
    def ingest_pilot_export(
        mission_id: str,
        request: PilotExportIngestRequest,
        response: Response,
        principal: Principal = Depends(_ISSUE_PERMISSION),  # noqa: B008
    ) -> FlightArtifactIngestResponse:
        try:
            kmz_bytes = base64.b64decode(request.kmz_base64, validate=True)
            result = store.ingest_pilot_export(
                mission_id,
                organization_id=principal.organization_id,
                provenance_ref=request.provenance_ref,
                kmz_bytes=kmz_bytes,
                validated_by=principal.principal_id,
                now=datetime.now(UTC),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        response.status_code = _HTTP_STATUS[result.verdict]
        if result.verdict is FlightArtifactCandidateVerdict.STORE_UNAVAILABLE:
            response.headers["Retry-After"] = "30"
        return FlightArtifactIngestResponse(
            verdict=result.verdict,
            detail=result.detail,
            candidate=_to_response(result.candidate) if result.candidate is not None else None,
        )

    @router.get(
        "/{mission_id}/flight-artifacts", response_model=list[FlightArtifactCandidateResponse]
    )
    def list_flight_artifacts(
        mission_id: str,
        principal: Principal = Depends(_READ_PERMISSION),  # noqa: B008
    ) -> list[FlightArtifactCandidateResponse]:
        # MissionStore is consulted first so an empty list cannot become a
        # cross-organization mission existence oracle.
        if not store.has_scoped_mission(mission_id, organization_id=principal.organization_id):
            raise HTTPException(status_code=404, detail=MISSION_NOT_FOUND_DETAIL)
        return [
            _to_response(item)
            for item in store.list_for_mission(
                mission_id, organization_id=principal.organization_id
            )
        ]

    @router.get("/{mission_id}/flight-artifacts/{candidate_id}/download")
    def download_flight_artifact(
        mission_id: str,
        candidate_id: str,
        principal: Principal = Depends(_READ_PERMISSION),  # noqa: B008
    ) -> BinaryResponse:
        candidate = store.get(mission_id, candidate_id, organization_id=principal.organization_id)
        if candidate is None:
            raise HTTPException(status_code=404, detail="FlightArtifact candidate를 찾을 수 없다")
        try:
            kmz_bytes = store.read_exact_bytes(candidate)
        except EvidenceStorageError as exc:
            raise HTTPException(
                status_code=503, detail="FlightArtifact 보관소를 읽을 수 없다"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return BinaryResponse(
            content=kmz_bytes,
            media_type=_CONTENT_TYPE,
            headers={
                "Content-Disposition": f'attachment; filename="{candidate.candidate_id}.kmz"',
                "X-KSI-FlightArtifact-Status": _STATUS,
                "X-KSI-Executable": "false",
            },
        )

    return router


def mount_flight_artifacts(app: FastAPI, store: FlightArtifactStore) -> None:
    app.state.flight_artifact_store = store
    app.include_router(build_flight_artifacts_router(store))


__all__ = [
    "FlightArtifactCandidate",
    "FlightArtifactCandidateResult",
    "FlightArtifactCandidateVerdict",
    "FlightArtifactStore",
    "FlightArtifactStoreRecoveryError",
    "PilotExportInspection",
    "PilotExportIngestRequest",
    "build_flight_artifact_object_key",
    "build_flight_artifacts_router",
    "inspect_pilot_export_kmz",
    "mount_flight_artifacts",
]
