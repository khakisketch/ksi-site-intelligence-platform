import { parseVisualBrowsingContext, visualBrowsingReturnHref, type VisualBrowsingContext } from "@/lib/operator-journey";
import { ResponsiveActionBoundary } from "@/components/responsive/ResponsiveActionBoundary";
import { SiteSelectionForm } from "@/app/sites/[siteId]/SiteSelectionForm";
import Link from "next/link";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { OperationsSessionFailure } from "@/app/field/OperationsSessionFailure";
import { resolveFieldSession } from "@/app/field/resolve-session";
import { SiteHeader } from "@/app/sites/[siteId]/SiteHeader";

import { SpatialDataRequestAction } from "./SpatialDataRequestAction";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { CoreApiError } from "@/lib/core-api/client";
import {
  getSpatialAsset,
  listSpatialAssets,
  type SpatialAssetCatalogItem,
  type SpatialAssetInspection,
  type SpatialAssetInspectedRasterFacts,
} from "@/lib/core-api/spatial-assets";
import { getSite } from "@/lib/core-api/sites";
import { getExternalReconstructionSubmission } from "@/lib/core-api/external-reconstruction";
import { validateRegistrationHistory } from "@/lib/registration-history";
import { RegistrationHistoryFacts, RegistrationHistoryUnavailable } from "./RegistrationHistoryFacts";
import { formatKoreanDateTime } from "@/lib/datetime";
import { formatBytesKo, formatCountKo } from "@/lib/number-format";
import { listObservationWorkOrders } from "@/lib/core-api/observation-work-orders";
import {
  duplicateFileNames,
  resolveWorkName,
} from "@/lib/human-labels";
import {
  assetBusinessTitle,
  assetBusinessTitles,
  assetLifecycleLabel,
  capturePeriodTitle,
  dataKindLabel,
  isSupportedDataKind,
  isSupportedLifecycleState,
} from "@/lib/operator-language";
import { listWorkAreas } from "@/lib/core-api/workAreas";

export const metadata = { title: "등록 자료 · KSI" };

type SearchValue = string | string[] | undefined;
type SearchParams = { workAreaId?: SearchValue; cursor?: SearchValue; assetRef?: SearchValue; visualAAssetRef?: SearchValue; visualBAssetRef?: SearchValue; q?: SearchValue; kind?: SearchValue; state?: SearchValue };

/** 목록 필터. Core 카탈로그는 정렬·검색 계약을 따로 받지 않으므로, 불러온
 *  페이지 안에서만 적용하고 그 범위를 화면에 밝힌다. */
interface CatalogFilters {
  q: string;
  kind: string;
  state: "" | "inspected" | "attention";
}
const EMPTY_FILTERS: CatalogFilters = { q: "", kind: "", state: "" };

function singleQueryValue(value: SearchValue): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

function pageHref(siteId: string, workAreaId: string, values: { cursor?: string; assetRef?: string } = {}, context: VisualBrowsingContext | null = null, filters: CatalogFilters = EMPTY_FILTERS): string {
  const query = new URLSearchParams({ workAreaId });
  if (context?.workAreaId === workAreaId) {
    query.set("visualAAssetRef", context.visualAAssetRef);
    query.set("visualBAssetRef", context.visualBAssetRef);
  }
  if (filters.q) query.set("q", filters.q);
  if (filters.kind) query.set("kind", filters.kind);
  if (filters.state) query.set("state", filters.state);
  if (values.cursor) query.set("cursor", values.cursor);
  if (values.assetRef) query.set("assetRef", values.assetRef);
  return `/sites/${encodeURIComponent(siteId)}/spatial-assets?${query.toString()}`;
}

function filtersAreActive(filters: CatalogFilters): boolean {
  return filters.q !== "" || filters.kind !== "" || filters.state !== "";
}

/** 검사 실패와 검사 전을 한 칸에 둔다 — 둘 다 아직 쓸 수 있다고 말할 수 없다. */
function needsAttention(item: SpatialAssetCatalogItem): boolean {
  return item.inspection.state === "FAILED"
    || item.inspection.outcome === "REJECTED"
    || item.inspection.outcome === null;
}


function errorView(error: unknown, scope: "site" | "catalog" | "detail", siteId: string, returnHref?: string) {
  if (error instanceof CoreApiError) {
    if (error.status === 404) {
      if (scope === "site") notFound();
      return <ErrorState
        message={scope === "catalog"
          ? "작업구역을 확인할 수 없거나 접근 권한이 없습니다."
          : "자산을 찾을 수 없거나 현재 조회할 수 없습니다."}
        tone="high"
        action={{ label: "등록 자료 목록으로", href: returnHref ?? `/sites/${encodeURIComponent(siteId)}/spatial-assets` }}
      />;
    }
    if (error.status === 403) {
      return <ErrorState message="현장 등록 자료 조회 권한이 없습니다. 현장 담당자에게 조회 권한을 요청하세요." tone="high" />;
    }
    if (error.status === 503 || error.status >= 500) {
      return <ErrorState message="등록 자료를 일시적으로 불러오지 못했습니다." retryable retryAfterSeconds={error.retryAfterSeconds} />;
    }
    return <ErrorState message="요청한 등록 자료 정보를 확인할 수 없습니다." tone="high" />;
  }
  return <ErrorState message="등록 자료 정보를 불러오지 못했습니다." retryable />;
}

function TechnicalFileInfo({ item, workName, areaName }: { item: SpatialAssetCatalogItem; workName?: string | null; areaName?: string }) {
  return <details className="mt-2 text-[12px] text-ink-2">
    <summary className="tap-target cursor-pointer font-semibold text-ink-muted">파일 정보·처리 상세 보기</summary>
    <div className="mt-1 flex flex-col gap-1 break-all border-l-2 border-line pl-3">
      <p>등록 파일명 · {item.declared.fileName}</p>
      {areaName && <p>작업구역명 · {areaName}</p>}
      <p>등록된 관측 작업명 · {workName ?? "확인 불가"}</p>
      <p>제출 참조 · {item.submissionRef} · 등록 버전 {item.revision}</p>
      <p>등록 버전은 제출한 자료 묶음의 버전이며 촬영 횟수와 다릅니다.</p>
      {!isSupportedDataKind(item.kind) && <p>등록 종류(원문) · {item.kind}</p>}
      {!isSupportedLifecycleState(item.lifecycleState) && <p>등록 상태(원문) · {item.lifecycleState}</p>}
      <p>자산 참조 · {item.assetRef}</p>
      <p>관측 기록 ID · {item.observationEpochId}</p>
      <p>작업 지시 ID · {item.workOrderId}</p>
      <p>원본 artifact ID · {item.artifactId}</p>
    </div>
  </details>;
}

const INSPECTION_STATE_LABEL: Record<string, string> = {
  PENDING_SEAL: "파일 제출 대기",
  INSPECTION_NOT_CONFIGURED: "검사 미설정",
  INSPECTION_NOT_QUERIED: "검사 결과 확인 전",
  INSPECTION_PENDING_SEAL: "파일 제출 대기",
  INSPECTION_PENDING_POLICY: "검사 기준 확인 중",
  INSPECTION_PENDING: "검사 대기",
  INSPECTION_QUEUED: "검사 대기",
  INSPECTION_RUNNING: "검사 중",
  INSPECTION_REPORTED: "검사 결과 기록됨",
  INSPECTION_FAILED_INCOMPLETE: "검사 미완료",
  COMPLETED: "검사 완료",
  FAILED: "검사 실패",
};

function inspectionStateLabel(state: string): string {
  return INSPECTION_STATE_LABEL[state] ?? "검사 상태 확인 필요";
}

function inspectionOutcomeLabel(outcome: SpatialAssetInspection["outcome"]): string {
  if (outcome === "MEASURED") return "파일 정보 확인됨";
  if (outcome === "REJECTED") return "거부됨";
  if (outcome === "NOT_APPLICABLE") return "적용 대상 아님";
  return "아직 확인되지 않음";
}

function kindLabel(kind: SpatialAssetCatalogItem["kind"]): string {
  return dataKindLabel(kind);
}

function exactByteCount(value: number): string {
  return Number.isSafeInteger(value) && value >= 0
    ? formatBytesKo(value)
    : "정확한 크기 표시 불가";
}

function isMetadataOnly(item: SpatialAssetCatalogItem): boolean {
  return item.dataAccess === "NOT_AVAILABLE_FROM_CATALOG"
    && item.analysisStatus === "NOT_EVALUATED"
    && item.supportedActions.length === 1
    && item.supportedActions[0] === "VIEW_METADATA";
}

/**
 * 관측 묶음 grouping — Core가 준 관측 기록 ID 순서 그대로 둔다.
 * 시간으로 재정렬하지 않고, 묶음 식별자가 없는 항목은 따로 모은다(버리지 않는다).
 */
function groupAssetsByObservation(items: readonly SpatialAssetCatalogItem[]): Array<{ epochId: string; items: SpatialAssetCatalogItem[] }> {
  const groups: Array<{ epochId: string; items: SpatialAssetCatalogItem[] }> = [];
  const index = new Map<string, SpatialAssetCatalogItem[]>();
  for (const item of items) {
    const key = typeof item.observationEpochId === "string" && item.observationEpochId.length > 0
      ? item.observationEpochId
      : "";
    let list = index.get(key);
    if (!list) {
      list = [];
      index.set(key, list);
      groups.push({ epochId: key, items: list });
    }
    list.push(item);
  }
  return groups;
}

/** 묶음 안의 촬영 구간이 모두 같을 때만 한 줄로 말한다. 다르면 항목별로만 둔다. */
function observationGroupDateLine(items: readonly SpatialAssetCatalogItem[]): string | null {
  const lines = items.map((item) =>
    capturePeriodTitle(item.declared.captureStartedAt, item.declared.captureEndedAt, {
      captureDate: item.declared.captureDate ?? null,
    }));
  const first = lines[0];
  if (first === undefined) return null;
  return lines.every((line) => line === first) ? first : null;
}

interface AvailabilityStatus {
  label: string;
  action: string | null;
  retry: boolean;
}

/**
 * 자료 상태에서 허용되는 행동 — 카탈로그가 아는 것만 말한다.
 * 분석 적합성은 이 목록에서 평가하지 않으므로 '적합' 상태는 두지 않는다.
 */
function availabilityStatus(item: SpatialAssetCatalogItem): AvailabilityStatus {
  if (item.inspection.outcome === "REJECTED" || item.inspection.state === "FAILED") {
    return {
      label: "처리 실패",
      action: `${item.inspection.reason ? `사유: ${item.inspection.reason}. ` : ""}구역 자료 준비에서 재처리를 요청하세요.`,
      retry: true,
    };
  }
  if (item.lifecycleState === "UNSEALED") {
    return { label: "파일 제출 미완료", action: "제출이 끝나면 갱신됩니다.", retry: false };
  }
  if (item.lifecycleState === "SUPERSEDED") {
    return { label: "이전 등록 자료", action: "최신 제출을 기준으로 보세요.", retry: false };
  }
  const inspected = item.inspection.outcome === "MEASURED"
    ? "파일 정보 확인됨"
    : item.inspection.outcome === "NOT_APPLICABLE"
      ? "적용 대상 아님"
      : "검사 결과 확인 전";
  return {
    label: inspected,
    action: item.observed ? null : "저장 파일 확인 기록 없음.",
    retry: false,
  };
}

/** 파일 타일 — 제출된 파일의 형식만 말한다. 픽셀이 없으므로 썸네일인 척하지 않는다. */
function FileKindTile({ fileName }: { fileName: string }) {
  const ext = fileName.includes(".") ? fileName.split(".").pop()!.toUpperCase().slice(0, 4) : "FILE";
  return <span aria-hidden="true" className="flex h-11 w-11 shrink-0 items-center justify-center rounded-md border border-line bg-sunk font-mono text-[10px] font-bold text-ink-2">{ext}</span>;
}

/** 목록 행 — 두 줄로 끝낸다. 파일 사실과 검사 근거는 펼친 상세에서만 본다. */
function AssetRow({ item, headline, toggleHref, toggleLabel, open, expanded, nameIsDuplicated }: {
  item: SpatialAssetCatalogItem;
  headline: string;
  toggleHref: string;
  toggleLabel: "상세 보기" | "닫기";
  open: boolean;
  expanded: ReactNode;
  nameIsDuplicated: boolean;
}) {
  const availability = availabilityStatus(item);
  const inspectionText = inspectionOutcomeLabel(item.inspection.outcome);
  // 검사 결과가 상태를 그대로 말하면 되풀이하지 않는다 — 다를 때만 둘 다 둔다.
  const statusExtra = availability.label !== inspectionText || availability.action ? availability : null;
  const inspectionTone = item.inspection.outcome === "MEASURED"
    ? "text-safe-ink"
    : needsAttention(item) ? "text-high-ink" : "text-ink-2";
  return <>
    <div className="flex items-center gap-3 py-2.5">
      <FileKindTile fileName={item.declared.fileName} />
      <div className="min-w-0 flex-1">
        <p className="break-words text-[14px] font-semibold leading-snug">{headline}</p>
        <p className="mt-0.5 break-all text-[12px] text-ink-2">파일명 · {item.declared.fileName}</p>
        <p className="mt-0.5 break-words text-[12px] text-ink-2">
          <span className={`font-semibold ${inspectionTone}`}>파일 검사 · {inspectionText}</span>
          {statusExtra !== null && <>
            {" · "}상태 · {statusExtra.label}
            {statusExtra.action ? ` — ${statusExtra.action}` : ""}
          </>}
        </p>
        {nameIsDuplicated && <p className="mt-0.5 text-[11.5px] text-high-ink">같은 파일명이 이 목록에 여러 건 있습니다. 펼쳐서 등록 버전·촬영 구간으로 구분하세요.</p>}
      </div>
      <Link href={toggleHref} aria-expanded={open} aria-label={`${headline} ${toggleLabel}`} className="tap-target shrink-0 text-[12.5px] font-semibold text-ink-2 underline decoration-dotted">{toggleLabel}</Link>
    </div>
    {open ? expanded : null}
  </>;
}

function FactStatus({ item, compact = false }: { item: SpatialAssetCatalogItem; compact?: boolean }) {
  const inspectionText = inspectionOutcomeLabel(item.inspection.outcome);
  return <div className={compact ? "mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11.5px] text-ink-2" : "mt-3 grid gap-2 sm:grid-cols-3"}>
    <p>제출자 입력 정보 있음</p>
    <p>{item.observed ? "저장 파일 확인 기록 있음" : "저장 파일 확인 기록 없음"}</p>
    <p>파일 검사: {inspectionText}</p>
  </div>;
}

function DeclaredFacts({ item }: { item: SpatialAssetCatalogItem }) {
  const declared = item.declared;
  return <section className="rounded-lg border border-line bg-surface p-4">
    <h3 className="text-[14px] font-bold">제출자가 입력한 정보</h3>
    <dl className="mt-3 grid gap-3 text-[12.5px] sm:grid-cols-2">
      <Fact label="파일명 / 형식" value={`${declared.fileName} · ${declared.format}`} />
      <Fact label="종류 / MIME" value={`${kindLabel(item.kind)} · ${declared.contentType}`} />
      <Fact label="신고 크기" value={exactByteCount(declared.sizeBytes)} />
      <Fact label="신고 파일 확인값(SHA-256)" value={declared.sha256} mono />
      <Fact label="신고 좌표 기준" value={declared.crs ?? "미기재"} />
      <Fact label="신고 해상도" value={declared.gsdM === null ? "미기재" : `${declared.gsdM} m/pixel`} />
      <Fact label="제출 시각" value={formatKoreanDateTime(declared.submittedAt, { dateStyle: "medium", timeStyle: "short" })} />
      <Fact label="처리 완료 신고 시각" value={declared.producerCompletedAt ? formatKoreanDateTime(declared.producerCompletedAt, { dateStyle: "medium", timeStyle: "short" }) : "미기재"} />
      <Fact label="촬영 구간" value={declared.captureStartedAt && declared.captureEndedAt ? `${formatKoreanDateTime(declared.captureStartedAt, { dateStyle: "medium", timeStyle: "short" })} – ${formatKoreanDateTime(declared.captureEndedAt, { dateStyle: "medium", timeStyle: "short" })}` : "완전한 구간 미기재"} />
      <Fact label="신고 수직 기준" value={declared.verticalReference ? `${declared.verticalReference.datum} · ${declared.verticalReference.basis}` : "미기재"} />
    </dl>
    <p className="mt-3 text-[11.5px] leading-5 text-ink-muted">이 항목은 고객이 신고한 값이며 파일에서 확인한 사실이나 정확도 보증을 뜻하지 않습니다.</p>
  </section>;
}

function ObservedFacts({ item }: { item: SpatialAssetCatalogItem }) {
  if (!item.observed) return <section className="rounded-lg border border-line bg-surface p-4"><h3 className="text-[14px] font-bold">저장 파일 확인 정보</h3><p className="mt-2 text-[12.5px] text-ink-2">제출 파일을 확인한 기록이 없습니다.</p></section>;
  const observed = item.observed;
  return <section className="rounded-lg border border-line bg-surface p-4">
    <h3 className="text-[14px] font-bold">저장 파일 확인 정보</h3>
    <dl className="mt-3 grid gap-3 text-[12.5px] sm:grid-cols-2">
      <Fact label="관측 크기" value={exactByteCount(observed.sizeBytes)} />
      <Fact label="관측 MIME" value={observed.contentType} />
      <Fact label="관측 파일 확인값(SHA-256)" value={observed.sha256} mono />
      <Fact label="매니페스트 확인값" value={observed.manifestDigest} mono />
      <Fact label="KSI 관측 시각" value={formatKoreanDateTime(observed.observedAt, { dateStyle: "medium", timeStyle: "short" })} />
    </dl>
    <p className="mt-3 text-[11.5px] leading-5 text-ink-muted">바이트 관측은 파일의 공간적 의미나 분석 적합성을 확인한 결과가 아닙니다.</p>
  </section>;
}

function Fact({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return <div className="min-w-0"><dt className="text-[11px] text-ink-muted">{label}</dt><dd className={`mt-0.5 break-words text-ink-2 ${mono ? "font-mono text-[11px]" : ""}`}>{value}</dd></div>;
}

function RasterFacts({ raster }: { raster: SpatialAssetInspectedRasterFacts }) {
  return <>
    <dl className="mt-3 grid gap-3 text-[12.5px] sm:grid-cols-2">
      <Fact label="관측 좌표 기준" value={raster.observedCrsIdentifier} />
      <Fact label="격자 크기" value={`${formatCountKo(raster.width)} × ${formatCountKo(raster.height)} pixels`} />
      <Fact label="관측 좌표 기준 확인값" value={raster.observedCrsDigest} mono />
      <Fact label="검사 보고서 확인값" value={raster.sourceReportDigest} mono />
      <Fact label="검사 도구 빌드 확인값" value={raster.inspectorBuildDigest} mono />
      <Fact label="관측 수직 기준" value={raster.observedVerticalReference ? `${raster.observedVerticalReference.identifier} · ${raster.observedVerticalReference.basis}` : "관측되지 않음"} />
    </dl>
    <details className="mt-3 text-[11.5px] text-ink-2"><summary className="cursor-pointer">격자 변환과 포함 범위 근거</summary>
      <p className="mt-2 break-all font-mono">{raster.transform.join(", ")}</p>
      <p className="mt-2 break-all font-mono">{raster.footprintWkt}</p>
      <p className="mt-1 break-all font-mono text-ink-muted">범위 확인값: {raster.footprintDigest}</p>
    </details>
  </>;
}

function InspectionFacts({ inspection }: { inspection: SpatialAssetInspection }) {
  return <section className="rounded-lg border border-line bg-surface p-4">
    <h3 className="text-[14px] font-bold">파일 검사 결과</h3>
    <p className="mt-2 text-[12.5px] text-ink-2">상태: {inspectionStateLabel(inspection.state)} · 결과: {inspectionOutcomeLabel(inspection.outcome)}</p>
    {inspection.reason && <p className="mt-1 text-[12px] text-ink-2">사유: {inspection.reason}</p>}
    <details className="mt-2 text-[12px] text-ink-2"><summary className="tap-target cursor-pointer">좌표·격자와 검사 근거</summary>
    <p className="mt-1">검사 상태 코드 · {inspection.state}</p>
    {inspection.raster ? <RasterFacts raster={inspection.raster} /> : <p className="mt-2 text-[12px] text-ink-muted">파일에서 확인한 위치·격자 정보가 없습니다.</p>}
    {inspection.reportDigest && <p className="mt-2 break-all font-mono text-[10.5px] text-ink-muted">검사 보고서 확인값: {inspection.reportDigest}</p>}
    </details>
    <p className="mt-3 text-[11.5px] leading-5 text-ink-muted">형식·격자 정보 검사만 나타냅니다. 정확도, 좌표 기준의 현장 검증, 분석 적합성은 판정하지 않습니다.</p>
  </section>;
}

function AssetDetail({ item, workName, areaName, headline, compareHref, retryHref = null }: {
  item: SpatialAssetCatalogItem;
  workName: string | null;
  areaName: string;
  headline: string;
  /** 분석 요청 권한이 있고 이 자료의 관측 작업을 실제로 지목할 수 있을 때만 넘긴다. */
  compareHref: string | null;
  /** 처리 실패 항목에만 준다 — 다른 상태의 재처리를 암시하지 않는다. */
  retryHref?: string | null;
}) {
  const availability = availabilityStatus(item);
  const captureLine = capturePeriodTitle(item.declared.captureStartedAt, item.declared.captureEndedAt, {
    captureDate: item.declared.captureDate ?? null,
  });
  // 바깥(행 목록·상세 틀)이 경계를 이미 졌으므로 안쪽은 근접으로만 나눈다.
  // kicker는 두지 않는다 — 제목이 말하게 한다.
  return <section aria-label="관측 자료 상세" className="flex flex-col gap-2.5 rounded-lg border border-line bg-surface p-3 sm:p-4">
    <header>
      <p className="sr-only">관측 자료 상세</p>
      <h4 className="break-words text-[16px] font-bold tracking-tight">{headline}</h4>
      <p className="mt-0.5 text-[12px] text-ink-2">{areaName} · 등록 버전 {item.revision}</p>
    </header>
    {/* 상세 첫 화면은 파일명이 아니라 이 자료가 무엇이고 어디까지 확인됐는지다. */}
    <dl className="grid grid-cols-2 gap-x-3 gap-y-2 py-1 sm:grid-cols-4">
      <div className="min-w-0"><dt className="text-[11px] text-ink-muted">자료 구성</dt><dd className="mt-0.5 break-words text-[12.5px] font-semibold">{dataKindLabel(item.kind)} · {item.declared.format}</dd></div>
      <div className="min-w-0"><dt className="text-[11px] text-ink-muted">관측 시점</dt><dd className="mt-0.5 break-words text-[12.5px] font-semibold">{captureLine}</dd></div>
      <div className="min-w-0"><dt className="text-[11px] text-ink-muted">파일 검사</dt><dd className="mt-0.5 break-words text-[12.5px] font-semibold">{inspectionOutcomeLabel(item.inspection.outcome)}</dd></div>
      <div className="min-w-0"><dt className="text-[11px] text-ink-muted">정량 분석 적합성</dt><dd className="mt-0.5 break-words text-[12.5px] font-semibold text-ink-2">이 화면에서 판정하지 않음</dd></div>
    </dl>
    <p className="text-[12px] text-ink-2">
      {item.lifecycleState !== "SEALED" && <><span className="font-semibold">제출 상태 · {assetLifecycleLabel(item.lifecycleState)}</span>{" · "}</>}
      <span className="font-semibold">상태 · {availability.label}</span>
      {availability.action ? ` — ${availability.action}` : ""}
    </p>
    {availability.retry && retryHref
      ? <p className="text-[12px] text-high-ink">재처리는 <Link className="tap-target underline" href={retryHref}>구역 자료 준비에서 재처리 요청</Link>하세요.</p>
      : null}
    {compareHref && <div className="flex flex-wrap items-center gap-2">
      <Link href={compareHref} className="btn w-fit">이 자료를 현재 관측으로 선택</Link>
      <span className="text-[11.5px] text-ink-muted">분석 실행은 결과 화면에서 합니다.</span>
    </div>}
    <FactStatus item={item} />
    <div className="grid gap-2 sm:grid-cols-2">
      <details className="rounded-lg border border-line bg-surface p-3 text-[12px]"><summary className="tap-target cursor-pointer font-semibold">제출자 입력 정보</summary><DeclaredFacts item={item} /></details>
      <details className="rounded-lg border border-line bg-surface p-3 text-[12px]"><summary className="tap-target cursor-pointer font-semibold">저장 파일 확인</summary><ObservedFacts item={item} /></details>
    </div>
    <InspectionFacts inspection={item.inspection} />
    <details className="rounded-lg border border-line bg-surface p-3 text-[12px]"><summary className="tap-target cursor-pointer font-semibold">파일·참조 정보</summary><TechnicalFileInfo item={item} workName={workName} areaName={areaName} /></details>
    <p className="text-[11.5px] leading-5 text-ink-muted">파일 검사 완료는 형식·격자 확인이며, 측량·정산 근거나 분석 사용 가능 판정이 아닙니다.</p>
    {item.lifecycleState !== "SEALED" && <p className="text-[11.5px] leading-5 text-high-ink">제출 상태가 {assetLifecycleLabel(item.lifecycleState)}이므로 유효한 분석 입력으로 취급하지 않습니다.</p>}
  </section>;
}

/** 펼친 행의 본문 — 상세·등록 이력·받기 요청을 한 덩어리로 둔다. */
function DetailBlock({ detail, workName, areaName, headline, compareHref, retryHref, historyResult, requestProps }: {
  detail: SpatialAssetCatalogItem;
  workName: string | null;
  areaName: string;
  headline: string;
  compareHref: string | null;
  retryHref: string | null;
  historyResult: ReturnType<typeof validateRegistrationHistory> | null;
  requestProps: { siteId: string; workAreaId: string; inspectedRaster: SpatialAssetCatalogItem["inspection"]["raster"]; canRequest: boolean };
}) {
  return <>
    <AssetDetail
      item={detail}
      workName={workName}
      areaName={areaName}
      headline={headline}
      compareHref={compareHref}
      retryHref={retryHref}
    />
    {historyResult?.kind === "v3" && <RegistrationHistoryFacts history={historyResult.history} />}
    {historyResult?.kind === "unavailable" && <RegistrationHistoryUnavailable />}
    <SpatialDataRequestAction
      siteId={requestProps.siteId}
      workAreaId={requestProps.workAreaId}
      assetRef={detail.assetRef}
      inspectedRaster={requestProps.inspectedRaster}
      observedCrsIdentifier={requestProps.inspectedRaster?.observedCrsIdentifier ?? null}
      observedCrsDigest={requestProps.inspectedRaster?.observedCrsDigest ?? null}
      canRequest={requestProps.canRequest}
    />
  </>;
}

export default async function SpatialAssetsPage({
  params,
  searchParams,
}: {
  params: Promise<{ siteId: string }>;
  searchParams: Promise<SearchParams>;
}) {
  const [{ siteId }, query] = await Promise.all([params, searchParams]);
  const session = await resolveFieldSession();
  if (session.kind === "blocked") return <OperationsSessionFailure verdict={session.verdict} next={`/sites/${encodeURIComponent(siteId)}/spatial-assets`} />;

  let site: Awaited<ReturnType<typeof getSite>>;
  let areas: Awaited<ReturnType<typeof listWorkAreas>>;
  try {
    [site, areas] = await Promise.all([getSite(siteId), listWorkAreas(siteId, { includeArchived: true })]);
  } catch (error) {
    return <div className="mx-auto max-w-5xl p-4 sm:p-5">{errorView(error, "site", siteId)}</div>;
  }

  // 작업 지시 이름은 사람용 표시 전용이다. 이 조회가 실패해도 목록·상세는
  // "작업명 확인 불가"로 그대로 표시되며, 존재·권한·적합성을 추정하지 않는다.
  let workOrderNames: Record<string, string> | null = null;
  try {
    const workOrders = await listObservationWorkOrders(siteId);
    const names: Record<string, string> = {};
    for (const order of workOrders) {
      if (order.siteId !== siteId || order.organizationId !== session.principal.organizationId) continue;
      if (typeof order.name === "string" && order.name.trim().length > 0) names[order.workOrderId] = order.name;
    }
    workOrderNames = names;
  } catch {
    workOrderNames = null;
  }

  const basePath = `/sites/${encodeURIComponent(siteId)}/spatial-assets`;
  const areaParam = query.workAreaId;
  if (Array.isArray(areaParam)) {
    return <div className="mx-auto max-w-5xl p-4 sm:p-5"><ErrorState message="작업구역을 하나만 선택하세요." tone="high" action={{ label: "목록으로 돌아가기", href: basePath }} /></div>;
  }
  const workAreaId = singleQueryValue(areaParam);
  // 작업구역이 하나뿐이면 같은 구역으로 이어간다. 여러 구역이면 직접 선택을 둔다.
  const activeAreas = areas.workAreas.filter((area) => area.status === "ACTIVE");
  const effectiveWorkAreaId = workAreaId
    ?? (activeAreas.length === 1 && activeAreas[0] ? activeAreas[0].workAreaId : undefined);
  const effectiveAreaNotice = !workAreaId && effectiveWorkAreaId
    ? "현장에 등록된 작업구역이 하나뿐이라 해당 구역의 자료를 표시합니다."
    : null;
  const selectedArea = areas.workAreas.find((area) => area.workAreaId === effectiveWorkAreaId);
  const cursorParam = query.cursor;
  const assetRefParam = query.assetRef;
  if (workAreaId && !selectedArea) {
    return <div className="mx-auto max-w-5xl p-4 sm:p-5"><ErrorState message="작업구역을 확인할 수 없거나 접근 권한이 없습니다." tone="high" action={{ label: "다른 작업구역 선택", href: basePath }} /></div>;
  }
  if (Array.isArray(cursorParam) || (typeof cursorParam === "string" && cursorParam.length > 1024)) {
    return <div className="mx-auto max-w-5xl p-4 sm:p-5"><ErrorState message="페이지 커서가 올바르지 않습니다. 목록을 처음부터 다시 열어 주세요." tone="high" action={{ label: "처음부터 보기", href: effectiveWorkAreaId ? pageHref(siteId, effectiveWorkAreaId) : basePath }} /></div>;
  }
  if (Array.isArray(assetRefParam) || (typeof assetRefParam === "string" && !/^ksa-v1-[0-9a-f]{64}$/.test(assetRefParam))) {
    return <div className="mx-auto max-w-5xl p-4 sm:p-5"><ErrorState message="자산 참조가 올바르지 않습니다." tone="high" action={{ label: "목록으로 돌아가기", href: effectiveWorkAreaId ? pageHref(siteId, effectiveWorkAreaId) : basePath }} /></div>;
  }
  const cursor = singleQueryValue(cursorParam);
  const assetRef = singleQueryValue(assetRefParam);

  let page: Awaited<ReturnType<typeof listSpatialAssets>> | null = null;
  let pageError: unknown = null;
  if (effectiveWorkAreaId) {
    try {
      page = await listSpatialAssets(siteId, effectiveWorkAreaId, { limit: 50, cursor });
    } catch (error) {
      pageError = error;
    }
  }

  let detail: Awaited<ReturnType<typeof getSpatialAsset>> | null = null;
  let detailError: unknown = null;
  if (assetRef && effectiveWorkAreaId && !pageError) {
    try {
      detail = await getSpatialAsset(siteId, effectiveWorkAreaId, assetRef);
    } catch (error) {
      detailError = error;
    }
  }

  const duplicatedNames = page
    ? duplicateFileNames(page.assets.map((asset) => asset.declared.fileName))
    : new Set<string>();
  const businessTitles = page ? assetBusinessTitles(page.assets) : new Map<string, string>();
  const businessTitleFor = (item: SpatialAssetCatalogItem): string =>
    businessTitles.get(item.assetRef) ?? assetBusinessTitle(item);
  const areaDisplayName = selectedArea?.name ?? effectiveWorkAreaId ?? "";
  const canRequestAnalysis = session.principal.permissions.includes("SITES_WRITE");
  const canRequestData = session.principal.permissions.includes("SPATIAL_DATA_REQUEST");
  const inspectedRaster = detail?.inspection.raster ?? null;
  const detailMatchesScope = detail !== null
    && assetRef !== undefined
    && detail.assetRef === assetRef
    && detail.siteId === siteId
    && detail.workAreaId === effectiveWorkAreaId;

  // 선택한 자산 하나에 묶인 제출서 revision 1건만 읽는다 — 목록 N+1 조회가 아니다.
  // Core revision GET을 운영자 세션으로 그대로 쓰며, 계약 버전·귀속은
  // validateRegistrationHistory가 대조한다. 실패해도 파일 사실은 그대로 둔다.
  let historyResult: ReturnType<typeof validateRegistrationHistory> | null = null;
  if (detailMatchesScope && detail) {
    try {
      const record = await getExternalReconstructionSubmission(detail.workOrderId, detail.submissionRef, detail.revision);
      historyResult = validateRegistrationHistory(record, {
        submissionRef: detail.submissionRef,
        revision: detail.revision,
        siteId: detail.siteId,
        organizationId: session.principal.organizationId,
        observationEpochId: detail.observationEpochId,
      });
    } catch {
      historyResult = { kind: "unavailable" };
    }
  }
  const visualShape = parseVisualBrowsingContext({ workAreaId: effectiveWorkAreaId,
    visualAAssetRef: query.visualAAssetRef, visualBAssetRef: query.visualBAssetRef });
  const currentAssets = page && page.siteId === siteId && page.workAreaId === effectiveWorkAreaId
    ? [...page.assets, ...(detailMatchesScope && detail ? [detail] : [])] : [];
  // 목록은 관측 묶음(관측 기록 ID) 단위로 접는다 — Core 반환 순서를 유지하고
  // 시간으로 재정렬하지 않는다. 범위 밖 항목은 묶음에 넣지 않고 그대로 둔다.
  const inScopeAssets = page && page.siteId === siteId && page.workAreaId === effectiveWorkAreaId
    ? page.assets.filter((item) => item.siteId === siteId && item.workAreaId === effectiveWorkAreaId)
    : [];
  const outOfScopeAssets = page && page.siteId === siteId && page.workAreaId === effectiveWorkAreaId
    ? page.assets.filter((item) => item.siteId !== siteId || item.workAreaId !== effectiveWorkAreaId)
    : [];

  // 필터는 Core 카탈로그가 이미 돌려준 페이지 안에서만 적용한다. 서버 정렬·검색
  // 계약이 없으므로 "전체 구역 검색"처럼 말하지 않고, 아래에서 범위를 밝힌다.
  const requestedKind = singleQueryValue(query.kind) ?? "";
  const requestedState = singleQueryValue(query.state) ?? "";
  const filters: CatalogFilters = {
    q: (singleQueryValue(query.q) ?? "").slice(0, 80),
    kind: isSupportedDataKind(requestedKind) ? requestedKind : "",
    state: requestedState === "inspected" || requestedState === "attention" ? requestedState : "",
  };
  const filteredAssets = inScopeAssets.filter((item) => {
    if (filters.kind && item.kind !== filters.kind) return false;
    if (filters.state === "inspected" && item.inspection.outcome !== "MEASURED") return false;
    if (filters.state === "attention" && !needsAttention(item)) return false;
    if (filters.q) {
      const haystack = `${item.declared.fileName} ${dataKindLabel(item.kind)}`.toLowerCase();
      if (!haystack.includes(filters.q.toLowerCase())) return false;
    }
    return true;
  });
  const catalogCounts = {
    total: inScopeAssets.length,
    inspected: inScopeAssets.filter((item) => item.inspection.outcome === "MEASURED").length,
    attention: inScopeAssets.filter(needsAttention).length,
  };
  const availableKinds = [...new Set(inScopeAssets.map((item) => item.kind))];
  const observationGroups = groupAssetsByObservation(filteredAssets);
  const retryBase = effectiveWorkAreaId
    ? `/sites/${encodeURIComponent(siteId)}/spatial-data-requests?workAreaId=${encodeURIComponent(effectiveWorkAreaId)}`
    : null;
  const visualContext = visualShape && [visualShape.visualAAssetRef, visualShape.visualBAssetRef].every((ref) =>
    currentAssets.some((item) => item.siteId === siteId && item.workAreaId === effectiveWorkAreaId
      && item.assetRef === ref && isMetadataOnly(item))) ? visualShape : null;
  const visualNotice = (query.visualAAssetRef !== undefined || query.visualBAssetRef !== undefined) && !visualContext
    ? "현재 자료 목록에서 탐색 중이던 두 자료를 확인하지 못했습니다. 다른 자료로 대체하지 않았습니다." : null;
  const visualReturnHref = visualContext && effectiveWorkAreaId
    ? visualBrowsingReturnHref(`/sites/${encodeURIComponent(siteId)}`, visualContext, effectiveWorkAreaId) : null;
  const currentHint = new URLSearchParams();
  if (effectiveWorkAreaId && detailMatchesScope && detail) {
    currentHint.set("workAreaId", effectiveWorkAreaId);
    currentHint.set("hintCurrentWorkOrderId", detail.workOrderId);
    currentHint.set("hintCurrentSubmissionRef", detail.submissionRef);
    currentHint.set("hintCurrentRevision", String(detail.revision));
    if (visualContext) {
      currentHint.set("visualAAssetRef", visualContext.visualAAssetRef);
      currentHint.set("visualBAssetRef", visualContext.visualBAssetRef);
    }
  }
  const compareHref = canRequestAnalysis && effectiveWorkAreaId && selectedArea && detailMatchesScope && detail?.workOrderId
    ? `/sites/${encodeURIComponent(siteId)}/analysis?${currentHint.toString()}#new-analysis-request`
    : null;
  // 상세는 목록 행 아래에 펼친다. 현재 필터에 걸러진 항목이면 목록 위에
  // 같은 상세를 둔다 — 커서 페이지 밖 선택도 잃지 않는다.
  const expandedAssetRef = detailMatchesScope && detail && filteredAssets.some((item) => item.assetRef === detail.assetRef)
    ? detail.assetRef
    : null;
  const detailBlock = detailMatchesScope && detail && isMetadataOnly(detail)
    ? <DetailBlock
      detail={detail}
      workName={resolveWorkName(detail.workOrderId, workOrderNames)}
      areaName={areaDisplayName}
      headline={businessTitleFor(detail)}
      compareHref={compareHref}
      retryHref={retryBase}
      historyResult={historyResult}
      requestProps={{ siteId, workAreaId: effectiveWorkAreaId!, inspectedRaster, canRequest: canRequestData }}
    />
    : null;

  return <div className="flex flex-col">
    <SiteHeader
      site={site}
      selectedEpochId={null}
      tab="materials"
      canCreateWorkOrder={session.principal.permissions.includes("WORK_ORDERS_WRITE")}
      canEditAoi={canRequestAnalysis}
      scopedWorkAreaId={effectiveWorkAreaId && selectedArea ? effectiveWorkAreaId : null}
      scopedAssetRef={detail && assetRef && detail.assetRef === assetRef ? assetRef : null}
      visualContext={visualContext}
    />
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-3 p-4 sm:p-5">
      {visualReturnHref && <p className="text-[12px] text-ink-2">탐색 중이던 두 자료는 유지합니다. <Link className="tap-target inline-flex underline" href={visualReturnHref}>독립 보기로 돌아가기</Link></p>}
      {visualNotice && <p role="status" className="text-[12px] text-ink-2">{visualNotice}</p>}
      {/* 제목은 탭과 같은 말로 한 번만. 설명 문단은 두지 않는다. */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-[18px] font-bold tracking-tight">자료</h2>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          {/* 자료 등록이 이 화면의 유일한 1차 행동이다. 준비·외부 기록은
              같은 줄의 조용한 길로만 둔다. */}
          {session.principal.permissions.includes("WORK_ORDERS_WRITE") && (
            <ResponsiveActionBoundary action="WORK_ORDERS_WRITE" inlineNotice={false}>
            <Link
              href={`/sites/${encodeURIComponent(siteId)}/observations/new${effectiveWorkAreaId ? `?workAreaId=${encodeURIComponent(effectiveWorkAreaId)}` : ""}`}
              className="btn btn-primary"
            >
              자료 등록
            </Link>
            </ResponsiveActionBoundary>
          )}
          <span className="flex flex-wrap gap-x-3 text-[12.5px]">
            <Link className="tap-target underline text-ink-2" href={`/sites/${encodeURIComponent(siteId)}/spatial-data-requests${effectiveWorkAreaId ? `?workAreaId=${encodeURIComponent(effectiveWorkAreaId)}` : ""}`}>구역 자료 준비</Link>
            <Link className="tap-target underline text-ink-2" href={`/sites/${encodeURIComponent(siteId)}/observations`}>외부 비교 기록</Link>
          </span>
        </div>
      </div>

      {/* 도구모음 한 줄 — 구역·검색·유형·검사가 같은 띠에서 바로 바뀐다.
          SiteSelectionForm 은 JS 가 있을 때 변경 즉시 제출하고, 없을 때는
          네이티브 제출 버튼을 남긴다. 구역이 바뀌면 다른 필터는 버린다. */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-y border-line py-2">
        <SiteSelectionForm action={basePath} className="flex items-center gap-1.5">
          <label className="flex items-center gap-1.5 text-[12px] font-semibold" htmlFor="spatial-work-area">작업구역
            <select id="spatial-work-area" name="workAreaId" className="input w-auto" defaultValue={effectiveWorkAreaId ?? ""} required>
              <option value="" disabled>선택</option>
              {areas.workAreas.map((area) => <option key={area.workAreaId} value={area.workAreaId}>{area.name}{area.status === "ARCHIVED" ? " · 보관됨" : ""}</option>)}
            </select>
          </label>
        </SiteSelectionForm>
        {effectiveWorkAreaId && inScopeAssets.length > 0 && <SiteSelectionForm action={basePath} className="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-2">
          <input type="hidden" name="workAreaId" value={effectiveWorkAreaId} />
          {visualContext && <>
            <input type="hidden" name="visualAAssetRef" value={visualContext.visualAAssetRef} />
            <input type="hidden" name="visualBAssetRef" value={visualContext.visualBAssetRef} />
          </>}
          <label className="flex min-w-36 flex-1 items-center gap-1.5 text-[12px] font-semibold" htmlFor="spatial-q">검색
            <input id="spatial-q" name="q" type="search" defaultValue={filters.q} maxLength={80} placeholder="파일명 또는 자료 유형" className="input" />
          </label>
          <label className="flex items-center gap-1.5 text-[12px] font-semibold" htmlFor="spatial-kind">유형
            <select id="spatial-kind" name="kind" className="input w-auto" defaultValue={filters.kind}>
              <option value="">전체 유형</option>
              {availableKinds.map((kind) => <option key={kind} value={kind}>{dataKindLabel(kind)}</option>)}
            </select>
          </label>
          <label className="flex items-center gap-1.5 text-[12px] font-semibold" htmlFor="spatial-state">검사
            <select id="spatial-state" name="state" className="input w-auto" defaultValue={filters.state}>
              <option value="">전체</option>
              <option value="inspected">검사 완료</option>
              <option value="attention">확인 필요</option>
            </select>
          </label>
          {filtersAreActive(filters) && <Link className="tap-target text-[12.5px] underline text-ink-2" href={pageHref(siteId, effectiveWorkAreaId ?? "", {}, visualContext)}>필터 초기화</Link>}
        </SiteSelectionForm>}
      </div>
      {areas.workAreas.length === 0 && <p className="text-[12.5px] leading-5 text-ink-2">현장에 등록된 작업구역이 없습니다. 자료를 확인하려면 작업구역을 먼저 등록하세요.</p>}
      {!effectiveWorkAreaId && areas.workAreas.length > 0 && <p className="text-[12px] text-ink-2">작업구역을 선택하면 해당 구역의 자료가 표시됩니다.</p>}
      {effectiveAreaNotice && <p className="text-[12px] text-ink-muted" role="status">{effectiveAreaNotice}</p>}

      {pageError !== null && <div>{errorView(pageError, "catalog", siteId, effectiveWorkAreaId ? pageHref(siteId, effectiveWorkAreaId) : undefined)}</div>}
      {page && <>
        {page.workAreaId !== effectiveWorkAreaId || page.siteId !== siteId ? <ErrorState message="Core 응답의 현장·작업구역 범위가 요청과 일치하지 않아 자산을 표시하지 않았습니다." tone="high" /> : <>
          {assetRef && detailError && <div>{errorView(detailError, "detail", siteId, effectiveWorkAreaId ? pageHref(siteId, effectiveWorkAreaId) : undefined)}</div>}
          {assetRef && detail && (detail.assetRef !== assetRef || detail.siteId !== siteId || detail.workAreaId !== effectiveWorkAreaId)
            ? <ErrorState message="Core 응답 자산의 ID 또는 현장·작업구역 범위가 요청과 일치하지 않아 상세를 표시하지 않았습니다." tone="high" />
            : null}
          {/* 필터에 걸러진 선택은 목록 위에서 본다 — 커서 밖 선택도 잃지 않는다. */}
          {detailMatchesScope && detail && expandedAssetRef === null
            ? (detailBlock ?? <ErrorState message="Core 응답에 데이터 접근 또는 분석 상태 제한이 없어 상세를 표시하지 않았습니다." tone="high" />)
            : null}
          {/* 집계는 한 줄 요약으로 — 0인 칸은 색 없이, 확인할 것만 강조한다. */}
          <div className="flex flex-col gap-2.5">
          <div>
            <p className="text-[12px] text-ink-2">
              불러온 {formatCountKo(catalogCounts.total)} · 검사 완료 {formatCountKo(catalogCounts.inspected)}
              {catalogCounts.attention > 0 && <span className="font-semibold text-high-ink"> · 확인 필요 {formatCountKo(catalogCounts.attention)}</span>}
              {page.hasMore && <span className="text-ink-muted"> · 이번에 불러온 {formatCountKo(catalogCounts.total)}건 기준</span>}
            </p>
            <p className="mt-0.5 text-[11.5px] text-ink-muted">여러 작업구역에 함께 연결된 기록은 제외합니다.</p>
          </div>
          {page.assets.length === 0
            ? <EmptyState compact title="이 작업구역에 등록된 자료가 없습니다" description="관측 자료가 이 작업구역에 등록되면 해당 자료의 메타데이터가 여기에 표시됩니다." />
            : filteredAssets.length === 0
              ? <EmptyState compact title="조건에 맞는 자료가 없습니다" description="검색어나 필터를 바꿔 다시 찾아보세요." />
              : <ul className="flex flex-col divide-y divide-line">
                {observationGroups.flatMap((group, groupIndex) => {
                  const dateLine = observationGroupDateLine(group.items);
                  const dividerLabel = dateLine ?? (group.epochId === ""
                    ? "관측 묶음 확인 불가"
                    : "촬영 구간이 항목마다 다름");
                  return [
                    <li key={group.epochId === "" ? "divider-unidentified" : `divider-${group.epochId}`} className={groupIndex === 0 ? "pb-1" : "pt-3 pb-1"}>
                      <h3 className="text-[12px] font-bold text-ink-muted">{dividerLabel} · {formatCountKo(group.items.length)}</h3>
                    </li>,
                    ...group.items.map((item) => {
                      if (!isMetadataOnly(item)) {
                        return <li key={item.assetRef}><ErrorState message="Core 응답에 데이터 접근 또는 분석 상태 제한이 없어 해당 항목을 숨겼습니다." tone="high" /></li>;
                      }
                      const open = expandedAssetRef === item.assetRef;
                      return <li key={item.assetRef}>
                        <AssetRow
                          item={item}
                          headline={businessTitleFor(item)}
                          toggleHref={pageHref(siteId, item.workAreaId, open ? { ...(cursor ? { cursor } : {}) } : { assetRef: item.assetRef, ...(cursor ? { cursor } : {}) }, visualContext, filters)}
                          toggleLabel={open ? "닫기" : "상세 보기"}
                          open={open}
                          expanded={open && detailBlock ? <div className="pb-3 sm:pl-14">{detailBlock}</div> : null}
                          nameIsDuplicated={duplicatedNames.has(item.declared.fileName)}
                        />
                      </li>;
                    }),
                  ];
                })}
                {outOfScopeAssets.map((item) => (
                  <li key={item.assetRef}><ErrorState message="Core 응답 자산의 현장·작업구역 범위가 일치하지 않아 해당 항목을 숨겼습니다." tone="high" /></li>
                ))}
              </ul>}
          </div>
          <nav aria-label="등록 자료 페이지" className="flex flex-wrap gap-2 pt-1">
            {cursor && effectiveWorkAreaId && <Link className="btn" href={pageHref(siteId, effectiveWorkAreaId, {}, visualContext, filters)}>처음부터 보기</Link>}
            {page.hasMore && page.nextCursor && effectiveWorkAreaId && <Link className="btn btn-primary" href={pageHref(siteId, effectiveWorkAreaId, { cursor: page.nextCursor }, visualContext, filters)}>다음 자산 보기</Link>}
          </nav>
        </>}
      </>}
    </div>
  </div>;
}
