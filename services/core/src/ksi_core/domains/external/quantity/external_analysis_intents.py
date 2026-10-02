"""Durable public analysis intent, independent from AP/NX execution authority.

The facade has one concrete responsibility that AP and NX deliberately do not:
it retains the public Site/WorkArea selector request even when AP blocks before
there is a calculation identity.  Its events make AP→NX hand-off restartable;
they never contain a caller-selected profile, runtime, artifact capability, or
numeric result.
"""

from __future__ import annotations

import hashlib
import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_analysis_api import (
    AnalysisBlockerV1,
    AnalysisObservationSelectorV1,
    CreateAnalysisRequestV1,
)

from ksi_core.foundation.api_base import iso_utc
from ksi_core.foundation.durable_journal import DurableJournal, JournalSealedError

_EVENT_VERSION = 1
_LINK_EVENT_KIND = "external-analysis-intent-calculation-linked"
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _digest(value: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _event_digest(value: dict[str, object]) -> str:
    return _digest({key: item for key, item in value.items() if key != "eventDigest"})


@dataclass(frozen=True, slots=True)
class PublicAnalysisIntent:
    analysis_id: str
    organization_id: str
    site_id: str
    work_area_id: str
    request: CreateAnalysisRequestV1
    pre_admission_blockers: tuple[AnalysisBlockerV1, ...]
    selector_digest: str
    idempotency_digest: str
    created_at: datetime
    calculation_request_id: str | None = None

    @property
    def baseline(self) -> AnalysisObservationSelectorV1:
        """Compatibility access for facade projection; source of truth is request."""
        return self.request.baseline

    @property
    def current(self) -> AnalysisObservationSelectorV1:
        """Compatibility access for facade projection; source of truth is request."""
        return self.request.current


class AnalysisIntentRecoveryError(RuntimeError):
    """A public analysis intent journal could not be replayed safely."""


class AnalysisIntentStore:
    """Append and replay immutable public selector records.

    AP and NX links are deliberately added by later events.  A recoverer can
    therefore inspect one durable intent before deciding whether the matching
    AP assessment or NX calculation needs idempotent continuation.
    """

    def __init__(self, journal: DurableJournal) -> None:
        self._journal = journal
        self._lock = threading.RLock()
        self._by_id: dict[str, PublicAnalysisIntent] = {}
        self._by_idempotency: dict[tuple[str, str], str] = {}
        try:
            for raw in journal.replay():
                self._apply(raw)
        except BaseException as exc:
            journal.close()
            if isinstance(exc, AnalysisIntentRecoveryError):
                raise
            raise AnalysisIntentRecoveryError(str(exc)) from exc

    def close(self) -> None:
        self._journal.close()

    def record_intent(
        self,
        *,
        organization_id: str,
        site_id: str,
        work_area_id: str,
        request: CreateAnalysisRequestV1,
        idempotency_key: str,
        now: datetime,
        pre_admission_blockers: tuple[AnalysisBlockerV1, ...] = (),
    ) -> PublicAnalysisIntent:
        """Return one frozen intent for an exact organization/idempotency scope."""
        if not all(
            value.strip() for value in (organization_id, site_id, work_area_id, idempotency_key)
        ):
            raise ValueError("analysis intent scope and idempotency key are required")
        if now.tzinfo is None or now.utcoffset() != UTC.utcoffset(now):
            raise ValueError("analysis intent time must be UTC")
        selectors = request.model_dump(by_alias=True, mode="json")
        selector_digest = _digest(
            {
                "siteId": site_id,
                "workAreaId": work_area_id,
                "selectors": selectors,
            }
        )
        idempotency_digest = "sha256:" + hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        analysis_id = (
            "analysis-v1-"
            + hashlib.sha256(
                canonical_json_bytes(
                    {
                        "organizationId": organization_id,
                        "idempotencyDigest": idempotency_digest,
                    }
                )
            ).hexdigest()[:32]
        )
        raw: dict[str, object] = {
            "kind": "external-analysis-intent-recorded",
            "version": _EVENT_VERSION,
            "analysisId": analysis_id,
            "organizationId": organization_id,
            "siteId": site_id,
            "workAreaId": work_area_id,
            "selectors": selectors,
            "preAdmissionBlockers": [
                item.model_dump(by_alias=True, mode="json") for item in pre_admission_blockers
            ],
            "selectorDigest": selector_digest,
            "idempotencyDigest": idempotency_digest,
            "createdAt": iso_utc(now),
        }
        raw["eventDigest"] = _event_digest(raw)
        with self._lock:
            existing_id = self._by_idempotency.get((organization_id, idempotency_digest))
            if existing_id is not None:
                existing = self._by_id[existing_id]
                if (
                    existing.site_id != site_id
                    or existing.work_area_id != work_area_id
                    or existing.selector_digest != selector_digest
                ):
                    raise ValueError("idempotency key is already bound to another analysis request")
                return self._public(existing)
            self._validate_event(raw, mutate=False)
            try:
                self._journal.append(raw)
            except JournalSealedError as exc:
                raise RuntimeError("analysis intent journal is unavailable") from exc
            self._apply(raw)
            return self._public(self._by_id[analysis_id])

    def get(self, analysis_id: str, *, organization_id: str) -> PublicAnalysisIntent | None:
        with self._lock:
            record = self._by_id.get(analysis_id)
            if record is None or record.organization_id != organization_id:
                return None
            return self._public(record)

    def get_by_idempotency(
        self, *, organization_id: str, idempotency_key: str
    ) -> PublicAnalysisIntent | None:
        """Read an existing user retry without invoking AP/NX again."""
        digest = "sha256:" + hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        with self._lock:
            analysis_id = self._by_idempotency.get((organization_id, digest))
            record = self._by_id.get(analysis_id) if analysis_id is not None else None
            return self._public(record) if record is not None else None

    def list(self, *, organization_id: str, site_id: str) -> tuple[PublicAnalysisIntent, ...]:
        with self._lock:
            return tuple(
                self._public(record)
                for record in self._by_id.values()
                if record.organization_id == organization_id and record.site_id == site_id
            )

    def list_for_organization(self, *, organization_id: str) -> tuple[PublicAnalysisIntent, ...]:
        """Internal worker discovery projection; it exposes no public capability."""
        with self._lock:
            return tuple(
                self._public(record)
                for record in self._by_id.values()
                if record.organization_id == organization_id
            )

    def link_calculation(
        self,
        *,
        analysis_id: str,
        organization_id: str,
        calculation_request_id: str,
    ) -> PublicAnalysisIntent:
        """Durably connect an intent to the actual NX request selected by dedup.

        NX may return a pre-existing request for the same immutable calculation
        identity.  This one-way link lets a restarted facade project that real
        request rather than assuming its public analysis ID is the NX ID.
        """
        if (
            not analysis_id.strip()
            or not organization_id.strip()
            or not calculation_request_id.strip()
        ):
            raise ValueError("analysis calculation link scope is required")
        with self._lock:
            existing = self._by_id.get(analysis_id)
            if existing is None or existing.organization_id != organization_id:
                raise LookupError("analysis intent is not available")
            if existing.calculation_request_id is not None:
                if existing.calculation_request_id != calculation_request_id:
                    raise ValueError("analysis intent calculation link is already bound")
                return self._public(existing)
            raw: dict[str, object] = {
                "kind": _LINK_EVENT_KIND,
                "version": _EVENT_VERSION,
                "analysisId": analysis_id,
                "organizationId": organization_id,
                "calculationRequestId": calculation_request_id,
            }
            raw["eventDigest"] = _event_digest(raw)
            self._validate_calculation_link(raw)
            try:
                self._journal.append(raw)
            except JournalSealedError as exc:
                raise RuntimeError("analysis intent journal is unavailable") from exc
            self._apply(raw)
            return self._public(self._by_id[analysis_id])

    def _apply(self, raw: object) -> None:
        if isinstance(raw, dict) and raw.get("kind") == _LINK_EVENT_KIND:
            self._validate_calculation_link(raw, mutate=True)
            return
        self._validate_event(raw, mutate=True)

    def _validate_calculation_link(self, raw: object, *, mutate: bool = False) -> None:
        if (
            not isinstance(raw, dict)
            or not isinstance(raw.get("eventDigest"), str)
            or raw.get("eventDigest") != _event_digest(raw)
        ):
            raise AnalysisIntentRecoveryError("analysis calculation link digest is invalid")
        expected = {
            "kind",
            "version",
            "analysisId",
            "organizationId",
            "calculationRequestId",
            "eventDigest",
        }
        if (
            set(raw) != expected
            or raw.get("kind") != _LINK_EVENT_KIND
            or type(raw.get("version")) is not int
            or raw.get("version") != _EVENT_VERSION
        ):
            raise AnalysisIntentRecoveryError("analysis calculation link shape is invalid")
        analysis_id = raw.get("analysisId")
        organization_id = raw.get("organizationId")
        calculation_request_id = raw.get("calculationRequestId")
        if not all(
            isinstance(value, str) and value.strip()
            for value in (analysis_id, organization_id, calculation_request_id)
        ):
            raise AnalysisIntentRecoveryError("analysis calculation link values are invalid")
        assert isinstance(analysis_id, str)
        assert isinstance(organization_id, str)
        assert isinstance(calculation_request_id, str)
        if not mutate:
            return
        existing = self._by_id.get(analysis_id)
        if existing is None or existing.organization_id != organization_id:
            raise AnalysisIntentRecoveryError("analysis calculation link has no scoped intent")
        if (
            existing.calculation_request_id is not None
            and existing.calculation_request_id != calculation_request_id
        ):
            raise AnalysisIntentRecoveryError("analysis calculation link is rebound")
        self._by_id[analysis_id] = replace(existing, calculation_request_id=calculation_request_id)

    def _validate_event(self, raw: object, *, mutate: bool) -> None:
        if (
            not isinstance(raw, dict)
            or not isinstance(raw.get("eventDigest"), str)
            or raw.get("eventDigest") != _event_digest(raw)
        ):
            raise AnalysisIntentRecoveryError("analysis intent event digest is invalid")
        expected = {
            "kind",
            "version",
            "analysisId",
            "organizationId",
            "siteId",
            "workAreaId",
            "selectors",
            "selectorDigest",
            "idempotencyDigest",
            "createdAt",
            "eventDigest",
        }
        # The journal had one development-only predecessor before typed
        # pre-admission blockers were added.  Preserve its replay rather than
        # treating an additive public status fact as a data-loss migration.
        expected_with_blockers = expected | {"preAdmissionBlockers"}
        if (
            set(raw) != expected
            and set(raw) != expected_with_blockers
            or raw.get("kind") != "external-analysis-intent-recorded"
            or type(raw.get("version")) is not int
            or raw.get("version") != _EVENT_VERSION
        ):
            raise AnalysisIntentRecoveryError("analysis intent event shape is invalid")
        try:
            created_at_raw = raw["createdAt"]
            if not isinstance(created_at_raw, str):
                raise ValueError("createdAt must be a string")
            created_at = datetime.fromisoformat(created_at_raw.replace("Z", "+00:00"))
            if created_at.tzinfo is None or created_at.utcoffset() != UTC.utcoffset(created_at):
                raise ValueError("createdAt must be UTC")
            selectors_raw = raw["selectors"]
            if not isinstance(selectors_raw, dict):
                raise ValueError("selectors must be an object")
            selectors = CreateAnalysisRequestV1.model_validate(selectors_raw)
            raw_blockers = raw.get("preAdmissionBlockers", [])
            if not isinstance(raw_blockers, list):
                raise ValueError("preAdmissionBlockers must be a list")
            blockers = tuple(AnalysisBlockerV1.model_validate(item) for item in raw_blockers)
            analysis_id = raw["analysisId"]
            organization_id = raw["organizationId"]
            site_id = raw["siteId"]
            work_area_id = raw["workAreaId"]
            selector_digest = raw["selectorDigest"]
            idempotency_digest = raw["idempotencyDigest"]
            if not all(
                isinstance(value, str) and value.strip()
                for value in (analysis_id, organization_id, site_id, work_area_id)
            ):
                raise ValueError("analysis identity and scope must be nonblank strings")
            if not isinstance(selector_digest, str) or not _DIGEST_RE.fullmatch(selector_digest):
                raise ValueError("selector digest is invalid")
            if not isinstance(idempotency_digest, str) or not _DIGEST_RE.fullmatch(
                idempotency_digest
            ):
                raise ValueError("idempotency digest is invalid")
            expected_selector_digest = _digest(
                {
                    "siteId": site_id,
                    "workAreaId": work_area_id,
                    "selectors": selectors.model_dump(by_alias=True, mode="json"),
                }
            )
            if selector_digest != expected_selector_digest:
                raise ValueError("selector digest mismatch")
        except (TypeError, ValueError, KeyError) as exc:
            raise AnalysisIntentRecoveryError(str(exc)) from exc
        if not mutate:
            return
        record = PublicAnalysisIntent(
            analysis_id=analysis_id,
            organization_id=organization_id,
            site_id=site_id,
            work_area_id=work_area_id,
            # Retain a freshly validated value from primitive journal data.
            # ``CreateAnalysisRequestV1`` is intentionally mutable at the
            # public boundary, so retaining an input/return object would let a
            # caller rewrite a future idempotent replay in memory.
            request=CreateAnalysisRequestV1.model_validate(
                selectors.model_dump(by_alias=True, mode="json")
            ),
            pre_admission_blockers=tuple(
                AnalysisBlockerV1.model_validate(item.model_dump(by_alias=True, mode="json"))
                for item in blockers
            ),
            selector_digest=selector_digest,
            idempotency_digest=idempotency_digest,
            created_at=created_at,
            calculation_request_id=None,
        )
        existing = self._by_id.get(analysis_id)
        if existing is not None and existing != record:
            raise AnalysisIntentRecoveryError("analysis intent ID is rebound")
        existing_id = self._by_idempotency.get((organization_id, idempotency_digest))
        if existing_id is not None and existing_id != analysis_id:
            raise AnalysisIntentRecoveryError("analysis idempotency digest is rebound")
        self._by_id[analysis_id] = record
        self._by_idempotency[(organization_id, idempotency_digest)] = analysis_id

    @staticmethod
    def _public(record: PublicAnalysisIntent) -> PublicAnalysisIntent:
        return PublicAnalysisIntent(
            analysis_id=record.analysis_id,
            organization_id=record.organization_id,
            site_id=record.site_id,
            work_area_id=record.work_area_id,
            request=record.request.model_copy(deep=True),
            pre_admission_blockers=tuple(
                item.model_copy(deep=True) for item in record.pre_admission_blockers
            ),
            selector_digest=record.selector_digest,
            idempotency_digest=record.idempotency_digest,
            created_at=record.created_at,
            calculation_request_id=record.calculation_request_id,
        )


__all__ = ["AnalysisIntentRecoveryError", "AnalysisIntentStore", "PublicAnalysisIntent"]
