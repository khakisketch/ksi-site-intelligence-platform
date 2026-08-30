"""현장 보고서 내보내기 감사 원장 (ADR-KSI-008 §1, INV-053/060).

Dashboard의 PDF는 브라우저 인쇄이고 CSV도 브라우저가 이미 받은 진척 값을
문자열화한 것이다. 따라서 Core는 존재하지 않는 파일 bytes를 보관하거나 ``서버가
PDF를 만들었다``고 주장하지 않는다. 대신 **누가·언제·어느 조직/현장에서·Core가
검증 가능한 어느 두 설계 대비 결과를 기준으로** PDF/CSV 내보내기를 요청했는지를
append-only journal에 남긴다.

클라이언트가 보내는 것은 export ID, 형식, 기준/최신 design-conformance ID뿐이다.
조직은 인증 Principal에서만, 현장은 경로에서만 얻는다. 설계면 revision·정규화
계보·처리 profile·source lineage·Core 재해싱 diff-raster digest는 요청 몸체가
아니라 기존 immutable 원장에서 다시 읽어 snapshot으로 만든다. 이 경계가 없으면
화면에 보지 않은 다른 수치나 타 조직 report ID를 ``내보냈다``고 감사 기록에 섞을
수 있다.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal, Protocol

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from ksi_mission_contracts.signing import canonical_payload_bytes, sha256_digest
from pydantic import Field

from ksi_core.api_base import (
    JOURNAL_APPEND_FAILED_DETAIL,
    JOURNAL_SEALED_DETAIL,
    CamelModel,
    iso_utc,
)
from ksi_core.auth import Permission, Principal, require_permission
from ksi_core.design_progress import derive_progress
from ksi_core.durable_journal import DurableJournal, JournalSealedError
from ksi_core.identifiers import is_path_safe_identifier

if TYPE_CHECKING:
    from ksi_core.design_conformance_reports import RecordedDesignConformance
    from ksi_core.design_conformance_requests import DesignConformanceRequestRecord
    from ksi_core.sites import SiteStore


DEFAULT_HISTORY_LIMIT = 50


class ReportExportCatalog(Protocol):
    """Narrow immutable-report lookup boundary required by the audit ledger."""

    def request_of(
        self, design_conformance_id: str
    ) -> DesignConformanceRequestRecord | None: ...

    def get(
        self, mission_id: str, design_conformance_id: str
    ) -> RecordedDesignConformance | None: ...


class ReportExportFormat(StrEnum):
    """The only two browser export operations currently offered by the Console."""

    PDF = "PDF"
    CSV = "CSV"


class ReportExportVerdict(StrEnum):
    RECORDED = "RECORDED"
    ALREADY_RECORDED = "ALREADY_RECORDED"
    UNKNOWN_SITE = "UNKNOWN_SITE"
    UNKNOWN_REPORT = "UNKNOWN_REPORT"
    REPORT_SITE_MISMATCH = "REPORT_SITE_MISMATCH"
    SNAPSHOT_NOT_COMPARABLE = "SNAPSHOT_NOT_COMPARABLE"
    DUPLICATE_EXPORT_ID = "DUPLICATE_EXPORT_ID"
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"


_STATUS: dict[ReportExportVerdict, int] = {
    ReportExportVerdict.RECORDED: 201,
    ReportExportVerdict.ALREADY_RECORDED: 200,
    ReportExportVerdict.UNKNOWN_SITE: 404,
    ReportExportVerdict.UNKNOWN_REPORT: 404,
    ReportExportVerdict.REPORT_SITE_MISMATCH: 404,
    ReportExportVerdict.SNAPSHOT_NOT_COMPARABLE: 422,
    ReportExportVerdict.DUPLICATE_EXPORT_ID: 409,
    ReportExportVerdict.STORE_UNAVAILABLE: 503,
}


class ReportExportRecoveryError(RuntimeError):
    """A report-export journal cannot be replayed into a trustworthy projection."""


class ReportExportCreateRequest(CamelModel):
    """Client input deliberately contains no organization, report values, or file bytes."""

    export_id: str = Field(min_length=1, max_length=128)
    export_format: ReportExportFormat
    baseline_design_conformance_id: str = Field(min_length=1, max_length=128)
    latest_design_conformance_id: str = Field(min_length=1, max_length=128)


class ReportExportSource(CamelModel):
    """One immutable Core-recorded result that the browser report was based on."""

    design_conformance_id: str
    #: Canonical digest of the complete immutable DesignConformanceReport, not
    #: merely its diff-raster reference. This binds zone values, policy, CRS,
    #: vertical reference and computed-at timestamp into the export audit.
    report_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    mission_id: str
    request_id: str
    computed_at: datetime
    current_job_id: str
    current_artifact_id: str
    diff_raster_id: str
    diff_raster_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    core_recomputed_diff_raster_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    processing_profile_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    source_bundle_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class ReportExportSnapshot(CamelModel):
    """Core-derived report identity; it is not a representation of browser file bytes."""

    schema_version: Literal["1.0"] = "1.0"
    site_id: str
    design_surface_id: str
    design_surface_revision: str
    design_surface_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    design_normalization_profile: str
    design_normalization_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    baseline: ReportExportSource
    latest: ReportExportSource


class ReportExportCreateResponse(CamelModel):
    verdict: str
    export_id: str | None = None
    recorded_at: datetime | None = None
    snapshot_digest: str | None = None
    #: Explicitly prevents clients from interpreting the audit entry as a server-generated PDF/CSV.
    content_produced_by_server: bool = False
    detail: str | None = None


class ReportExportEntry(CamelModel):
    export_id: str
    export_format: ReportExportFormat
    actor: str
    recorded_at: datetime
    snapshot: ReportExportSnapshot
    snapshot_digest: str
    content_produced_by_server: bool = False


class ReportExportListView(CamelModel):
    site_id: str
    export_count: int
    exports: list[ReportExportEntry]


@dataclass(frozen=True, slots=True)
class RecordedReportExport:
    organization_id: str
    site_id: str
    export_id: str
    export_format: ReportExportFormat
    actor: str
    recorded_at: datetime
    snapshot: ReportExportSnapshot
    snapshot_digest: str


@dataclass(frozen=True, slots=True)
class ReportExportResult:
    verdict: ReportExportVerdict
    record: RecordedReportExport | None = None
    detail: str | None = None


def _parse_aware_utc(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise ReportExportRecoveryError(f"재생: {field_name} 이 문자열이 아니다")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ReportExportRecoveryError(f"재생: {field_name} 이 ISO UTC 시각이 아니다") from exc
    if parsed.tzinfo is None:
        raise ReportExportRecoveryError(f"재생: {field_name} 이 tz-aware 가 아니다")
    return parsed.astimezone(UTC)


def _snapshot_digest(snapshot: ReportExportSnapshot) -> str:
    return sha256_digest(canonical_payload_bytes(snapshot.model_dump(by_alias=True, mode="json")))


def _is_valid_actor(value: object) -> bool:
    """Match the auth boundary: principal IDs need UTF-8/nonblank, not path safety.

    OIDC ``sub`` values and human-facing identifiers can legally be e-mail-like
    or Unicode. They are audit values, never object keys or URL path segments.
    """

    if not isinstance(value, str) or not value.strip():
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


class ReportExportStore:
    """Organization/site-scoped immutable audit ledger for browser report exports.

    The report data itself continues to live in design-conformance records. This
    store owns only the export audit fact and re-derives its snapshot from those
    records every time (live and replay), so a manually edited journal cannot
    assert a different report revision or digest.
    """

    def __init__(
        self,
        journal: DurableJournal,
        *,
        site_store: SiteStore,
        design_conformance_store: ReportExportCatalog,
    ) -> None:
        self._journal = journal
        self._site_store = site_store
        self._design_conformance_store = design_conformance_store
        self._lock = threading.Lock()
        self._by_site: dict[tuple[str, str], list[RecordedReportExport]] = {}
        # Idempotency belongs to the site-scoped endpoint.  The same caller may
        # legitimately reuse an action key at another site; retries for this
        # site must still resolve to exactly one immutable record.
        self._by_id: dict[tuple[str, str, str], RecordedReportExport] = {}
        try:
            self._replay(journal)
        except BaseException:
            journal.close()
            raise

    @property
    def sealed_reason(self) -> str | None:
        return self._journal.sealed_reason

    def _resolve_report(
        self, design_conformance_id: str
    ) -> tuple[DesignConformanceRequestRecord, RecordedDesignConformance] | None:
        request = self._design_conformance_store.request_of(design_conformance_id)
        if request is None:
            return None
        entry = self._design_conformance_store.get(request.mission_id, design_conformance_id)
        if entry is None:
            return None
        return request, entry

    def _source(
        self,
        request: DesignConformanceRequestRecord,
        entry: RecordedDesignConformance,
    ) -> ReportExportSource | None:
        # New reports must hold all civil compatibility anchors. Legacy reports remain
        # readable but cannot produce a newly audited quantitative export (INV-053).
        if request.processing_profile_digest is None or request.source_bundle_digest is None:
            return None
        report = entry.report
        if entry.core_recomputed_digest != report.diff_raster.digest:
            return None
        return ReportExportSource(
            design_conformance_id=report.design_conformance_id,
            report_digest=sha256_digest(
                canonical_payload_bytes(report.model_dump(by_alias=True, mode="json"))
            ),
            mission_id=request.mission_id,
            request_id=request.request_id,
            computed_at=report.computed_at,
            current_job_id=report.current.job_id,
            current_artifact_id=report.current.artifact_id,
            diff_raster_id=report.diff_raster.diff_raster_id,
            diff_raster_digest=report.diff_raster.digest,
            core_recomputed_diff_raster_digest=entry.core_recomputed_digest,
            processing_profile_digest=request.processing_profile_digest,
            source_bundle_digest=request.source_bundle_digest,
        )

    def _resolve_snapshot(
        self,
        *,
        organization_id: str,
        site_id: str,
        baseline_design_conformance_id: str,
        latest_design_conformance_id: str,
    ) -> tuple[ReportExportVerdict, ReportExportSnapshot | None, str | None]:
        if self._site_store.get_scoped(site_id, organization_id) is None:
            return ReportExportVerdict.UNKNOWN_SITE, None, "해당 조직의 현장을 찾을 수 없다"

        baseline_pair = self._resolve_report(baseline_design_conformance_id)
        latest_pair = self._resolve_report(latest_design_conformance_id)
        if baseline_pair is None or latest_pair is None:
            return (
                ReportExportVerdict.UNKNOWN_REPORT,
                None,
                "Core에 기록된 설계 대비 리포트를 찾을 수 없다",
            )
        baseline_request, baseline_entry = baseline_pair
        latest_request, latest_entry = latest_pair

        # The request records are the authoritative site binding. Never accept a
        # client-provided site or use a global report ID without this check.
        if baseline_request.site_id != site_id or latest_request.site_id != site_id:
            return (
                ReportExportVerdict.REPORT_SITE_MISMATCH,
                None,
                "선택한 설계 대비 리포트가 경로의 현장에 속하지 않는다",
            )

        baseline_source = self._source(baseline_request, baseline_entry)
        latest_source = self._source(latest_request, latest_entry)
        if baseline_source is None or latest_source is None:
            return (
                ReportExportVerdict.SNAPSHOT_NOT_COMPARABLE,
                None,
                "처리 profile·원본 계보 또는 Core 확인 digest가 없는 과거 리포트는 "
                "새 내보내기 감사 기준으로 쓸 수 없다",
            )

        # This is the same numerical comparability rule the report page uses; a
        # direct caller cannot record an export for two reports that the UI would
        # correctly refuse to render as progress.
        derived = derive_progress(
            baseline_entry.report,
            latest_entry.report,
            site_id=site_id,
        )
        if derived.progress is None:
            return ReportExportVerdict.SNAPSHOT_NOT_COMPARABLE, None, derived.detail

        anchors_match = (
            baseline_request.design_surface_id == latest_request.design_surface_id
            and baseline_request.design_surface_sha256 == latest_request.design_surface_sha256
            and baseline_request.design_surface_revision is not None
            and baseline_request.design_surface_revision == latest_request.design_surface_revision
            and baseline_request.design_normalization_profile is not None
            and baseline_request.design_normalization_profile
            == latest_request.design_normalization_profile
            and baseline_request.design_normalization_digest is not None
            and baseline_request.design_normalization_digest
            == latest_request.design_normalization_digest
            and baseline_source.processing_profile_digest == latest_source.processing_profile_digest
        )
        if not anchors_match:
            return (
                ReportExportVerdict.SNAPSHOT_NOT_COMPARABLE,
                None,
                "설계 revision·정규화·처리 profile 중 하나가 미상 또는 불일치해 "
                "감사 가능한 정량 보고서 기준이 아니다",
            )

        # ``anchors_match`` above is the runtime gate; these assertions only
        # narrow optional historical fields for the typed immutable snapshot.
        assert baseline_request.design_surface_revision is not None  # noqa: S101
        assert baseline_request.design_normalization_profile is not None  # noqa: S101
        assert baseline_request.design_normalization_digest is not None  # noqa: S101

        return (
            ReportExportVerdict.RECORDED,
            ReportExportSnapshot(
                site_id=site_id,
                design_surface_id=baseline_request.design_surface_id,
                design_surface_revision=baseline_request.design_surface_revision,
                design_surface_sha256=baseline_request.design_surface_sha256,
                design_normalization_profile=baseline_request.design_normalization_profile,
                design_normalization_digest=baseline_request.design_normalization_digest,
                baseline=baseline_source,
                latest=latest_source,
            ),
            None,
        )

    def _project(self, record: RecordedReportExport) -> None:
        key = (record.organization_id, record.site_id, record.export_id)
        if key in self._by_id:
            raise ReportExportRecoveryError(
                "재생: 같은 조직에서 exportId가 중복됐다: "
                f"{record.organization_id}/{record.export_id}"
            )
        self._by_id[key] = record
        self._by_site.setdefault((record.organization_id, record.site_id), []).append(record)

    def _replay(self, journal: DurableJournal) -> None:
        try:
            for raw in journal.replay():
                if raw.get("kind") != "report-export-recorded":
                    raise ReportExportRecoveryError(
                        f"알 수 없는 report-export journal kind: {raw.get('kind')!r}"
                    )
                organization_id = raw["organizationId"]
                site_id = raw["siteId"]
                export_id = raw["exportId"]
                actor = raw["actor"]
                if not all(
                    isinstance(value, str) and is_path_safe_identifier(value)
                    for value in (organization_id, site_id, export_id)
                ) or not _is_valid_actor(actor):
                    raise ReportExportRecoveryError(
                        "재생: organization/site/export/actor 식별자가 유효하지 않다"
                    )
                snapshot = ReportExportSnapshot.model_validate(raw["snapshot"])
                snapshot_digest = raw["snapshotDigest"]
                if snapshot.site_id != site_id or snapshot_digest != _snapshot_digest(snapshot):
                    raise ReportExportRecoveryError(
                        "재생: report export snapshot 또는 digest가 원장과 다르다"
                    )
                verdict, resolved, detail = self._resolve_snapshot(
                    organization_id=organization_id,
                    site_id=site_id,
                    baseline_design_conformance_id=snapshot.baseline.design_conformance_id,
                    latest_design_conformance_id=snapshot.latest.design_conformance_id,
                )
                if verdict is not ReportExportVerdict.RECORDED or resolved != snapshot:
                    raise ReportExportRecoveryError(
                        "재생: Core 원장과 다시 대조할 수 없는 report export "
                        f"({verdict.value}: {detail})"
                    )
                self._project(
                    RecordedReportExport(
                        organization_id=organization_id,
                        site_id=site_id,
                        export_id=export_id,
                        export_format=ReportExportFormat(raw["exportFormat"]),
                        actor=actor,
                        recorded_at=_parse_aware_utc(raw["ts"], field_name="ts"),
                        snapshot=snapshot,
                        snapshot_digest=snapshot_digest,
                    )
                )
        except (KeyError, TypeError, ValueError) as exc:
            raise ReportExportRecoveryError(f"report-export journal 재생 실패: {exc}") from exc

    def record(
        self,
        request: ReportExportCreateRequest,
        *,
        organization_id: str,
        site_id: str,
        actor: str,
        now: datetime,
    ) -> ReportExportResult:
        if now.tzinfo is None:
            raise ValueError("now는 tz-aware 시각이어야 한다")
        if not all(is_path_safe_identifier(value) for value in (organization_id, site_id)):
            raise ValueError("organizationId·siteId는 경로-안전 비공백 식별자여야 한다")
        if not _is_valid_actor(actor):
            raise ValueError("actor는 UTF-8 비공백 Principal 식별자여야 한다")
        if not is_path_safe_identifier(request.export_id):
            return ReportExportResult(
                ReportExportVerdict.SNAPSHOT_NOT_COMPARABLE,
                detail="exportId는 경로-안전 비공백 식별자여야 한다",
            )
        with self._lock:
            if self._journal.sealed_reason is not None:
                return ReportExportResult(
                    ReportExportVerdict.STORE_UNAVAILABLE, detail=JOURNAL_SEALED_DETAIL
                )
            verdict, snapshot, detail = self._resolve_snapshot(
                organization_id=organization_id,
                site_id=site_id,
                baseline_design_conformance_id=request.baseline_design_conformance_id,
                latest_design_conformance_id=request.latest_design_conformance_id,
            )
            if verdict is not ReportExportVerdict.RECORDED:
                return ReportExportResult(verdict, detail=detail)
            assert snapshot is not None  # noqa: S101 -- verdict postcondition
            digest = _snapshot_digest(snapshot)
            existing = self._by_id.get((organization_id, site_id, request.export_id))
            if existing is not None:
                if (
                    existing.export_format is request.export_format
                    and existing.actor == actor
                    and existing.snapshot_digest == digest
                ):
                    return ReportExportResult(ReportExportVerdict.ALREADY_RECORDED, existing)
                return ReportExportResult(
                    ReportExportVerdict.DUPLICATE_EXPORT_ID,
                    detail="같은 현장의 exportId로 다른 사용자·형식·스냅샷을 덮어쓸 수 없다",
                )
            record = RecordedReportExport(
                organization_id=organization_id,
                site_id=site_id,
                export_id=request.export_id,
                export_format=request.export_format,
                actor=actor,
                recorded_at=now.astimezone(UTC),
                snapshot=snapshot,
                snapshot_digest=digest,
            )
            raw = {
                "kind": "report-export-recorded",
                "ts": iso_utc(record.recorded_at),
                "organizationId": organization_id,
                "siteId": site_id,
                "exportId": request.export_id,
                "exportFormat": request.export_format.value,
                "actor": actor,
                "snapshot": snapshot.model_dump(by_alias=True, mode="json"),
                "snapshotDigest": digest,
            }
            try:
                self._journal.append(raw)
            except JournalSealedError:
                return ReportExportResult(
                    ReportExportVerdict.STORE_UNAVAILABLE,
                    detail=JOURNAL_APPEND_FAILED_DETAIL,
                )
            self._project(record)
            return ReportExportResult(ReportExportVerdict.RECORDED, record)

    def history(
        self, *, organization_id: str, site_id: str, limit: int | None = None
    ) -> list[RecordedReportExport]:
        if limit is not None and limit < 0:
            raise ValueError("limit은 음수일 수 없다")
        if self._site_store.get_scoped(site_id, organization_id) is None:
            return []
        with self._lock:
            records = list(reversed(self._by_site.get((organization_id, site_id), ())))
        return records if limit is None else records[:limit]

    def site_exists_scoped(self, *, organization_id: str, site_id: str) -> bool:
        """Expose the visibility check without leaking the backing SiteStore."""

        return self._site_store.get_scoped(site_id, organization_id) is not None


def _entry_view(record: RecordedReportExport) -> ReportExportEntry:
    return ReportExportEntry(
        export_id=record.export_id,
        export_format=record.export_format,
        actor=record.actor,
        recorded_at=record.recorded_at,
        snapshot=record.snapshot,
        snapshot_digest=record.snapshot_digest,
    )


def build_report_exports_router(store: ReportExportStore) -> APIRouter:
    router = APIRouter(prefix="/v1/sites", tags=["report-exports"])

    @router.post(
        "/{site_id}/report-exports",
        response_model=ReportExportCreateResponse,
        status_code=201,
    )
    def create_report_export(
        site_id: str,
        request: ReportExportCreateRequest,
        response: Response,
        principal: Principal = Depends(require_permission(Permission.SITES_READ)),  # noqa: B008
    ) -> ReportExportCreateResponse:
        """Record a browser PDF/CSV export audit fact; Core does not receive the file bytes."""
        outcome = store.record(
            request,
            organization_id=principal.organization_id,
            site_id=site_id,
            actor=principal.principal_id,
            now=datetime.now(UTC),
        )
        response.status_code = _STATUS[outcome.verdict]
        if outcome.verdict is ReportExportVerdict.STORE_UNAVAILABLE:
            response.headers["Retry-After"] = "30"
        record = outcome.record
        return ReportExportCreateResponse(
            verdict=outcome.verdict.value,
            export_id=None if record is None else record.export_id,
            recorded_at=None if record is None else record.recorded_at,
            snapshot_digest=None if record is None else record.snapshot_digest,
            detail=outcome.detail,
        )

    @router.get("/{site_id}/report-exports", response_model=ReportExportListView)
    def list_report_exports(
        site_id: str,
        limit: int = Query(default=DEFAULT_HISTORY_LIMIT, ge=1, le=200),  # noqa: B008
        principal: Principal = Depends(require_permission(Permission.SITES_READ)),  # noqa: B008
    ) -> ReportExportListView:
        # Unknown/cross-org sites are deliberately indistinguishable. A known site
        # with no exports is an empty 200 list, unlike data products where 404 could
        # mean "not yet computed".
        if not store.site_exists_scoped(
            organization_id=principal.organization_id, site_id=site_id
        ):
            raise HTTPException(status_code=404, detail="해당 조직의 현장을 찾을 수 없다")
        # Count and page come from one projection snapshot. Two independent
        # reads could disagree if another export is appended between them.
        history = store.history(organization_id=principal.organization_id, site_id=site_id)
        return ReportExportListView(
            site_id=site_id,
            export_count=len(history),
            exports=[_entry_view(entry) for entry in history[:limit]],
        )

    return router


def mount_report_exports(app: Any, store: ReportExportStore) -> None:
    app.include_router(build_report_exports_router(store))


__all__ = [
    "DEFAULT_HISTORY_LIMIT",
    "RecordedReportExport",
    "ReportExportCreateRequest",
    "ReportExportCatalog",
    "ReportExportFormat",
    "ReportExportRecoveryError",
    "ReportExportResult",
    "ReportExportSnapshot",
    "ReportExportStore",
    "ReportExportVerdict",
    "build_report_exports_router",
    "mount_report_exports",
]
