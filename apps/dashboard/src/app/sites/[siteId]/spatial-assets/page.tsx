import { visualBrowsingReturnHref, type VisualBrowsingContext } from "@/lib/operator-journey";
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
import { listSpatialDataRequests } from "@/lib/core-api/spatial-data-requests";
import {
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
import { visualLayersForExactSubmission } from "../site-visual-pair";
import { extractSimpleRing, planeUnitForCrs, sameDisplayPlane, selectableGeometry } from "../site-spatial";
import { nativeBoundsFromInspection } from "@/lib/spatial-data-request";
import { SiteMosaicAbsentDiagram } from "../SiteMosaicAbsentDiagram";
import {
  firstReadableWindowJob,
  toPreparedWindowJob,
  type PreparedWindowJob,
} from "@/lib/site-windowed-pixel-viewer";
import { SiteWindowedPixelViewer } from "../SiteWindowedPixelViewer";
import { MaterialThumb } from "./MaterialThumb";
import {
  groupAssetsByObservation,
  isViewableRasterKind,
  materialsHref,
  observationGroupDateLine,
  resolveVisualSelection,
  shortKindLabel,
  type MaterialsScope,
} from "./materials-visual";

export const metadata = { title: "등록 자료 · KSI" };

type SearchValue = string | string[] | undefined;
type SearchParams = { workAreaId?: SearchValue; cursor?: SearchValue; assetRef?: SearchValue; visualAAssetRef?: SearchValue; visualBAssetRef?: SearchValue; q?: SearchValue; kind?: SearchValue; state?: SearchValue; info?: SearchValue };

/** 목록 필터. Core 카탈로그는 정렬·검색 계약을 따로 받지 않으므로, 불러온
 *  페이지 안에서만 적용하고 그 범위를 화면에 밝힌다. */
interface CatalogFilters {
  q: string;
  kind: string;
  state: "" | "inspected" | "attention";
}

function singleQueryValue(value: SearchValue): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
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

/** 상태 점 — 목록 첫 화면의 유일한 상태 표시. 정확한 문구는 title과 정보 펼침이 맡는다. */
function RailStatusDot({ item }: { item: SpatialAssetCatalogItem }) {
  const attention = needsAttention(item);
  const label = attention
    ? `확인 필요 · ${inspectionOutcomeLabel(item.inspection.outcome)}`
    : `파일 검사 · ${inspectionOutcomeLabel(item.inspection.outcome)}`;
  const tone = attention ? "bg-high-ink" : item.inspection.outcome === "MEASURED" ? "bg-safe-ink" : "bg-ink-muted";
  return <span title={label} className={`mt-1 inline-block size-2 shrink-0 rounded-full ${tone}`}><span className="sr-only">{label}</span></span>;
}

/** 파일 타일 — 제출된 파일의 형식만 말한다. 픽셀이 없으므로 썸네일인 척하지 않는다. */
function FileKindTile({ fileName }: { fileName: string }) {
  const ext = fileName.includes(".") ? fileName.split(".").pop()!.toUpperCase().slice(0, 4) : "FILE";
  return <span aria-hidden="true" className="flex h-[54px] w-[72px] shrink-0 items-center justify-center rounded-md border border-line bg-sunk font-mono text-[10px] font-bold text-ink-2">{ext}</span>;
}

/**
 * 탐색 레일 항목 — 두 줄로 끝낸다. 정확한 날짜는 묶음 머리에서 한 번만
 * 말하고, 항목은 종류·버전·파일명으로 가른다. 누르면 큰 미리보기가 바뀌고,
 * 파일 사실과 검사 근거는 정보 펼침에서만 본다.
 */
function RailItem({ item, headline, viewHref, putBHref, isA, isB, showThumb, thumbJobs, siteId }: {
  item: SpatialAssetCatalogItem;
  /** 레일 한 줄 제목 — 짧은 종류·등록 버전. */
  headline: string;
  /** 이 자료를 A(왼쪽·단일)로 보는 주소. */
  viewHref: string;
  /** 이 자료를 B(오른쪽)로 두는 주소. */
  putBHref: string;
  isA: boolean;
  isB: boolean;
  showThumb: boolean;
  /** 이미 읽은 준비 기록 — 썸네일도 이 목록에서만 고른다. */
  thumbJobs: readonly PreparedWindowJob[];
  siteId: string;
}) {
  const role = isA && isB ? "A·B" : isA ? "A" : isB ? "B" : null;
  const readable = showThumb ? firstReadableWindowJob(thumbJobs, item.assetRef) : null;
  return <div className={`flex min-w-0 items-start gap-2 rounded-md px-1.5 py-1.5 ${isA || isB ? "bg-sunk" : ""}`}>
    {readable && readable.receipt
      ? <MaterialThumb siteId={siteId} workAreaId={item.workAreaId} jobId={readable.jobId} receipt={readable.receipt} fileName={item.declared.fileName} />
      : <FileKindTile fileName={item.declared.fileName} />}
    <div className="min-w-0 flex-1">
      <p className="flex min-w-0 items-start gap-1 break-words text-[12.5px] font-semibold leading-snug">
        {role && <span className="mt-0.5 shrink-0 rounded bg-surface px-1 text-[10.5px] font-bold" aria-label={`현재 ${role}로 선택됨`}>{role}</span>}
        <Link href={viewHref} aria-current={isA ? "true" : undefined} className="min-w-0 tap-target underline-offset-2 hover:underline">{headline}</Link>
        <RailStatusDot item={item} />
      </p>
      <p className="mt-0.5 truncate text-[11.5px] text-ink-2" title={item.declared.fileName}>{item.declared.fileName}</p>
      <p className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[11.5px]">
        <Link href={viewHref} className="tap-target underline decoration-dotted text-ink-2" aria-label={`${headline} A로 보기`}>A로 보기</Link>
        <Link href={putBHref} className="tap-target underline decoration-dotted text-ink-2" aria-label={`${headline} B에 두기`}>B에 두기</Link>
      </p>
    </div>
  </div>;
}

function FactStatus({ item }: { item: SpatialAssetCatalogItem }) {
  const inspectionText = inspectionOutcomeLabel(item.inspection.outcome);
  return <div className="mt-3 flex flex-col gap-1 text-[12.5px] text-ink-2">
    <p>제출자 입력 정보 있음</p>
    <p>{item.observed ? "저장 파일 확인 기록 있음" : "저장 파일 확인 기록 없음"}</p>
    <p>파일 검사: {inspectionText}</p>
  </div>;
}

function DeclaredFacts({ item }: { item: SpatialAssetCatalogItem }) {
  const declared = item.declared;
  return <section className="rounded-lg border border-line bg-surface p-4">
    <h3 className="text-[14px] font-bold">제출자가 입력한 정보</h3>
    <dl className="mt-3 grid gap-3 text-[12.5px]">
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
    <dl className="mt-3 grid gap-3 text-[12.5px]">
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
    <dl className="mt-3 grid gap-3 text-[12.5px]">
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
  // 바깥 틀이 경계를 이미 졌으므로 안쪽은 한 줄씩만 둔다. 320px 정보
  // 판에서도 읽히게 사실 쌍은 세로 한 줄로 둔다.
  return <section aria-label="관측 자료 상세" className="flex flex-col gap-2.5 rounded-lg border border-line bg-surface p-3 sm:p-4">
    <header>
      <p className="sr-only">관측 자료 상세</p>
      <h4 className="break-words text-[16px] font-bold tracking-tight">{headline}</h4>
      <p className="mt-0.5 text-[12px] text-ink-2">{areaName} · 등록 버전 {item.revision}</p>
    </header>
    {/* 상세 첫 화면은 파일명이 아니라 이 자료가 무엇이고 어디까지 확인됐는지다. */}
    <dl className="grid gap-x-3 gap-y-2 py-1">
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
    <div className="grid gap-2">
      <details className="rounded-lg border border-line bg-surface p-3 text-[12px]"><summary className="tap-target cursor-pointer font-semibold">제출자 입력 정보</summary><DeclaredFacts item={item} /></details>
      <details className="rounded-lg border border-line bg-surface p-3 text-[12px]"><summary className="tap-target cursor-pointer font-semibold">저장 파일 확인</summary><ObservedFacts item={item} /></details>
    </div>
    <InspectionFacts inspection={item.inspection} />
    <details className="rounded-lg border border-line bg-surface p-3 text-[12px]"><summary className="tap-target cursor-pointer font-semibold">파일·참조 정보</summary><TechnicalFileInfo item={item} workName={workName} areaName={areaName} /></details>
    <p className="text-[11.5px] leading-5 text-ink-muted">파일 검사 완료는 형식·격자 확인이며, 측량·정산 근거나 분석 사용 가능 판정이 아닙니다.</p>
    {item.lifecycleState !== "SEALED" && <p className="text-[11.5px] leading-5 text-high-ink">제출 상태가 {assetLifecycleLabel(item.lifecycleState)}이므로 유효한 분석 입력으로 취급하지 않습니다.</p>}
  </section>;
}

/** 펼친 본문 — 상세·등록 이력·받기 요청을 한 덩어리로 둔다. */
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

/**
 * 한쪽 미리보기 — 래스터(정사영상/DSM)는 같은 제출 묶음의 정확한 층으로
 * 실제 픽셀을 두고, 그 밖의 형식은 파일형 본문으로 둔다. 절대 다른 자료의
 * 대표 화면을 가져오지 않으며, 새 준비 요청은 만들지 않는다(읽기 전용).
 * 목록 접근 제한이 있는 자료는 미리보기에 올리지 않는다.
 */
function PreviewPane({ siteId, workAreaId, item, pool, jobs, jobsState, canRead, canRequest, requestsHref, workAreaRing, workAreaCrs, side, siblingHrefBase }: {
  siteId: string;
  workAreaId: string;
  item: SpatialAssetCatalogItem;
  pool: readonly SpatialAssetCatalogItem[];
  jobs: readonly PreparedWindowJob[];
  jobsState: "ready" | "denied" | "unavailable";
  canRead: boolean;
  canRequest: boolean;
  requestsHref: string;
  workAreaRing: Array<[number, number]> | null;
  workAreaCrs: string;
  /** "A" | "B" — 층 전환 주소의 쿼리 키를 정한다. */
  side: "A" | "B";
  /** 층 전환 링크의 바탕 주소(같은 쪽 참조를 갈아끼운다). */
  siblingHrefBase: string;
}) {
  if (!isMetadataOnly(item)) {
    return <ErrorState message="Core 응답에 데이터 접근 또는 분석 상태 제한이 없어 미리보기를 표시하지 않았습니다." tone="high" />;
  }
  if (!isViewableRasterKind(item.kind)) {
    return <div className="flex min-w-0 flex-col items-start gap-2 rounded-lg border border-line bg-surface px-4 py-6">
      <FileKindTile fileName={item.declared.fileName} />
      <p className="break-words text-[13px] font-bold">{dataKindLabel(item.kind)}</p>
      <p className="break-all text-[12px] text-ink-2">파일명 · {item.declared.fileName}</p>
      <p className="text-[12px] text-ink-2">파일 검사 · {inspectionOutcomeLabel(item.inspection.outcome)}</p>
      <p className="text-[12px] leading-5 text-ink-2">이 형식은 미리보기를 두지 않습니다. 바이트를 그림으로 바꾸지 않으며, 파일 사실은 선택 자료 정보에서 확인하세요.</p>
    </div>;
  }
  const layers = visualLayersForExactSubmission(pool, item);
  const param = side === "A" ? "visualAAssetRef" : "visualBAssetRef";
  const heading = `${dataKindLabel(item.kind)} · ${capturePeriodTitle(item.declared.captureStartedAt, item.declared.captureEndedAt, { captureDate: item.declared.captureDate ?? null })}`;
  // 픽셀 유무와 무관하게 중앙 시각을 둔다 — 검사 격자에서 유도한
  // 범위 도식(사진 아님)을 먼저 둔다. 픽셀을 흉내내지 않으며, 아래 뷰어의
  // 정직한 상태·복구 문구는 그대로 둔다. 픽셀이 복구되면 도식은 파일 전체
  // 범위 맥락으로 남는다.
  const raster = item.inspection.raster;
  const fileBounds = raster ? nativeBoundsFromInspection(raster) : null;
  const fileRing: Array<[number, number]> | null = fileBounds
    ? [[fileBounds[0], fileBounds[1]], [fileBounds[2], fileBounds[1]], [fileBounds[2], fileBounds[3]], [fileBounds[0], fileBounds[3]]]
    : null;
  const overlaid = fileRing !== null
    && workAreaRing !== null
    && workAreaRing.length >= 3
    && raster?.observedCrsIdentifier != null
    && sameDisplayPlane(workAreaCrs, raster.observedCrsIdentifier);
  const overlayNote = !fileRing ? null
    : !workAreaRing || workAreaRing.length < 3
      ? "작업구역 경계를 확인하지 못해 파일 범위만 단독으로 둡니다."
      : !raster?.observedCrsIdentifier
        ? "위치 기준을 확인하지 못해 작업구역 경계를 겹쳐 표시하지 않았습니다. 파일 범위만 단독으로 둡니다."
        : !overlaid
          ? "위치 기준이 달라 작업구역 경계를 겹쳐 표시하지 않았습니다. 파일 범위만 단독으로 둡니다."
          : null;
  return <div className="flex min-w-0 flex-col gap-2">
  {fileRing && raster && <SiteMosaicAbsentDiagram
    fileRing={fileRing}
    workAreaRing={workAreaRing}
    overlaid={overlaid}
    overlayNote={overlayNote}
    crsLabel={raster.observedCrsIdentifier ?? "확인 불가"}
    planeUnit={raster.observedCrsIdentifier ? planeUnitForCrs(raster.observedCrsIdentifier) : "unknown"}
    filePixelSize={{ width: raster.width, height: raster.height }}
    fileExtentLabel={raster.observedCrsIdentifier ? `${raster.observedCrsIdentifier} 네이티브 평면 ${raster.width} × ${raster.height} 픽셀` : null}
  />}
  <SiteWindowedPixelViewer
    siteId={siteId}
    workAreaId={workAreaId}
    layers={layers}
    jobs={[...jobs]}
    jobsState={jobsState}
    canRead={canRead}
    canRequest={canRequest}
    requestsHref={requestsHref}
    workAreaRing={workAreaRing}
    workAreaCrs={workAreaCrs}
    observationHeading={heading}
    idPrefix={`materials-${side.toLowerCase()}`}
    slimHeader
    selectedAssetRef={item.assetRef}
    layerSelectHref={siblingHrefBase}
    layerSelectParam={param as "visualAAssetRef" | "visualBAssetRef"}
    hidePrepareActions
    presentation="canvas"
  />
  </div>;
}

async function readCatalogOutcome(siteId: string, workAreaId: string, cursor: string | undefined) {
  try {
    return { ok: true as const, page: await listSpatialAssets(siteId, workAreaId, { limit: 50, cursor }) };
  } catch (error) {
    return { ok: false as const, error };
  }
}

async function readDetailOutcome(siteId: string, workAreaId: string, assetRef: string) {
  try {
    return { ok: true as const, detail: await getSpatialAsset(siteId, workAreaId, assetRef) };
  } catch (error) {
    return { ok: false as const, error };
  }
}

async function readJobsOutcome(siteId: string, workAreaId: string, canRead: boolean) {
  if (!canRead) return { ok: false as const, denied: true as const };
  try {
    return { ok: true as const, page: await listSpatialDataRequests(siteId, workAreaId, { limit: 50 }) };
  } catch (error) {
    return { ok: false as const, denied: error instanceof CoreApiError && error.status === 403, error };
  }
}

async function readNamesOutcome(siteId: string, organizationId: string) {
  try {
    return { ok: true as const, orders: await listObservationWorkOrders(siteId) };
  } catch {
    return { ok: false as const, organizationId };
  }
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
    return <div className="mx-auto max-w-5xl p-4 sm:p-5"><ErrorState message="페이지 커서가 올바르지 않습니다. 목록을 처음부터 다시 열어 주세요." tone="high" action={{ label: "처음부터 보기", href: effectiveWorkAreaId ? materialsHref(siteId, effectiveWorkAreaId) : basePath }} /></div>;
  }
  if (Array.isArray(assetRefParam) || (typeof assetRefParam === "string" && !/^ksa-v1-[0-9a-f]{64}$/.test(assetRefParam))) {
    return <div className="mx-auto max-w-5xl p-4 sm:p-5"><ErrorState message="자산 참조가 올바르지 않습니다." tone="high" action={{ label: "목록으로 돌아가기", href: effectiveWorkAreaId ? materialsHref(siteId, effectiveWorkAreaId) : basePath }} /></div>;
  }
  const cursor = singleQueryValue(cursorParam);
  const assetRef = singleQueryValue(assetRefParam);
  // 시각 쌍 참조는 모양만 본다 — 어긋나면 그쪽만 비우고 알린다. 조용히
  // 다른 자료로 바꾸지 않는다(아래 resolveVisualSelection).
  const visualARaw = query.visualAAssetRef;
  const visualBRaw = query.visualBAssetRef;
  const infoOpen = singleQueryValue(query.info) === "1";

  const canRequestAnalysis = session.principal.permissions.includes("SITES_WRITE");
  const canRequestData = session.principal.permissions.includes("SPATIAL_DATA_REQUEST");
  const canReadData = session.principal.permissions.includes("SPATIAL_DATA_READ");

  // 독립 읽기는 함께 나간다 — 카탈로그·상세·준비 기록·작업명은 서로를
  // 기다리지 않는다. 실패는 각 자리에서만 다루고 빈 목록으로 단정하지 않는다.
  const [catalogOutcome, detailOutcome, jobsOutcome, namesOutcome] = await Promise.all([
    effectiveWorkAreaId ? readCatalogOutcome(siteId, effectiveWorkAreaId, cursor) : Promise.resolve(null),
    assetRef && effectiveWorkAreaId ? readDetailOutcome(siteId, effectiveWorkAreaId, assetRef) : Promise.resolve(null),
    effectiveWorkAreaId ? readJobsOutcome(siteId, effectiveWorkAreaId, canReadData) : Promise.resolve(null),
    readNamesOutcome(siteId, session.principal.organizationId),
  ]);

  const page = catalogOutcome?.ok === true ? catalogOutcome.page : null;
  const pageError: unknown = catalogOutcome?.ok === false ? catalogOutcome.error : null;
  const rawDetail = detailOutcome?.ok === true ? detailOutcome.detail : null;
  const detailError: unknown = detailOutcome?.ok === false ? detailOutcome.error : null;

  // 작업 지시 이름은 사람용 표시 전용이다. 이 조회가 실패해도 목록·상세는
  // "작업명 확인 불가"로 그대로 표시되며, 존재·권한·적합성을 추정하지 않는다.
  let workOrderNames: Record<string, string> | null = null;
  if (namesOutcome.ok) {
    const names: Record<string, string> = {};
    for (const order of namesOutcome.orders) {
      if (order.siteId !== siteId || order.organizationId !== session.principal.organizationId) continue;
      if (typeof order.name === "string" && order.name.trim().length > 0) names[order.workOrderId] = order.name;
    }
    workOrderNames = names;
  }

  const detailMatchesScope = rawDetail !== null
    && assetRef !== undefined
    && rawDetail.assetRef === assetRef
    && rawDetail.siteId === siteId
    && rawDetail.workAreaId === effectiveWorkAreaId;
  const detail = detailMatchesScope ? rawDetail : null;

  const businessTitles = page ? assetBusinessTitles(page.assets) : new Map<string, string>();
  const businessTitleFor = (item: SpatialAssetCatalogItem): string =>
    businessTitles.get(item.assetRef) ?? assetBusinessTitle(item);
  const railHeadlineFor = (item: SpatialAssetCatalogItem): string =>
    `${shortKindLabel(item.kind)} · 등록 버전 ${item.revision}`;
  const areaDisplayName = selectedArea?.name ?? effectiveWorkAreaId ?? "";
  // 목록은 관측 묶음(관측 기록 ID) 단위로 접는다 — Core 반환 순서를 유지하고
  // 시간으로 재정열하지 않는다. 범위 밖 항목은 묶음에 넣지 않고 그대로 둔다.
  const inScopeAssets = page && page.siteId === siteId && page.workAreaId === effectiveWorkAreaId
    ? page.assets.filter((item) => item.siteId === siteId && item.workAreaId === effectiveWorkAreaId)
    : [];
  const selectionPool: SpatialAssetCatalogItem[] = [...inScopeAssets];
  if (detail && !selectionPool.some((item) => item.assetRef === detail.assetRef)) {
    selectionPool.push(detail);
  }
  const outOfScopeCount = page && page.siteId === siteId && page.workAreaId === effectiveWorkAreaId
    ? page.assets.filter((item) => item.siteId !== siteId || item.workAreaId !== effectiveWorkAreaId).length
    : 0;

  // 커서 페이지 밖에 있는 명시 선택도 같은 범위에서 최대 2건까지 직접 읽는다.
  // 403/404는 존재를 드러내지 않는 불투명 실패로 두고, 모양이 어긋난 값은
  // 읽지 않는다. 조용히 다른 자료로 바꾸지 않는다.
  if (effectiveWorkAreaId && page?.siteId === siteId && page.workAreaId === effectiveWorkAreaId) {
    const poolRefs = new Set(selectionPool.map((item) => item.assetRef));
    const wanted: string[] = [];
    for (const raw of [visualARaw, visualBRaw]) {
      if (typeof raw === "string" && /^ksa-v1-[0-9a-f]{64}$/.test(raw) && !poolRefs.has(raw) && !wanted.includes(raw)) {
        wanted.push(raw);
      }
    }
    const fetched = await Promise.all(wanted.slice(0, 2).map(async (ref) => {
      try {
        const candidate = await getSpatialAsset(siteId, effectiveWorkAreaId, ref);
        return candidate.assetRef === ref && candidate.siteId === siteId && candidate.workAreaId === effectiveWorkAreaId
          ? candidate
          : null;
      } catch {
        return null;
      }
    }));
    for (const candidate of fetched) {
      if (candidate && !poolRefs.has(candidate.assetRef)) {
        poolRefs.add(candidate.assetRef);
        selectionPool.push(candidate);
      }
    }
  }

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
      const haystack = `${item.declared.fileName} · ${dataKindLabel(item.kind)} · ${shortKindLabel(item.kind)}`.toLowerCase();
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
  // 시각 선택 해소 — 명시 참조는 정확히 맞을 때만 쓰고, 없으면 목록 첫
  // 자료를 A 기본값으로 둔다. B는 미리 고르지 않는다.
  const selection = resolveVisualSelection({
    pool: selectionPool,
    visualARaw,
    visualBRaw,
    legacyRef: assetRef,
  });
  const sideA = selection.sideA;
  const sideB = selection.sideB;
  const compareMode = selection.mode === "compare";
  // 헤더 맥락은 정확한 선택 그대로만 싣는다. A/B의 시간 순서·우열을
  // 짓지 않으므로 baseline/current 힌트를 만들지 않는다.
  const headerVisualContext = compareMode && sideA && sideB && effectiveWorkAreaId
    ? {
        workAreaId: effectiveWorkAreaId,
        visualAAssetRef: sideA.assetRef,
        visualBAssetRef: sideB.assetRef,
      }
    : null;
  const workspaceReturnHref = headerVisualContext && effectiveWorkAreaId
    ? visualBrowsingReturnHref(`/sites/${encodeURIComponent(siteId)}`, headerVisualContext satisfies VisualBrowsingContext, effectiveWorkAreaId) : null;

  // 선택한 쪽의 제출서 이력 — 각 쪽 최대 1건의 bounded 읽기다. 목록 N+1
  // 조회가 아니며, 실패해도 파일 사실은 그대로 둔다.
  const historyByRef = new Map<string, ReturnType<typeof validateRegistrationHistory>>();
  for (const side of [sideA, sideB]) {
    if (!side || !isMetadataOnly(side) || historyByRef.has(side.assetRef)) continue;
    if (side.assetRef === detail?.assetRef && detailMatchesScope) continue;
    try {
      const record = await getExternalReconstructionSubmission(side.workOrderId, side.submissionRef, side.revision);
      historyByRef.set(side.assetRef, validateRegistrationHistory(record, {
        submissionRef: side.submissionRef,
        revision: side.revision,
        siteId: side.siteId,
        organizationId: session.principal.organizationId,
        observationEpochId: side.observationEpochId,
      }));
    } catch {
      historyByRef.set(side.assetRef, { kind: "unavailable" });
    }
  }
  // 옛 assetRef 진입의 상세 이력은 그대로 재사용한다 — 같은 자산이면 두 번 읽지 않는다.
  let legacyHistory: ReturnType<typeof validateRegistrationHistory> | null = null;
  if (detailMatchesScope && detail && [sideA, sideB].some((side) => side?.assetRef === detail.assetRef)) {
    try {
      const record = await getExternalReconstructionSubmission(detail.workOrderId, detail.submissionRef, detail.revision);
      legacyHistory = validateRegistrationHistory(record, {
        submissionRef: detail.submissionRef,
        revision: detail.revision,
        siteId: detail.siteId,
        organizationId: session.principal.organizationId,
        observationEpochId: detail.observationEpochId,
      });
    } catch {
      legacyHistory = { kind: "unavailable" };
    }
    if (!historyByRef.has(detail.assetRef)) historyByRef.set(detail.assetRef, legacyHistory);
  }

  const compareHrefFor = (item: SpatialAssetCatalogItem): string | null =>
    canRequestAnalysis && effectiveWorkAreaId && isMetadataOnly(item)
      ? (() => {
          const hint = new URLSearchParams();
          hint.set("workAreaId", effectiveWorkAreaId);
          hint.set("hintCurrentWorkOrderId", item.workOrderId);
          hint.set("hintCurrentSubmissionRef", item.submissionRef);
          hint.set("hintCurrentRevision", String(item.revision));
          if (headerVisualContext) {
            hint.set("visualAAssetRef", headerVisualContext.visualAAssetRef);
            hint.set("visualBAssetRef", headerVisualContext.visualBAssetRef);
          }
          return `/sites/${encodeURIComponent(siteId)}/analysis?${hint.toString()}#new-analysis-request`;
        })()
      : null;
  // 모든 이동 링크는 현재 A/B 쌍을 싣는다 — 페이지·필터·정보 전환이
  // 선택을 잃지 않는다. 구역이 바뀌는 이동에서만 쌍을 버린다.
  // Info/filter/paging actions must not clear an explicit failed selection and
  // thereby trigger the default A on the next request. Keep exact requested refs;
  // malformed input is represented by a harmless invalid marker, never echoed.
  const retainedARef = sideA?.assetRef ?? (selection.notices.invalidA || selection.notices.foreignA
    ? typeof visualARaw === "string" && /^ksa-v1-[0-9a-f]{64}$/.test(visualARaw) ? visualARaw : "invalid"
    : null);
  const retainedBRef = sideB?.assetRef ?? (selection.notices.invalidB || selection.notices.foreignB
    ? typeof visualBRaw === "string" && /^ksa-v1-[0-9a-f]{64}$/.test(visualBRaw) ? visualBRaw : "invalid"
    : null);
  const scopeForLinks = (overrides: Partial<MaterialsScope> = {}): MaterialsScope => ({
    ...(filters.q ? { q: filters.q } : {}),
    ...(filters.kind ? { kind: filters.kind } : {}),
    ...(filters.state ? { state: filters.state } : {}),
    ...(assetRef ? { assetRef } : {}),
    visualA: retainedARef,
    visualB: retainedBRef,
    ...(infoOpen ? { info: "1" } : {}),
    ...overrides,
  });
  const detailBlockFor = (item: SpatialAssetCatalogItem): ReactNode => {
    if (!isMetadataOnly(item)) {
      return <ErrorState message="Core 응답에 데이터 접근 또는 분석 상태 제한이 없어 상세를 표시하지 않았습니다." tone="high" />;
    }
    return <DetailBlock
      detail={item}
      workName={resolveWorkName(item.workOrderId, workOrderNames)}
      areaName={areaDisplayName}
      headline={businessTitleFor(item)}
      compareHref={compareHrefFor(item)}
      retryHref={retryBase}
      historyResult={historyByRef.get(item.assetRef) ?? null}
      requestProps={{ siteId, workAreaId: effectiveWorkAreaId!, inspectedRaster: item.inspection.raster, canRequest: canRequestData }}
    />;
  };

  // 준비 기록(읽기 전용) — 실패는 denied/unavailable로만 두고 빈 목록으로
  // 단정하지 않는다. 새 준비 요청을 만들지 않으며, 바이트 권한을 새로 만들지도 않는다.
  let preparedJobs: PreparedWindowJob[] = [];
  let jobsState: "ready" | "denied" | "unavailable" = "unavailable";
  if (effectiveWorkAreaId) {
    if (jobsOutcome === null || (!jobsOutcome.ok && jobsOutcome.denied)) {
      jobsState = "denied";
    } else if (jobsOutcome.ok) {
      preparedJobs = jobsOutcome.page.items
        .filter((job) => job.siteId === siteId && job.workAreaId === effectiveWorkAreaId)
        .map(toPreparedWindowJob);
      jobsState = "ready";
    }
  }
  const geometry = selectedArea ? selectableGeometry(selectedArea) : null;
  const workAreaRing = geometry ? extractSimpleRing(geometry.polygon) : null;
  const workAreaCrs = geometry?.crs ?? "확인 불가";
  const requestsHref = retryBase ?? `/sites/${encodeURIComponent(siteId)}/spatial-data-requests`;
  const siblingBaseFor = (side: "A" | "B"): string => {
    if (!effectiveWorkAreaId) return basePath;
    const base: MaterialsScope = { ...scopeForLinks(), cursor: cursor ?? null };
    if (side === "A") {
      if (sideB) base.visualB = sideB.assetRef;
    } else {
      if (sideA) base.visualA = sideA.assetRef;
    }
    return materialsHref(siteId, effectiveWorkAreaId, base);
  };

  // 레일 썸네일 예산 — 처음 8개만, 이미 읽은 준비 기록에서만 고른다.
  const thumbRefs = new Set(filteredAssets.slice(0, 8).map((item) => item.assetRef));

  const railFilters = (idSuffix: string) => effectiveWorkAreaId ? (
    <details className="rounded-md border border-line bg-surface px-2 py-1.5 text-[12px]">
      <summary className="tap-target cursor-pointer font-semibold">검색·필터{filtersAreActive(filters) ? " · 적용 중" : ""}</summary>
      <SiteSelectionForm action={basePath} className="mt-1.5 flex min-w-0 flex-col gap-2">
        <input type="hidden" name="workAreaId" value={effectiveWorkAreaId} />
        {retainedARef && <input type="hidden" name="visualAAssetRef" value={retainedARef} />}
        {retainedBRef && <input type="hidden" name="visualBAssetRef" value={retainedBRef} />}
        {assetRef && <input type="hidden" name="assetRef" value={assetRef} />}
        {infoOpen && <input type="hidden" name="info" value="1" />}
        <label className="flex min-w-0 flex-col gap-1 font-semibold" htmlFor={`spatial-q-${idSuffix}`}>검색
          <input id={`spatial-q-${idSuffix}`} name="q" type="search" defaultValue={filters.q} maxLength={80} placeholder="파일명 또는 자료 유형" className="input min-w-0" />
        </label>
        <label className="flex min-w-0 items-center gap-1.5 font-semibold" htmlFor={`spatial-kind-${idSuffix}`}>유형
          <select id={`spatial-kind-${idSuffix}`} name="kind" className="input min-w-0 flex-1" defaultValue={filters.kind}>
            <option value="">전체 유형</option>
            {availableKinds.map((kind) => <option key={kind} value={kind}>{dataKindLabel(kind)}</option>)}
          </select>
        </label>
        <label className="flex min-w-0 items-center gap-1.5 font-semibold" htmlFor={`spatial-state-${idSuffix}`}>검사
          <select id={`spatial-state-${idSuffix}`} name="state" className="input min-w-0 flex-1" defaultValue={filters.state}>
            <option value="">전체</option>
            <option value="inspected">검사 완료</option>
            <option value="attention">확인 필요</option>
          </select>
        </label>
        {filtersAreActive(filters) && <Link className="tap-target text-[12px] underline text-ink-2" href={materialsHref(siteId, effectiveWorkAreaId, scopeForLinks({ q: "", kind: "", state: "" }))}>필터 초기화</Link>}
      </SiteSelectionForm>
    </details>
  ) : null;

  const railGroups = (
    <div className="flex min-w-0 flex-col gap-3">
      {observationGroups.map((group) => {
        const dateLine = observationGroupDateLine(group.items);
        const dividerLabel = dateLine ?? (group.epochId === ""
          ? "관측 묶음 확인 불가"
          : "촬영 구간이 항목마다 다름");
        return <section key={group.epochId === "" ? "divider-unidentified" : `divider-${group.epochId}`} aria-label={dividerLabel} className="min-w-0">
          <h4 className="px-1.5 pb-1 text-[12px] font-bold text-ink-muted">{dividerLabel} · {formatCountKo(group.items.length)}</h4>
          <ul className="flex min-w-0 flex-col divide-y divide-line">
            {group.items.map((item) => {
              const isA = sideA?.assetRef === item.assetRef;
              const isB = sideB?.assetRef === item.assetRef;
              const viewHref = effectiveWorkAreaId
                ? materialsHref(siteId, effectiveWorkAreaId, scopeForLinks({
                    visualA: item.assetRef,
                    visualB: sideB && sideB.assetRef !== item.assetRef ? sideB.assetRef : null,
                  }))
                : basePath;
              const putBHref = effectiveWorkAreaId
                ? materialsHref(siteId, effectiveWorkAreaId, scopeForLinks({
                    visualA: sideA?.assetRef ?? item.assetRef,
                    visualB: item.assetRef,
                  }))
                : basePath;
              return <li key={item.assetRef} className="min-w-0">
                <RailItem
                  item={item}
                  headline={railHeadlineFor(item)}
                  viewHref={viewHref}
                  putBHref={putBHref}
                  isA={isA}
                  isB={isB}
                  showThumb={thumbRefs.has(item.assetRef)}
                  thumbJobs={preparedJobs}
                  siteId={siteId}
                />
              </li>;
            })}
          </ul>
        </section>;
      })}
    </div>
  );

  const centerPane = (side: "A" | "B", item: SpatialAssetCatalogItem, heading: string) => (
    <div className="flex min-w-0 flex-col gap-1.5">
      <h3 className="min-w-0 break-words text-[13px] font-bold">{side} · {heading}</h3>
      <PreviewPane
        siteId={siteId}
        workAreaId={item.workAreaId}
        item={item}
        pool={selectionPool}
        jobs={preparedJobs}
        jobsState={jobsState}
        canRead={canReadData}
        canRequest={canRequestData}
        requestsHref={requestsHref}
        workAreaRing={workAreaRing}
        workAreaCrs={workAreaCrs}
        side={side}
        siblingHrefBase={siblingBaseFor(side)}
      />
    </div>
  );

  return <div className="flex min-w-0 flex-col">
    <SiteHeader
      site={site}
      selectedEpochId={null}
      tab="materials"
      variant="compact"
      canCreateWorkOrder={session.principal.permissions.includes("WORK_ORDERS_WRITE")}
      canEditAoi={canRequestAnalysis}
      scopedWorkAreaId={effectiveWorkAreaId && selectedArea ? effectiveWorkAreaId : null}
      scopedAssetRef={sideA ? sideA.assetRef : null}
      visualContext={headerVisualContext}
    />
    <div className="mx-auto flex w-full max-w-6xl min-w-0 flex-col gap-2 overflow-x-clip px-4 py-3 sm:px-5">
      <h2 className="sr-only">자료</h2>
      {/* 한 줄 도구모음 — 구역·보기 방식·정보·등록만 둔다. 검색·필터는 레일에서 펼친다. */}
      <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1.5">
        {areas.workAreas.length > 1 ? (
          <SiteSelectionForm action={basePath} className="flex min-w-0 items-center gap-1.5">
            {infoOpen && <input type="hidden" name="info" value="1" />}
            <label className="flex min-w-0 items-center gap-1.5 text-[12px] font-semibold" htmlFor="spatial-work-area">작업구역
              <select id="spatial-work-area" name="workAreaId" className="input min-w-0 w-auto max-w-44" defaultValue={effectiveWorkAreaId ?? ""} required>
                <option value="" disabled>선택</option>
                {areas.workAreas.map((area) => <option key={area.workAreaId} value={area.workAreaId}>{area.name}{area.status === "ARCHIVED" ? " · 보관됨" : ""}</option>)}
              </select>
            </label>
          </SiteSelectionForm>
        ) : selectedArea ? (
          <p className="min-w-0 truncate text-[12px] font-semibold">작업구역 · {areaDisplayName}{selectedArea.status === "ARCHIVED" ? " (보관됨)" : ""}</p>
        ) : null}
        <span className="shrink-0 rounded bg-sunk px-1.5 py-0.5 text-[11.5px] font-bold">{compareMode ? "A·B 보기" : "단일 보기"}</span>
        {compareMode && effectiveWorkAreaId && (
          <Link className="tap-target shrink-0 text-[12px] underline text-ink-2" href={materialsHref(siteId, effectiveWorkAreaId, scopeForLinks({ visualB: null }))}>한 장 보기로</Link>
        )}
        {effectiveWorkAreaId && (infoOpen
          ? <Link className="tap-target shrink-0 text-[12px] font-semibold underline" href={materialsHref(siteId, effectiveWorkAreaId, scopeForLinks({ info: null }))}>정보 닫기</Link>
          : <Link className="tap-target shrink-0 text-[12px] underline text-ink-2" href={materialsHref(siteId, effectiveWorkAreaId, scopeForLinks({ info: "1" }))}>정보</Link>)}
        <span className="ml-auto flex shrink-0 items-center gap-2">
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
          <details className="relative text-[12.5px]">
            <summary className="tap-target cursor-pointer list-none rounded-md border border-line bg-surface px-2.5 py-1.5 font-semibold text-ink-2">더 보기</summary>
            <div className="absolute right-0 z-10 mt-1 flex min-w-44 flex-col gap-1 rounded-md border border-line bg-surface p-1.5 shadow-lg">
              <Link className="tap-target rounded px-2 py-1.5 hover:bg-sunk" href={`/sites/${encodeURIComponent(siteId)}/spatial-data-requests${effectiveWorkAreaId ? `?workAreaId=${encodeURIComponent(effectiveWorkAreaId)}` : ""}`}>구역 자료 준비</Link>
              <Link className="tap-target rounded px-2 py-1.5 hover:bg-sunk" href={`/sites/${encodeURIComponent(siteId)}/observations`}>외부 비교 기록</Link>
              <Link className="tap-target rounded px-2 py-1.5 hover:bg-sunk" href={`/sites/${encodeURIComponent(siteId)}?section=work-orders${effectiveWorkAreaId ? `&workAreaId=${encodeURIComponent(effectiveWorkAreaId)}` : ""}`}>관측 작업 기록</Link>
              {workspaceReturnHref && <Link className="tap-target rounded px-2 py-1.5 hover:bg-sunk" href={workspaceReturnHref}>작업공간에서 나란히 보기</Link>}
            </div>
          </details>
        </span>
      </div>

      {areas.workAreas.length === 0 && <p className="text-[12.5px] leading-5 text-ink-2">현장에 등록된 작업구역이 없습니다. 자료를 확인하려면 작업구역을 먼저 등록하세요.</p>}
      {!effectiveWorkAreaId && areas.workAreas.length > 0 && <p className="text-[12px] text-ink-2">작업구역을 선택하면 해당 구역의 자료가 표시됩니다.</p>}
      {effectiveAreaNotice && <p className="text-[12px] text-ink-muted" role="status">{effectiveAreaNotice}</p>}

      {pageError !== null && <div>{errorView(pageError, "catalog", siteId, effectiveWorkAreaId ? materialsHref(siteId, effectiveWorkAreaId) : undefined)}</div>}
      {page && <>
        {(page.workAreaId !== effectiveWorkAreaId || page.siteId !== siteId) ? <ErrorState message="Core 응답의 현장·작업구역 범위가 요청과 일치하지 않아 자산을 표시하지 않았습니다." tone="high" /> : <>
          {assetRef && detailError && <div>{errorView(detailError, "detail", siteId, effectiveWorkAreaId ? materialsHref(siteId, effectiveWorkAreaId) : undefined)}</div>}
          {assetRef && rawDetail && (rawDetail.assetRef !== assetRef || rawDetail.siteId !== siteId || rawDetail.workAreaId !== effectiveWorkAreaId)
            ? <ErrorState message="Core 응답 자산의 ID 또는 현장·작업구역 범위가 요청과 일치하지 않아 상세를 표시하지 않았습니다." tone="high" />
            : null}
          {selection.notices.invalidA && <p role="status" className="text-[12px] text-high-ink">첫 자료(A)의 참조가 올바르지 않습니다. 다른 자료로 대체하지 않았습니다.</p>}
          {selection.notices.foreignA && <p role="status" className="text-[12px] text-high-ink">선택한 첫 자료를 현재 목록에서 확인하지 못했습니다. 다른 자료로 대체하지 않았습니다.</p>}
          {selection.notices.invalidB && <p role="status" className="text-[12px] text-high-ink">두 번째 자료(B)의 참조가 올바르지 않습니다. 다른 자료로 대체하지 않았습니다.</p>}
          {selection.notices.foreignB && <p role="status" className="text-[12px] text-high-ink">선택한 두 번째 자료를 현재 목록에서 확인하지 못했습니다. 다른 자료로 대체하지 않았습니다.</p>}
          {selection.notices.samePair && <p role="status" className="text-[12px] text-ink-2">같은 자료를 두 번 선택했습니다. 한 장 보기로 둡니다.</p>}

          {page.assets.length === 0 && !sideA && !sideB
            ? <EmptyState compact title="이 작업구역에 등록된 자료가 없습니다" description="관측 자료가 이 작업구역에 등록되면 해당 자료의 메타데이터가 여기에 표시됩니다." />
            : <div className={`grid min-w-0 items-stretch gap-3 lg:h-[calc(100dvh-240px)] lg:min-h-[430px] lg:grid-cols-[248px_minmax(0,1fr)] xl:grid-cols-[264px_minmax(0,1fr)] ${infoOpen ? "xl:grid-cols-[264px_minmax(0,1fr)_320px]" : ""}`}>
              {/* 왼쪽: 관측 묶음 탐색 레일. 독립 스크롤이며, 누르면 중앙 미리보기가 바뀐다. */}
              <aside aria-label="자료 목록" className="hidden min-w-0 rounded-lg border border-line bg-surface p-2 lg:block lg:h-full lg:min-h-0 lg:overflow-y-auto">
                <h3 className="px-1.5 pb-1 text-[12px] font-bold text-ink-muted">
                  자료 · 불러온 {formatCountKo(catalogCounts.total)} · 검사 완료 {formatCountKo(catalogCounts.inspected)}
                  {catalogCounts.attention > 0 && <span className="font-semibold text-high-ink"> · 확인 필요 {formatCountKo(catalogCounts.attention)}</span>}
                </h3>
                {page.hasMore && <p className="px-1.5 pb-1 text-[11.5px] text-ink-muted">이번에 불러온 {formatCountKo(catalogCounts.total)}건 기준</p>}
                {outOfScopeCount > 0 && <p className="px-1.5 pb-1 text-[11.5px] text-ink-muted">여러 작업구역에 함께 연결된 기록 {formatCountKo(outOfScopeCount)}건은 제외합니다.</p>}
                {railFilters("rail")}
                {filteredAssets.length === 0
                  ? <p className="px-1.5 py-3 text-[12px] text-ink-2">조건에 맞는 자료가 없습니다. 검색어나 필터를 바꿔 다시 찾아보세요.</p>
                  : railGroups}
              </aside>

              {/* 중앙: 큰 미리보기. 단일 또는 좌·우 독립 보기. 동기화·정합을 주장하지 않는다.
                  휴대폰에서는 미리보기가 목록보다 먼저다. */}
              <section aria-label={compareMode ? "선택한 두 자료 미리보기" : "선택한 자료 미리보기"} className="flex min-w-0 flex-col gap-2 rounded-lg border border-line bg-surface p-2 sm:p-3 lg:col-start-2 lg:row-start-1 lg:h-full lg:min-h-0 lg:overflow-y-auto">
                {!sideA && <p role="status" className="text-[12.5px] leading-5 text-ink-2">{sideB ? "첫 자료(A)를 목록에서 고르세요. 선택한 B는 그대로 표시합니다." : "표시할 자료를 목록에서 고르세요. 자동으로 다른 자료를 보여주지 않습니다."}</p>}
                {!sideA && sideB && centerPane("B", sideB, businessTitleFor(sideB))}
                {sideA && !compareMode && <>
                  <p className="min-w-0 break-words text-[11.5px] text-ink-muted">
                    {selection.legacyMapped ? "옛 주소의 선택을 그대로 읽었습니다" : selection.defaultedA ? "목록 첫 자료" : "선택한 자료"}
                  </p>
                  {centerPane("A", sideA, businessTitleFor(sideA))}
                  <p className="text-[11.5px] leading-5 text-ink-muted">두 시점을 나란히 보려면 목록에서 다른 자료를 「B에 두기」로 고르세요. 겹쳐 맞춤·차분 계산을 하지 않습니다.</p>
                </>}
                {sideA && sideB && compareMode && <>
                  <p className="text-[11.5px] leading-5 text-ink-muted">각 칸은 독립된 보기이며, 같은 범위 맞춤·같은 색 눈금을 지원하지 않습니다. 화면을 겹쳐도 분석 근거가 되지 않습니다.</p>
                  <div className={`grid min-w-0 gap-3 ${infoOpen ? "grid-cols-1" : "md:grid-cols-2"}`}>
                    {centerPane("A", sideA, businessTitleFor(sideA))}
                    {centerPane("B", sideB, businessTitleFor(sideB))}
                  </div>
                  <ComparePlaneNote sideA={sideA} sideB={sideB} />
                </>}
              </section>

              {/* 휴대폰 레일 — 미리보기 아래 접힌 목록. */}
              <details className="min-w-0 rounded-lg border border-line bg-surface p-2 lg:hidden">
                <summary className="tap-target cursor-pointer px-1.5 py-1 text-[13px] font-bold">
                  자료 목록 · {formatCountKo(filteredAssets.length)} (불러온 {formatCountKo(catalogCounts.total)})
                </summary>
                <div className="mt-1 flex min-w-0 flex-col gap-2">
                  {railFilters("rail-mobile")}
                  {filteredAssets.length === 0
                    ? <p className="px-1.5 py-2 text-[12px] text-ink-2">조건에 맞는 자료가 없습니다. 검색어나 필터를 바꿔 다시 찾아보세요.</p>
                    : railGroups}
                </div>
              </details>

              {/* 오른쪽: 선택 자료 정보 — info=1일 때만 proper grid 열을 차지한다. */}
              {infoOpen && effectiveWorkAreaId && (
                <section id="material-inspector" aria-label="선택 자료 정보" className="flex min-w-0 scroll-mt-3 flex-col gap-3 rounded-lg border border-line bg-surface p-3 text-[12px] leading-5 text-ink-2 lg:fixed lg:inset-y-0 lg:right-0 lg:z-30 lg:w-[min(340px,92vw)] lg:overflow-y-auto lg:rounded-none lg:border-y-0 lg:border-l lg:shadow-2xl xl:static xl:z-auto xl:col-start-3 xl:row-start-1 xl:h-full xl:min-h-0 xl:w-auto xl:overflow-y-auto xl:rounded-lg xl:border xl:shadow-none">
                  <div className="flex min-w-0 items-center justify-between gap-2">
                    <h3 className="min-w-0 break-words text-[13px] font-bold">선택 자료 정보</h3>
                    <Link className="tap-target shrink-0 text-[12px] underline text-ink-2" href={materialsHref(siteId, effectiveWorkAreaId, scopeForLinks({ info: null }))}>닫기</Link>
                  </div>
                  {!sideA && !sideB && <p>표시할 자료를 목록에서 고르세요.</p>}
                  {sideA && <>
                    <h4 className="break-words text-[13px] font-bold">A · {businessTitleFor(sideA)}</h4>
                    {detailBlockFor(sideA)}
                  </>}
                  {sideB && <>
                    <h4 className="break-words text-[13px] font-bold">B · {businessTitleFor(sideB)}</h4>
                    {detailBlockFor(sideB)}
                  </>}
                </section>
              )}
            </div>}
          <nav aria-label="등록 자료 페이지" className="flex min-w-0 flex-wrap gap-2 pt-1">
            {cursor && effectiveWorkAreaId && <Link className="btn" href={materialsHref(siteId, effectiveWorkAreaId, scopeForLinks({ cursor: null }))}>처음부터 보기</Link>}
            {page.hasMore && page.nextCursor && effectiveWorkAreaId && <Link className="btn btn-primary" href={materialsHref(siteId, effectiveWorkAreaId, scopeForLinks({ cursor: page.nextCursor }))}>다음 자산 보기</Link>}
          </nav>
        </>}
      </>}
    </div>
  </div>;
}

/**
 * 나란히 두기의 정합 한계 한 줄 — 두 자료의 위치 기준 표기가 다르면 그
 * 이유를 밝힌다. 격자·정합 판정을 새로 만들지 않는다.
 */
function ComparePlaneNote({ sideA, sideB }: {
  sideA: SpatialAssetCatalogItem;
  sideB: SpatialAssetCatalogItem;
}) {
  const crsA = sideA.inspection.raster?.observedCrsIdentifier ?? null;
  const crsB = sideB.inspection.raster?.observedCrsIdentifier ?? null;
  if (!isViewableRasterKind(sideA.kind) || !isViewableRasterKind(sideB.kind)) return null;
  if (!crsA || !crsB) {
    return <p className="text-[11.5px] leading-5 text-ink-muted">두 자료의 위치 기준을 확인하지 못해 나란히 두기의 전제를 두지 않습니다. 각 자료는 따로 볼 수 있습니다.</p>;
  }
  if (crsA !== crsB) {
    return <p className="text-[11.5px] leading-5 text-ink-muted">두 자료의 위치 기준이 달라({crsA} · {crsB}) 같은 화면 맞춤으로 읽지 마세요. 각 자료는 따로 볼 수 있습니다.</p>;
  }
  return <p className="text-[11.5px] leading-5 text-ink-muted">두 칸은 같은 위치 기준({crsA})의 작업구역 경계와 함께 둡니다. 화면 맞춤이 실제 지형 일치를 뜻하지 않습니다.</p>;
}
