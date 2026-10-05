"""Additive durable human-use review for V2 AP/NX results.

Review history re-resolves its source from independent intent/AP/NX journals.
Current checks use the existing assessment witness; no policy, number or V1
report is invented here. This is not an official issuance or flight gate.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from threading import RLock
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_analysis_review import (
    AnalysisReviewEvaluationV2,
    AnalysisReviewListV2,
    AnalysisReviewReceiptV2,
    AnalysisReviewTargetV2,
    CreateAnalysisReviewV2,
)

from ksi_core.foundation.durable_journal import DurableJournal, JournalSealedError
from ksi_core.identity.auth import Permission, Principal, PrincipalKind, require_permission


def _digest(raw: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(raw)).hexdigest()


class AnalysisReviewRecoveryError(RuntimeError):
    """Review history lacks its exact independently retained V2 source."""


class AnalysisReviewConflict(ValueError):
    """Submitted target or idempotent content no longer matches."""


class AnalysisReviewSource:
    def __init__(self, *, facade: Any, intents: Any, assessments: Any, calculations: Any) -> None:
        self.facade = facade
        self.intents = intents
        self.assessments = assessments
        self.calculations = calculations
        self.coordinator = assessments.coordinator

    def intent(self, principal: Principal, site_id: str, analysis_id: str) -> Any:
        intent = self.intents.get(analysis_id, organization_id=principal.organization_id)
        if (
            intent is None
            or intent.site_id != site_id
            or not self.facade._intent_is_in_scope(principal, intent)
        ):
            raise LookupError("ANALYSIS_RESOURCE_NOT_FOUND")
        return intent

    @staticmethod
    def target(admission: Any, report: Any) -> AnalysisReviewTargetV2:
        try:
            return AnalysisReviewSource._target(admission, report)
        except (TypeError, ValueError) as exc:
            raise AnalysisReviewConflict("ANALYSIS_REVIEW_RESULT_UNAVAILABLE") from exc

    @staticmethod
    def _target(admission: Any, report: Any) -> AnalysisReviewTargetV2:
        if len(admission.evaluation_revisions) != 2:
            raise ValueError("review requires exactly two evaluation revisions")

        def evaluation(item: Any) -> AnalysisReviewEvaluationV2:
            return AnalysisReviewEvaluationV2(
                epoch=item.epoch,
                evaluation_id=item.evaluation_id,
                revision=item.revision,
                evaluation_digest=item.evaluation_digest,
            )

        return AnalysisReviewTargetV2(
            result_id=report.report_id,
            result_revision=1,
            report_digest=report.report_digest,
            numeric_result_identity_digest=report.numeric_result_identity_digest,
            calculation_identity_digest=admission.calculation_identity_digest,
            admission_digest=admission.admission_digest,
            evaluations=(
                evaluation(admission.evaluation_revisions[0]),
                evaluation(admission.evaluation_revisions[1]),
            ),
        )

    def current(
        self, principal: Principal, site_id: str, analysis_id: str, now: datetime
    ) -> tuple[Any, Any, Any]:
        intent = self.intent(principal, site_id, analysis_id)
        snapshot = self.facade._read_v2_snapshot(
            principal=principal, site_id=site_id, analysis_id=analysis_id, now=now
        )
        if snapshot is None or snapshot[0].result is None:
            raise AnalysisReviewConflict("ANALYSIS_REVIEW_RESULT_UNAVAILABLE")
        assessment = self.assessments.get_history(
            analysis_id, organization_id=principal.organization_id
        )
        record = self.calculations.get_history(
            intent.calculation_request_id or analysis_id, organization_id=principal.organization_id
        )
        if assessment is None or record is None or record.report is None:
            raise AnalysisReviewConflict("ANALYSIS_REVIEW_RESULT_UNAVAILABLE")
        target = self.target(assessment.admission, record.report)
        if target.report_digest != snapshot[0].result.report_digest:
            raise AnalysisReviewConflict("ANALYSIS_REVIEW_TARGET_CHANGED")
        witness = self.assessments.prepare_execution_witness(
            calculation_identity_digest=target.calculation_identity_digest,
            organization_id=principal.organization_id,
            now=now,
            expected_admission=assessment.admission,
        )
        return intent, target, witness

    def remains_current(
        self, principal: Principal, intent: Any, witness: Any, now: datetime
    ) -> bool:
        return bool(
            self.facade._intent_is_in_scope(principal, intent)
            and self.assessments.execution_witness_is_current(witness=witness, now=now) is not None
        )

    def historical(self, receipt: AnalysisReviewReceiptV2) -> bool:
        intent = self.intents.get(receipt.analysis_id, organization_id=receipt.organization_id)
        if (
            intent is None
            or intent.site_id != receipt.site_id
            or intent.work_area_id != receipt.work_area_id
        ):
            return False
        assessment = self.assessments.get_history(
            receipt.analysis_id, organization_id=receipt.organization_id
        )
        record = self.calculations.get_history(
            intent.calculation_request_id or receipt.analysis_id,
            organization_id=receipt.organization_id,
        )
        return bool(
            assessment is not None
            and record is not None
            and record.report is not None
            and record.calculation_identity_digest == receipt.target.calculation_identity_digest
            and assessment.admission.assessed_at <= receipt.reviewed_at
            and record.report.computed_at <= receipt.reviewed_at
            and self.target(assessment.admission, record.report) == receipt.target
        )


class AnalysisReviewStore:
    def __init__(self, journal: DurableJournal, *, source: AnalysisReviewSource) -> None:
        self.journal, self.source = journal, source
        self._lock = RLock()
        self._receipts: dict[str, AnalysisReviewReceiptV2] = {}
        self._idempotency: dict[tuple[str, str, str, str], tuple[str, str]] = {}
        try:
            for event in journal.replay():
                self._apply(event)
        except BaseException as exc:
            journal.close()
            raise AnalysisReviewRecoveryError(str(exc)) from exc

    def _apply(self, event: Any) -> None:
        if not isinstance(event, dict) or set(event) != {
            "kind",
            "version",
            "receipt",
            "idempotencyDigest",
            "requestDigest",
            "eventDigest",
        }:
            raise AnalysisReviewRecoveryError("review event shape is invalid")
        if (
            event["kind"] != "external-analysis-reviewed-v2"
            or type(event["version"]) is not int
            or event["version"] != 1
        ):
            raise AnalysisReviewRecoveryError("review event kind/version is invalid")
        if event["eventDigest"] != _digest(
            {key: value for key, value in event.items() if key != "eventDigest"}
        ):
            raise AnalysisReviewRecoveryError("review event digest is invalid")
        receipt = AnalysisReviewReceiptV2.model_validate(event["receipt"])
        if receipt.receipt_digest is None or not self.source.historical(receipt):
            raise AnalysisReviewRecoveryError("review source binding is invalid")
        request = CreateAnalysisReviewV2(
            target=receipt.target, decision=receipt.decision, comment=receipt.comment
        )
        if event["requestDigest"] != _digest(request.model_dump(by_alias=True, mode="json")):
            raise AnalysisReviewRecoveryError("review request digest is invalid")
        key = (
            receipt.organization_id,
            receipt.reviewer_id,
            receipt.analysis_id,
            event["idempotencyDigest"],
        )
        if not isinstance(key[-1], str) or len(key[-1]) != 71 or not key[-1].startswith("sha256:"):
            raise AnalysisReviewRecoveryError("review idempotency digest is invalid")
        expected_ref = "arv2-" + _digest({"scope": list(key)})[7:]
        if (
            receipt.review_ref != expected_ref
            or key in self._idempotency
            or expected_ref in self._receipts
        ):
            raise AnalysisReviewRecoveryError("review identity is invalid or duplicated")
        self._receipts[expected_ref] = receipt
        self._idempotency[key] = (event["requestDigest"], expected_ref)

    def create(
        self,
        *,
        principal: Principal,
        site_id: str,
        analysis_id: str,
        request: CreateAnalysisReviewV2,
        idempotency_key: str,
        now: datetime,
    ) -> AnalysisReviewReceiptV2:
        if principal.kind is not PrincipalKind.OPERATOR:
            raise PermissionError("human review requires an operator")
        self.source.intent(principal, site_id, analysis_id)
        if not idempotency_key.strip() or len(idempotency_key) > 255:
            raise ValueError("IDEMPOTENCY_KEY_REQUIRED")
        digest = "sha256:" + hashlib.sha256(idempotency_key.encode()).hexdigest()
        key = (principal.organization_id, principal.principal_id, analysis_id, digest)
        fingerprint = _digest(request.model_dump(by_alias=True, mode="json"))
        with self._lock:
            previous = self._idempotency.get(key)
            if previous is not None:
                if previous[0] != fingerprint:
                    raise AnalysisReviewConflict("ANALYSIS_REVIEW_IDEMPOTENCY_CONFLICT")
                return self._receipts[previous[1]]
        intent, target, witness = self.source.current(principal, site_id, analysis_id, now)
        with self.source.coordinator.guarded_read(), self._lock:
            previous = self._idempotency.get(key)
            if previous is not None:
                if previous[0] != fingerprint:
                    raise AnalysisReviewConflict("ANALYSIS_REVIEW_IDEMPOTENCY_CONFLICT")
                return self._receipts[previous[1]]
            if target != request.target or not self.source.remains_current(
                principal, intent, witness, now
            ):
                raise AnalysisReviewConflict("ANALYSIS_REVIEW_TARGET_CHANGED")
            receipt = AnalysisReviewReceiptV2(
                review_ref="arv2-" + _digest({"scope": list(key)})[7:],
                organization_id=principal.organization_id,
                site_id=site_id,
                work_area_id=intent.work_area_id,
                analysis_id=analysis_id,
                reviewer_id=principal.principal_id,
                target=target,
                decision=request.decision,
                comment=request.comment,
                reviewed_at=now,
            ).sealed()
            event = {
                "kind": "external-analysis-reviewed-v2",
                "version": 1,
                "receipt": receipt.model_dump(by_alias=True, mode="json"),
                "idempotencyDigest": digest,
                "requestDigest": fingerprint,
            }
            event["eventDigest"] = _digest(event)
            self.journal.append(event)
            self._apply(event)
            return receipt

    def list(
        self,
        principal: Principal,
        site_id: str,
        analysis_id: str,
        *,
        limit: int = 50,
        cursor: str | None = None,
    ) -> AnalysisReviewListV2:
        self.source.intent(principal, site_id, analysis_id)
        with self._lock:
            items = [
                item
                for item in self._receipts.values()
                if item.organization_id == principal.organization_id
                and item.analysis_id == analysis_id
            ]
            start = 0
            if cursor is not None:
                indexes = [index for index, item in enumerate(items) if item.review_ref == cursor]
                if not indexes:
                    raise AnalysisReviewConflict("ANALYSIS_REVIEW_CURSOR_INVALID")
                start = indexes[0] + 1
            page = items[start : start + limit]
            return AnalysisReviewListV2(
                items=tuple(page),
                next_cursor=page[-1].review_ref if page and start + limit < len(items) else None,
            )


def build_analysis_review_router(store: AnalysisReviewStore) -> APIRouter:
    router = APIRouter(tags=["External Analysis V2 review"])
    base = "/v2/sites/{site_id}/analyses/{analysis_id}"
    read, write = (
        require_permission(Permission.SITES_READ),
        require_permission(Permission.SITES_WRITE),
    )

    def call(operation: Any) -> Any:
        try:
            return operation()
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="ANALYSIS_RESOURCE_NOT_FOUND") from exc
        except AnalysisReviewConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="HUMAN_REVIEW_PERMISSION_REQUIRED") from exc
        except JournalSealedError as exc:
            raise HTTPException(
                status_code=503, detail="ANALYSIS_REVIEW_JOURNAL_UNAVAILABLE"
            ) from exc

    @router.get(base + "/review-target", response_model=AnalysisReviewTargetV2)
    def target(site_id: str, analysis_id: str, principal: Principal = Depends(read)) -> Any:  # noqa: B008
        return call(
            lambda: store.source.current(principal, site_id, analysis_id, datetime.now(UTC))[1]
        )

    @router.get(base + "/reviews", response_model=AnalysisReviewListV2)
    def reviews(
        site_id: str,
        analysis_id: str,
        limit: int = Query(default=50, ge=1, le=50),
        cursor: str | None = Query(default=None, max_length=80),
        principal: Principal = Depends(read),  # noqa: B008
    ) -> Any:
        return call(lambda: store.list(principal, site_id, analysis_id, limit=limit, cursor=cursor))

    @router.post(base + "/reviews", response_model=AnalysisReviewReceiptV2, status_code=201)
    def review(
        site_id: str,
        analysis_id: str,
        request: CreateAnalysisReviewV2,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=255),
        principal: Principal = Depends(write),  # noqa: B008
    ) -> Any:
        if idempotency_key is None or not idempotency_key.strip():
            raise HTTPException(status_code=400, detail="IDEMPOTENCY_KEY_REQUIRED")
        return call(
            lambda: store.create(
                principal=principal,
                site_id=site_id,
                analysis_id=analysis_id,
                request=request,
                idempotency_key=idempotency_key,
                now=datetime.now(UTC),
            )
        )

    return router
