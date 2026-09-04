"""Core-owned validation of an independently surveyed checkpoint CSV against a DSM.

The operator can attest to checkpoint independence, but cannot submit an
accuracy value.  A processing worker measures sealed bytes and the immutable
DSM artifact; this store recomputes the terminal verdict during journal replay.
That keeps the existing artifact producer claim separate from the KSI-verified
measurement required by INV-024/053.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from ksi_event_contracts.change_detection_result import ArtifactRef
from ksi_event_contracts.checkpoint_validation import (
    CHECKPOINT_CSV_CONTENT_TYPE,
    CHECKPOINT_FILE_MAX_BYTES,
    CHECKPOINT_POINT_MAX,
    CHECKPOINT_POINT_MIN,
    CheckpointFileDeclared,
    CheckpointValidation,
    CheckpointValidationObserved,
    CheckpointValidationRejectionReason,
    CheckpointValidationStatus,
)
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from ksi_event_contracts.processing_job import ProcessingJobStatus
from ksi_event_contracts.vertical_reference import VerticalBridge, bridge_between
from ksi_geo_spatial.crs import (
    UnsupportedCrsError,
    assert_supported_project_crs,
    normalise_crs,
)
from pydantic import Field, ValidationError

from ksi_core.api_base import JOURNAL_SEALED_DETAIL, CamelModel, iso_utc
from ksi_core.auth import Permission, Principal, current_request_organization_id, require_permission
from ksi_core.durable_journal import DurableJournal, JournalSealedError
from ksi_core.evidence import (
    DEFAULT_UPLOAD_TTL,
    DEFAULT_VIEW_TTL,
    EvidenceStorage,
    EvidenceStorageError,
    expires_at,
)
from ksi_core.identifiers import is_path_safe_identifier

if TYPE_CHECKING:
    from fastapi import FastAPI

    from ksi_core.mission_records import MissionStore
    from ksi_core.processing_jobs import ProcessingJobStore

logger = logging.getLogger(__name__)
_NOT_FOUND = "해당 검사점 검증 기록을 찾을 수 없다"
MAX_PENDING_LIMIT = 200

_WORKER_FAILURE_REASONS = frozenset(
    {
        # The worker cannot construct a valid observation when the checkpoint
        # bytes exceed the contract or the DSM CRS cannot be sampled.
        CheckpointValidationRejectionReason.CHECKPOINT_SIZE_MISMATCH,
        CheckpointValidationRejectionReason.CHECKPOINT_OBJECT_MISSING,
        CheckpointValidationRejectionReason.DSM_CRS_MISMATCH,
        CheckpointValidationRejectionReason.DSM_OBJECT_MISSING,
        CheckpointValidationRejectionReason.INVALID_CHECKPOINT_CSV,
        CheckpointValidationRejectionReason.CHECKPOINT_COUNT_OUT_OF_RANGE,
        CheckpointValidationRejectionReason.CHECKPOINT_OUTSIDE_DSM,
        CheckpointValidationRejectionReason.DSM_NODATA_AT_CHECKPOINT,
        CheckpointValidationRejectionReason.UNREADABLE_DSM,
        CheckpointValidationRejectionReason.UNSUPPORTED_DSM,
        CheckpointValidationRejectionReason.INVALID_MEASUREMENT,
    }
)


class CheckpointValidationVerdict(StrEnum):
    REGISTERED = "REGISTERED"
    ALREADY_REGISTERED = "ALREADY_REGISTERED"
    SEALED = "SEALED"
    ALREADY_SEALED = "ALREADY_SEALED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"
    NOT_SEALED = "NOT_SEALED"
    ALREADY_JUDGED = "ALREADY_JUDGED"
    JOB_NOT_SUCCEEDED = "JOB_NOT_SUCCEEDED"
    NOT_DSM_ARTIFACT = "NOT_DSM_ARTIFACT"
    DSM_METADATA_MISSING = "DSM_METADATA_MISSING"
    CRS_MISMATCH = "CRS_MISMATCH"
    VERTICAL_REFERENCE_MISMATCH = "VERTICAL_REFERENCE_MISMATCH"
    VALIDATED_RESULT_EXISTS = "VALIDATED_RESULT_EXISTS"
    ACTIVE_VALIDATION_EXISTS = "ACTIVE_VALIDATION_EXISTS"
    REGISTRATION_DISABLED = "REGISTRATION_DISABLED"
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"


_STATUS: dict[CheckpointValidationVerdict, int] = {
    CheckpointValidationVerdict.REGISTERED: 201,
    CheckpointValidationVerdict.ALREADY_REGISTERED: 200,
    CheckpointValidationVerdict.SEALED: 201,
    CheckpointValidationVerdict.ALREADY_SEALED: 200,
    CheckpointValidationVerdict.VALIDATED: 201,
    CheckpointValidationVerdict.REJECTED: 422,
    CheckpointValidationVerdict.UNKNOWN: 404,
    CheckpointValidationVerdict.NOT_SEALED: 409,
    CheckpointValidationVerdict.ALREADY_JUDGED: 200,
    CheckpointValidationVerdict.JOB_NOT_SUCCEEDED: 409,
    CheckpointValidationVerdict.NOT_DSM_ARTIFACT: 422,
    CheckpointValidationVerdict.DSM_METADATA_MISSING: 409,
    CheckpointValidationVerdict.CRS_MISMATCH: 422,
    CheckpointValidationVerdict.VERTICAL_REFERENCE_MISMATCH: 422,
    CheckpointValidationVerdict.VALIDATED_RESULT_EXISTS: 409,
    CheckpointValidationVerdict.ACTIVE_VALIDATION_EXISTS: 409,
    CheckpointValidationVerdict.REGISTRATION_DISABLED: 403,
    CheckpointValidationVerdict.STORE_UNAVAILABLE: 503,
}


class CheckpointValidationRecoveryError(RuntimeError):
    """A checkpoint journal cannot be trusted after a failed replay."""


@dataclass(frozen=True, slots=True)
class StoreResult:
    verdict: CheckpointValidationVerdict
    record: CheckpointValidation | None = None
    detail: str | None = None
    object_key: str | None = None


def build_checkpoint_validation_id(job_id: str, artifact_id: str, sequence: int) -> str:
    if (
        not is_path_safe_identifier(job_id)
        or not is_path_safe_identifier(artifact_id)
        or sequence < 1
    ):
        raise ValueError("검사점 검증 식별자 입력이 경로-안전하지 않다")
    return f"{job_id}-{artifact_id}-cv{sequence}"


def build_checkpoint_object_key(*, site_id: str, validation_id: str) -> str:
    if not is_path_safe_identifier(site_id) or not is_path_safe_identifier(validation_id):
        raise ValueError("검사점 객체 키 입력이 경로-안전하지 않다")
    return f"sites/{site_id}/checkpoint-validations/{validation_id}/checkpoints.csv"


def _require_aware(raw: Any, field: str, validation_id: str) -> datetime:
    if not isinstance(raw, str):
        raise CheckpointValidationRecoveryError(
            f"재생: {field} 가 문자열이 아니다: {validation_id}"
        )
    try:
        value = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise CheckpointValidationRecoveryError(
            f"재생: {field} 가 ISO 시각이 아니다: {validation_id}"
        ) from exc
    if value.tzinfo is None:
        raise CheckpointValidationRecoveryError(f"재생: {field} 가 naive datetime: {validation_id}")
    return value


def _advanced(record: CheckpointValidation, **changes: Any) -> CheckpointValidation:
    return CheckpointValidation.model_validate({**record.model_dump(), **changes})


def _observed_reason(
    record: CheckpointValidation, observed: CheckpointValidationObserved
) -> CheckpointValidationRejectionReason | None:
    """Core verdict from worker measurements only; reused for replay tamper detection."""
    if observed.checkpoint_sha256 != record.declared.sha256:
        return CheckpointValidationRejectionReason.CHECKPOINT_DIGEST_MISMATCH
    if observed.checkpoint_size_bytes != record.declared.size_bytes:
        return CheckpointValidationRejectionReason.CHECKPOINT_SIZE_MISMATCH
    if observed.dsm_digest != record.dsm_digest:
        return CheckpointValidationRejectionReason.DSM_DIGEST_MISMATCH
    try:
        if normalise_crs(observed.dsm_crs) != normalise_crs(record.dsm_crs):
            return CheckpointValidationRejectionReason.DSM_CRS_MISMATCH
    except UnsupportedCrsError:
        return CheckpointValidationRejectionReason.DSM_CRS_MISMATCH
    return None


class CheckpointValidationStore:
    def __init__(
        self,
        journal: DurableJournal,
        *,
        processing_jobs: ProcessingJobStore,
        mission_store: MissionStore,
    ) -> None:
        self._journal = journal
        self._processing_jobs = processing_jobs
        self._mission_store = mission_store
        self._lock = threading.Lock()
        self._records: dict[str, CheckpointValidation] = {}
        try:
            self._replay(journal)
        except BaseException as exc:
            journal.close()
            if isinstance(exc, CheckpointValidationRecoveryError):
                raise
            raise CheckpointValidationRecoveryError(
                f"checkpoint-validation journal 재생 실패: {exc}"
            ) from exc

    @property
    def sealed_reason(self) -> str | None:
        return self._journal.sealed_reason

    def _replay(self, journal: DurableJournal) -> None:
        for raw in journal.replay():
            kind = raw.get("kind")
            validation_id = raw.get("validationId")
            if not isinstance(validation_id, str) or not is_path_safe_identifier(validation_id):
                raise CheckpointValidationRecoveryError("재생: validationId 가 경로-안전하지 않다")
            if kind == "checkpoint-validation-registered":
                if validation_id in self._records:
                    raise CheckpointValidationRecoveryError(
                        f"재생: validationId 중복: {validation_id}"
                    )
                try:
                    declared = CheckpointFileDeclared.model_validate(raw["declared"])
                    dsm_vertical = raw["dsmVerticalReference"]
                    record = CheckpointValidation(
                        validation_id=validation_id,
                        organization_id=raw["organizationId"],
                        mission_id=raw["missionId"],
                        site_id=raw["siteId"],
                        dsm=ArtifactRef.model_validate(raw["dsm"]),
                        dsm_digest=raw["dsmDigest"],
                        dsm_crs=raw["dsmCrs"],
                        dsm_vertical_reference=dsm_vertical,
                        declared=declared,
                        status=CheckpointValidationStatus.REGISTERED,
                        registered_at=_require_aware(raw["ts"], "ts", validation_id),
                        registered_by=raw["registeredBy"],
                    )
                except (ValidationError, KeyError, TypeError) as exc:
                    raise CheckpointValidationRecoveryError(
                        f"재생: 등록 레코드가 계약을 만족하지 않는다: {validation_id}"
                    ) from exc
                self._assert_record_metadata(record)
                if any(
                    existing.dsm == record.dsm
                    and existing.status
                    in {
                        CheckpointValidationStatus.REGISTERED,
                        CheckpointValidationStatus.SEALED,
                        CheckpointValidationStatus.VALIDATED,
                    }
                    for existing in self._records.values()
                ):
                    raise CheckpointValidationRecoveryError(
                        "재생: DSM 하나에 동시 active/validated 검증이 둘 이상이다: "
                        f"{validation_id}"
                    )
                self._records[validation_id] = record
            elif kind == "checkpoint-validation-sealed":
                record = self._replay_get(validation_id)
                if record.status is not CheckpointValidationStatus.REGISTERED:
                    raise CheckpointValidationRecoveryError(
                        f"재생: seal 전이가 불법이다: {validation_id}"
                    )
                self._records[validation_id] = _advanced(
                    record,
                    status=CheckpointValidationStatus.SEALED,
                    sealed_at=_require_aware(raw["ts"], "ts", validation_id),
                )
            elif kind == "checkpoint-validation-observed":
                record = self._replay_get(validation_id)
                if record.status is not CheckpointValidationStatus.SEALED:
                    raise CheckpointValidationRecoveryError(
                        f"재생: observation 전이가 불법이다: {validation_id}"
                    )
                try:
                    observed = CheckpointValidationObserved.model_validate(raw["observed"])
                except (ValidationError, KeyError, TypeError) as exc:
                    raise CheckpointValidationRecoveryError(
                        f"재생: observed 계약 위반: {validation_id}"
                    ) from exc
                reason = _observed_reason(record, observed)
                expected_status = (
                    CheckpointValidationStatus.VALIDATED
                    if reason is None
                    else CheckpointValidationStatus.REJECTED
                )
                if raw.get("status") != expected_status.value or raw.get("rejectionReason") != (
                    reason.value if reason else None
                ):
                    raise CheckpointValidationRecoveryError(
                        f"재생: 관측 판정 위조/불일치: {validation_id}"
                    )
                self._records[validation_id] = _advanced(
                    record, status=expected_status, observed=observed, rejection_reason=reason
                )
            elif kind == "checkpoint-validation-failed":
                record = self._replay_get(validation_id)
                if record.status is not CheckpointValidationStatus.SEALED:
                    raise CheckpointValidationRecoveryError(
                        f"재생: failure 전이가 불법이다: {validation_id}"
                    )
                try:
                    reason = CheckpointValidationRejectionReason(raw["reason"])
                except (KeyError, ValueError) as exc:
                    raise CheckpointValidationRecoveryError(
                        f"재생: 미지 failure reason: {validation_id}"
                    ) from exc
                if reason not in _WORKER_FAILURE_REASONS:
                    raise CheckpointValidationRecoveryError(
                        f"재생: worker가 허용되지 않은 rejection을 제출했다: {validation_id}"
                    )
                self._records[validation_id] = _advanced(
                    record,
                    status=CheckpointValidationStatus.REJECTED,
                    rejection_reason=reason,
                    rejection_detail=raw.get("detail"),
                )
            else:
                raise CheckpointValidationRecoveryError(f"재생: 알 수 없는 kind: {kind!r}")

    def _replay_get(self, validation_id: str) -> CheckpointValidation:
        record = self._records.get(validation_id)
        if record is None:
            raise CheckpointValidationRecoveryError(
                f"재생: 등록되지 않은 validationId: {validation_id}"
            )
        return record

    def _assert_record_metadata(self, record: CheckpointValidation) -> None:
        """Rebind every journal snapshot to current immutable source ledgers.

        A self-consistent checkpoint journal is not sufficient: an attacker
        must not be able to swap its mission, artifact digest, CRS, or vertical
        reference while leaving the processing and mission journals intact.
        """

        mission = self._mission_store.get_scoped(
            record.mission_id, organization_id=record.organization_id
        )
        found = self._processing_jobs.artifact_of(record.dsm.job_id, record.dsm.artifact_id)
        if mission is None or found is None:
            raise CheckpointValidationRecoveryError(
                "재생: checkpoint source mission/DSM이 원본 원장에 존재하지 않는다"
            )
        job, artifact = found
        if (
            mission.site_id != record.site_id
            or job.job_id != record.dsm.job_id
            or job.mission_id != record.mission_id
            or job.site_id != record.site_id
            or job.status is not ProcessingJobStatus.SUCCEEDED
            or artifact.kind is not ProcessingArtifactKind.DSM
            or artifact.digest != record.dsm_digest
            or artifact.crs is None
            or artifact.vertical_reference is None
            or artifact.vertical_reference != record.dsm_vertical_reference
        ):
            raise CheckpointValidationRecoveryError(
                "재생: checkpoint snapshot이 mission/processing 원장과 일치하지 않는다"
            )
        try:
            declared_crs = assert_supported_project_crs(record.declared.crs)
            dsm_crs = assert_supported_project_crs(record.dsm_crs)
            artifact_crs = assert_supported_project_crs(artifact.crs)
        except UnsupportedCrsError as exc:
            raise CheckpointValidationRecoveryError(
                "재생: checkpoint/DSM CRS가 지원되지 않는다"
            ) from exc
        if (
            declared_crs != dsm_crs
            or dsm_crs != artifact_crs
            or bridge_between(record.declared.vertical_reference, record.dsm_vertical_reference)
            is not VerticalBridge.DIRECT
        ):
            raise CheckpointValidationRecoveryError(
                "재생: checkpoint 선언과 DSM snapshot이 비교 가능하지 않다"
            )

    def _visible(self, record: CheckpointValidation) -> bool:
        org = current_request_organization_id()
        if org is None:
            return True
        mission = self._mission_store.get_scoped(record.mission_id, organization_id=org)
        return (
            mission is not None
            and mission.site_id == record.site_id
            and record.organization_id == org
        )

    def _validated_for_artifact_locked(self, dsm: ArtifactRef) -> CheckpointValidation | None:
        return next(
            (
                r
                for r in self._records.values()
                if r.dsm == dsm and r.status is CheckpointValidationStatus.VALIDATED
            ),
            None,
        )

    def register(
        self,
        job_id: str,
        artifact_id: str,
        declared: CheckpointFileDeclared,
        *,
        registered_by: str,
        now: datetime,
    ) -> StoreResult:
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        with self._lock:
            if self._journal.sealed_reason:
                return StoreResult(
                    CheckpointValidationVerdict.STORE_UNAVAILABLE, detail=JOURNAL_SEALED_DETAIL
                )
            found = self._processing_jobs.artifact_of(job_id, artifact_id)
            if found is None:
                return StoreResult(CheckpointValidationVerdict.UNKNOWN, detail=_NOT_FOUND)
            job, artifact = found
            org = current_request_organization_id()
            mission = (
                self._mission_store.get_scoped(job.mission_id, organization_id=org)
                if org
                else self._mission_store.get(job.mission_id)
            )
            if mission is None or mission.site_id != job.site_id:
                return StoreResult(CheckpointValidationVerdict.UNKNOWN, detail=_NOT_FOUND)
            if job.status is not ProcessingJobStatus.SUCCEEDED:
                return StoreResult(CheckpointValidationVerdict.JOB_NOT_SUCCEEDED)
            if artifact.kind is not ProcessingArtifactKind.DSM:
                return StoreResult(CheckpointValidationVerdict.NOT_DSM_ARTIFACT)
            if artifact.crs is None or artifact.vertical_reference is None:
                return StoreResult(CheckpointValidationVerdict.DSM_METADATA_MISSING)
            try:
                if assert_supported_project_crs(declared.crs) != assert_supported_project_crs(
                    artifact.crs
                ):
                    return StoreResult(CheckpointValidationVerdict.CRS_MISMATCH)
            except UnsupportedCrsError:
                return StoreResult(CheckpointValidationVerdict.CRS_MISMATCH)
            if (
                bridge_between(declared.vertical_reference, artifact.vertical_reference)
                is not VerticalBridge.DIRECT
            ):
                return StoreResult(CheckpointValidationVerdict.VERTICAL_REFERENCE_MISMATCH)
            dsm = ArtifactRef(job_id=job_id, artifact_id=artifact_id)
            active = next(
                (
                    r
                    for r in self._records.values()
                    if r.dsm == dsm
                    and r.status
                    in {CheckpointValidationStatus.REGISTERED, CheckpointValidationStatus.SEALED}
                ),
                None,
            )
            if (
                active is not None
                and active.declared == declared
                and active.status is CheckpointValidationStatus.REGISTERED
            ):
                return StoreResult(
                    CheckpointValidationVerdict.ALREADY_REGISTERED,
                    active,
                    object_key=build_checkpoint_object_key(
                        site_id=active.site_id, validation_id=active.validation_id
                    ),
                )
            if active is not None and active.declared == declared:
                return StoreResult(CheckpointValidationVerdict.ALREADY_SEALED, active)
            if active is not None:
                return StoreResult(CheckpointValidationVerdict.ACTIVE_VALIDATION_EXISTS)
            if self._validated_for_artifact_locked(dsm):
                return StoreResult(CheckpointValidationVerdict.VALIDATED_RESULT_EXISTS)
            sequence = 1 + sum(1 for r in self._records.values() if r.dsm == dsm)
            validation_id = build_checkpoint_validation_id(job_id, artifact_id, sequence)
            record = CheckpointValidation(
                validation_id=validation_id,
                organization_id=mission.organization_id,
                mission_id=job.mission_id,
                site_id=job.site_id,
                dsm=dsm,
                dsm_digest=artifact.digest,
                dsm_crs=assert_supported_project_crs(artifact.crs),
                dsm_vertical_reference=artifact.vertical_reference,
                declared=declared,
                status=CheckpointValidationStatus.REGISTERED,
                registered_at=now,
                registered_by=registered_by,
            )
            object_key = build_checkpoint_object_key(
                site_id=job.site_id, validation_id=validation_id
            )
            payload = {
                "kind": "checkpoint-validation-registered",
                "ts": iso_utc(now),
                "validationId": validation_id,
                "organizationId": record.organization_id,
                "missionId": record.mission_id,
                "siteId": record.site_id,
                "dsm": record.dsm.model_dump(by_alias=True, mode="json"),
                "dsmDigest": record.dsm_digest,
                "dsmCrs": record.dsm_crs,
                "dsmVerticalReference": record.dsm_vertical_reference.model_dump(
                    by_alias=True, mode="json"
                ),
                "declared": declared.model_dump(by_alias=True, mode="json"),
                "registeredBy": registered_by,
            }
            try:
                self._journal.append(payload)
            except JournalSealedError:
                return StoreResult(
                    CheckpointValidationVerdict.STORE_UNAVAILABLE, detail=JOURNAL_SEALED_DETAIL
                )
            self._records[validation_id] = record
            return StoreResult(
                CheckpointValidationVerdict.REGISTERED, record, object_key=object_key
            )

    def seal(self, validation_id: str, *, now: datetime) -> StoreResult:
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        with self._lock:
            if self._journal.sealed_reason:
                return StoreResult(
                    CheckpointValidationVerdict.STORE_UNAVAILABLE, detail=JOURNAL_SEALED_DETAIL
                )
            record = self._records.get(validation_id)
            if record is None or not self._visible(record):
                return StoreResult(CheckpointValidationVerdict.UNKNOWN, detail=_NOT_FOUND)
            if record.status is CheckpointValidationStatus.SEALED:
                return StoreResult(CheckpointValidationVerdict.ALREADY_SEALED, record)
            if record.status is not CheckpointValidationStatus.REGISTERED:
                return StoreResult(CheckpointValidationVerdict.ALREADY_JUDGED, record)
            try:
                self._journal.append(
                    {
                        "kind": "checkpoint-validation-sealed",
                        "ts": iso_utc(now),
                        "validationId": validation_id,
                    }
                )
            except JournalSealedError:
                return StoreResult(
                    CheckpointValidationVerdict.STORE_UNAVAILABLE, detail=JOURNAL_SEALED_DETAIL
                )
            record = _advanced(record, status=CheckpointValidationStatus.SEALED, sealed_at=now)
            self._records[validation_id] = record
            return StoreResult(CheckpointValidationVerdict.SEALED, record)

    def observe(
        self, validation_id: str, observed: CheckpointValidationObserved, *, now: datetime
    ) -> StoreResult:
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        with self._lock:
            if self._journal.sealed_reason:
                return StoreResult(
                    CheckpointValidationVerdict.STORE_UNAVAILABLE, detail=JOURNAL_SEALED_DETAIL
                )
            record = self._records.get(validation_id)
            if record is None or not self._visible(record):
                return StoreResult(CheckpointValidationVerdict.UNKNOWN, detail=_NOT_FOUND)
            if record.status is CheckpointValidationStatus.REGISTERED:
                return StoreResult(CheckpointValidationVerdict.NOT_SEALED, record)
            if record.status is not CheckpointValidationStatus.SEALED:
                return StoreResult(CheckpointValidationVerdict.ALREADY_JUDGED, record)
            reason = _observed_reason(record, observed)
            status = (
                CheckpointValidationStatus.VALIDATED
                if reason is None
                else CheckpointValidationStatus.REJECTED
            )
            if (
                status is CheckpointValidationStatus.VALIDATED
                and self._validated_for_artifact_locked(record.dsm)
            ):
                return StoreResult(CheckpointValidationVerdict.VALIDATED_RESULT_EXISTS, record)
            payload = {
                "kind": "checkpoint-validation-observed",
                "ts": iso_utc(now),
                "validationId": validation_id,
                "observed": observed.model_dump(by_alias=True, mode="json"),
                "status": status.value,
                "rejectionReason": reason.value if reason else None,
            }
            try:
                self._journal.append(payload)
            except JournalSealedError:
                return StoreResult(
                    CheckpointValidationVerdict.STORE_UNAVAILABLE, detail=JOURNAL_SEALED_DETAIL
                )
            record = _advanced(record, status=status, observed=observed, rejection_reason=reason)
            self._records[validation_id] = record
            return StoreResult(
                CheckpointValidationVerdict.VALIDATED
                if reason is None
                else CheckpointValidationVerdict.REJECTED,
                record,
            )

    def verification_failure(
        self,
        validation_id: str,
        reason: CheckpointValidationRejectionReason,
        detail: str | None,
        *,
        now: datetime,
    ) -> StoreResult:
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        if reason not in _WORKER_FAILURE_REASONS:
            raise ValueError("허용되지 않은 checkpoint validation failure reason")
        with self._lock:
            if self._journal.sealed_reason:
                return StoreResult(
                    CheckpointValidationVerdict.STORE_UNAVAILABLE, detail=JOURNAL_SEALED_DETAIL
                )
            record = self._records.get(validation_id)
            if record is None or not self._visible(record):
                return StoreResult(CheckpointValidationVerdict.UNKNOWN, detail=_NOT_FOUND)
            if record.status is CheckpointValidationStatus.REGISTERED:
                return StoreResult(CheckpointValidationVerdict.NOT_SEALED, record)
            if record.status is not CheckpointValidationStatus.SEALED:
                return StoreResult(CheckpointValidationVerdict.ALREADY_JUDGED, record)
            try:
                self._journal.append(
                    {
                        "kind": "checkpoint-validation-failed",
                        "ts": iso_utc(now),
                        "validationId": validation_id,
                        "reason": reason.value,
                        "detail": detail,
                    }
                )
            except JournalSealedError:
                return StoreResult(
                    CheckpointValidationVerdict.STORE_UNAVAILABLE, detail=JOURNAL_SEALED_DETAIL
                )
            record = _advanced(
                record,
                status=CheckpointValidationStatus.REJECTED,
                rejection_reason=reason,
                rejection_detail=detail,
            )
            self._records[validation_id] = record
            return StoreResult(CheckpointValidationVerdict.REJECTED, record)

    def get(self, validation_id: str) -> CheckpointValidation | None:
        with self._lock:
            record = self._records.get(validation_id)
        return record if record is not None and self._visible(record) else None

    def list_for_job(self, job_id: str) -> list[CheckpointValidation]:
        with self._lock:
            values = [
                r for r in self._records.values() if r.dsm.job_id == job_id and self._visible(r)
            ]
        return sorted(values, key=lambda r: (r.registered_at, r.validation_id))

    def list_pending(self, *, limit: int) -> list[CheckpointValidation]:
        with self._lock:
            values = [
                r
                for r in self._records.values()
                if r.status is CheckpointValidationStatus.SEALED and self._visible(r)
            ]
        return sorted(values, key=lambda r: (r.sealed_at or r.registered_at, r.validation_id))[
            :limit
        ]

    def validated_record_for(self, dsm: ArtifactRef) -> CheckpointValidation | None:
        with self._lock:
            record = self._validated_for_artifact_locked(dsm)
        return record if record is not None and self._visible(record) else None

    def validated_rmse_for(self, dsm: ArtifactRef) -> float | None:
        record = self.validated_record_for(dsm)
        return (
            record.observed.rmse_m if record is not None and record.observed is not None else None
        )


class CheckpointValidationRegisterRequest(CamelModel):
    declared: CheckpointFileDeclared


class CheckpointValidationObservationRequest(CamelModel):
    checkpoint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    checkpoint_size_bytes: int = Field(ge=1, le=CHECKPOINT_FILE_MAX_BYTES)
    dsm_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    dsm_crs: str = Field(min_length=1)
    point_count: int = Field(ge=CHECKPOINT_POINT_MIN, le=CHECKPOINT_POINT_MAX)
    mean_error_m: float
    mae_m: float = Field(ge=0.0)
    rmse_m: float = Field(ge=0.0)
    max_abs_error_m: float = Field(ge=0.0)


class CheckpointValidationFailureRequest(CamelModel):
    reason: CheckpointValidationRejectionReason
    detail: str | None = Field(default=None, max_length=500)


class CheckpointValidationResponse(CamelModel):
    verdict: str
    detail: str | None = None
    validation: CheckpointValidation | None = None
    validation_id: str | None = None
    object_key: str | None = None
    upload_url: str | None = None
    expires_at: datetime | None = None


class CheckpointValidationListResponse(CamelModel):
    validations: list[CheckpointValidation]


class PendingCheckpointValidation(CamelModel):
    validation_id: str
    checkpoint_download_url: str
    dsm_download_url: str
    checkpoint_crs: str
    checkpoint_vertical_reference: dict[str, Any]
    dsm_crs: str
    dsm_vertical_reference: dict[str, Any]
    expires_at: datetime


class PendingCheckpointValidationListResponse(CamelModel):
    validations: list[PendingCheckpointValidation]


def build_checkpoint_validations_router(
    store: CheckpointValidationStore,
    storage: EvidenceStorage,
    *,
    registration_enabled: bool = False,
) -> APIRouter:
    router = APIRouter(tags=["checkpoint-validations"])

    @router.post(
        "/v1/processing-jobs/{job_id}/artifacts/{artifact_id}/checkpoint-validations",
        response_model=CheckpointValidationResponse,
        status_code=201,
    )
    def register(
        job_id: str,
        artifact_id: str,
        request: CheckpointValidationRegisterRequest,
        response: Response,
        principal: Principal = Depends(require_permission(Permission.SITES_WRITE)),  # noqa: B008
    ) -> CheckpointValidationResponse:
        if not registration_enabled:
            response.status_code = 403
            return CheckpointValidationResponse(
                verdict=CheckpointValidationVerdict.REGISTRATION_DISABLED.value
            )
        now = datetime.now(UTC)
        result = store.register(
            job_id, artifact_id, request.declared, registered_by=principal.principal_id, now=now
        )
        response.status_code = _STATUS[result.verdict]
        if result.verdict is CheckpointValidationVerdict.STORE_UNAVAILABLE:
            response.headers["Retry-After"] = "30"
        if result.record is None:
            return CheckpointValidationResponse(verdict=result.verdict.value, detail=result.detail)
        if result.verdict not in {
            CheckpointValidationVerdict.REGISTERED,
            CheckpointValidationVerdict.ALREADY_REGISTERED,
        }:
            return CheckpointValidationResponse(
                verdict=result.verdict.value, detail=result.detail, validation=result.record
            )
        assert result.object_key is not None
        try:
            url = storage.presigned_put(
                result.object_key, content_type=CHECKPOINT_CSV_CONTENT_TYPE, ttl=DEFAULT_UPLOAD_TTL
            )
        except EvidenceStorageError:
            response.status_code = 503
            response.headers["Retry-After"] = "30"
            return CheckpointValidationResponse(
                verdict=CheckpointValidationVerdict.STORE_UNAVAILABLE.value,
                detail="등록은 됐으나 업로드 URL 발급에 실패했다",
                validation=result.record,
                validation_id=result.record.validation_id,
                object_key=result.object_key,
            )
        return CheckpointValidationResponse(
            verdict=result.verdict.value,
            validation=result.record,
            validation_id=result.record.validation_id,
            object_key=result.object_key,
            upload_url=url,
            expires_at=expires_at(now, DEFAULT_UPLOAD_TTL),
        )

    @router.post(
        "/v1/checkpoint-validations/{validation_id}/seal",
        response_model=CheckpointValidationResponse,
        status_code=201,
    )
    def seal(
        validation_id: str,
        response: Response,
        principal: Principal = Depends(require_permission(Permission.SITES_WRITE)),  # noqa: B008
    ) -> CheckpointValidationResponse:
        del principal
        result = store.seal(validation_id, now=datetime.now(UTC))
        response.status_code = _STATUS[result.verdict]
        return CheckpointValidationResponse(
            verdict=result.verdict.value, detail=result.detail, validation=result.record
        )

    @router.get(
        "/v1/processing-jobs/{job_id}/checkpoint-validations",
        response_model=CheckpointValidationListResponse,
    )
    def list_job(
        job_id: str,
        principal: Principal = Depends(require_permission(Permission.SITES_READ)),  # noqa: B008
    ) -> CheckpointValidationListResponse:
        del principal
        return CheckpointValidationListResponse(validations=store.list_for_job(job_id))

    @router.get(
        "/v1/checkpoint-validations/{validation_id}", response_model=CheckpointValidationResponse
    )
    def get(
        validation_id: str,
        principal: Principal = Depends(require_permission(Permission.SITES_READ)),  # noqa: B008
    ) -> CheckpointValidationResponse:
        del principal
        record = store.get(validation_id)
        if record is None:
            raise HTTPException(status_code=404, detail=_NOT_FOUND)
        return CheckpointValidationResponse(verdict=record.status.value, validation=record)

    @router.get(
        "/v1/checkpoint-validations", response_model=PendingCheckpointValidationListResponse
    )
    def pending(
        status: str = Query(default=CheckpointValidationStatus.SEALED.value),
        limit: int = Query(default=50, ge=1, le=MAX_PENDING_LIMIT),
        principal: Principal = Depends(require_permission(Permission.PROCESSING_WORK)),  # noqa: B008
    ) -> PendingCheckpointValidationListResponse:
        del principal
        if status != CheckpointValidationStatus.SEALED.value:
            raise HTTPException(status_code=422, detail="status must be SEALED")
        now = datetime.now(UTC)
        rows: list[PendingCheckpointValidation] = []
        for record in store.list_pending(limit=limit):
            try:
                checkpoint_url = storage.presigned_get(
                    build_checkpoint_object_key(
                        site_id=record.site_id, validation_id=record.validation_id
                    ),
                    ttl=DEFAULT_VIEW_TTL,
                )
                # New records resolve bytes exclusively through the accepted
                # manifest.  ``resolve_artifact`` alone owns the genuine legacy
                # conventional-key adapter.
                resolved_dsm = store._processing_jobs.resolve_artifact(  # noqa: SLF001
                    record.dsm.job_id, record.dsm.artifact_id
                )
                if resolved_dsm is None:
                    raise EvidenceStorageError(
                        "checkpoint DSM has no accepted artifact authority"
                    )
                dsm_url = storage.presigned_get(
                    resolved_dsm.object_key, ttl=DEFAULT_VIEW_TTL
                )
            except EvidenceStorageError:
                logger.warning(
                    "checkpoint validation URL issuance failed: %s", record.validation_id
                )
                continue
            rows.append(
                PendingCheckpointValidation(
                    validation_id=record.validation_id,
                    checkpoint_download_url=checkpoint_url,
                    dsm_download_url=dsm_url,
                    checkpoint_crs=record.declared.crs,
                    checkpoint_vertical_reference=record.declared.vertical_reference.model_dump(
                        by_alias=True, mode="json"
                    ),
                    dsm_crs=record.dsm_crs,
                    dsm_vertical_reference=record.dsm_vertical_reference.model_dump(
                        by_alias=True, mode="json"
                    ),
                    expires_at=expires_at(now, DEFAULT_VIEW_TTL),
                )
            )
        return PendingCheckpointValidationListResponse(validations=rows)

    @router.post(
        "/v1/checkpoint-validations/{validation_id}/observations",
        response_model=CheckpointValidationResponse,
        status_code=201,
    )
    def observe(
        validation_id: str,
        request: CheckpointValidationObservationRequest,
        response: Response,
        principal: Principal = Depends(require_permission(Permission.PROCESSING_WORK)),  # noqa: B008
    ) -> CheckpointValidationResponse:
        now = datetime.now(UTC)
        try:
            observed = CheckpointValidationObserved(
                **request.model_dump(), measured_at=now, measured_by=principal.principal_id
            )
        except ValidationError as exc:
            response.status_code = 422
            return CheckpointValidationResponse(verdict="INVALID_MEASUREMENT", detail=str(exc))
        result = store.observe(validation_id, observed, now=now)
        response.status_code = _STATUS[result.verdict]
        return CheckpointValidationResponse(
            verdict=result.verdict.value, detail=result.detail, validation=result.record
        )

    @router.post(
        "/v1/checkpoint-validations/{validation_id}/verification-failure",
        response_model=CheckpointValidationResponse,
        status_code=422,
    )
    def fail(
        validation_id: str,
        request: CheckpointValidationFailureRequest,
        response: Response,
        principal: Principal = Depends(require_permission(Permission.PROCESSING_WORK)),  # noqa: B008
    ) -> CheckpointValidationResponse:
        del principal
        try:
            result = store.verification_failure(
                validation_id, request.reason, request.detail, now=datetime.now(UTC)
            )
        except ValueError as exc:
            response.status_code = 422
            return CheckpointValidationResponse(verdict="INVALID_MEASUREMENT", detail=str(exc))
        response.status_code = _STATUS[result.verdict]
        return CheckpointValidationResponse(
            verdict=result.verdict.value, detail=result.detail, validation=result.record
        )

    return router


def mount_checkpoint_validations(
    app: FastAPI,
    store: CheckpointValidationStore,
    storage: EvidenceStorage,
    *,
    registration_enabled: bool = False,
) -> None:
    app.state.checkpoint_validation_store = store
    app.include_router(
        build_checkpoint_validations_router(
            store, storage, registration_enabled=registration_enabled
        )
    )


__all__ = [
    "CheckpointValidationRecoveryError",
    "CheckpointValidationStore",
    "CheckpointValidationVerdict",
    "build_checkpoint_object_key",
    "build_checkpoint_validation_id",
    "build_checkpoint_validations_router",
    "mount_checkpoint_validations",
]
