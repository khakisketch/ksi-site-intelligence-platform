import Link from "next/link";

import { AssetRequestDialog } from "../spatial-assets/AssetRequestDialog";
import { AssetProvenanceNote } from "../spatial-assets/AssetProvenanceNote";
import { SpatialDataRequestAction } from "../spatial-assets/SpatialDataRequestAction";
import { RegistrationHistoryFacts, RegistrationHistoryUnavailable } from "../spatial-assets/RegistrationHistoryFacts";
import { Disclosure } from "@/components/ui/Disclosure";
import { StateBadge } from "@/components/ui/StatusBadge";
import { formatKoreanDateTime } from "@/lib/datetime";
import { formatBytesKo, formatCountKo } from "@/lib/number-format";
import { capturePeriodTitle, dataKindLabel, isSupportedDataKind, isSupportedLifecycleState } from "@/lib/operator-language";
import type { validateRegistrationHistory } from "@/lib/registration-history";
import type { SpatialAssetCatalogItem, SpatialAssetInspection, SpatialAssetInspectedRasterFacts } from "@/lib/core-api/spatial-assets";

function TechnicalFileInfo({ item, workName, areaName }: { item: SpatialAssetCatalogItem; workName?: string | null; areaName?: string }) {
  return <div className="flex flex-col gap-1 break-all text-caption text-ink-2">
      <p>등록 파일명 · {item.declared.fileName}</p>
      {areaName && <p>작업구역명 · {areaName}</p>}
      <p>등록된 작업명 · {workName ?? "확인 불가"}</p>
      <p>제출 참조 · {item.submissionRef} · 등록 버전 {item.revision}</p>
      <p>등록 버전은 제출한 자료 묶음의 버전이며 촬영 횟수와 다릅니다.</p>
      {!isSupportedDataKind(item.kind) && <p>등록 종류(원문) · {item.kind}</p>}
      {!isSupportedLifecycleState(item.lifecycleState) && <p>등록 상태(원문) · {item.lifecycleState}</p>}
      <p>자산 참조 · {item.assetRef}</p>
      <p>관측 기록 ID · {item.observationEpochId}</p>
      <p>작업 지시 ID · {item.workOrderId}</p>
      <p>원본 artifact ID · {item.artifactId}</p>
  </div>;
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

export function inspectionStateLabel(state: string): string {
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

interface AvailabilityStatus {
  label: string;
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
      retry: true,
    };
  }
  if (item.lifecycleState === "UNSEALED") {
    return { label: "파일 제출 미완료", retry: false };
  }
  if (item.lifecycleState === "SUPERSEDED") {
    return { label: "이전 등록 자료", retry: false };
  }
  const inspected = item.inspection.outcome === "MEASURED"
    ? "파일 정보 확인됨"
    : item.inspection.outcome === "NOT_APPLICABLE"
      ? "적용 대상 아님"
      : "검사 결과 확인 전";
  return {
    label: inspected,
    retry: false,
  };
}

function DeclaredFacts({ item }: { item: SpatialAssetCatalogItem }) {
  const declared = item.declared;
  return <section className="rounded-lg border border-line bg-surface p-4">
    <h3 className="text-lead font-bold">제출자가 입력한 정보</h3>
    <dl className="mt-3 grid gap-3 text-body">
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
    <p className="mt-3 text-micro leading-5 text-ink-muted">이 항목은 고객이 신고한 값이며 파일에서 확인한 사실이나 정확도 보증을 뜻하지 않습니다.</p>
  </section>;
}

function ObservedFacts({ item }: { item: SpatialAssetCatalogItem }) {
  if (!item.observed) return <section className="rounded-lg border border-line bg-surface p-4"><h3 className="text-lead font-bold">저장 파일 확인 정보</h3><p className="mt-2 text-body text-ink-2">제출 파일을 확인한 기록이 없습니다.</p></section>;
  const observed = item.observed;
  return <section className="rounded-lg border border-line bg-surface p-4">
    <h3 className="text-lead font-bold">저장 파일 확인 정보</h3>
    <dl className="mt-3 grid gap-3 text-body">
      <Fact label="관측 크기" value={exactByteCount(observed.sizeBytes)} />
      <Fact label="관측 MIME" value={observed.contentType} />
      <Fact label="관측 파일 확인값(SHA-256)" value={observed.sha256} mono />
      <Fact label="매니페스트 확인값" value={observed.manifestDigest} mono />
      <Fact label="KSI 관측 시각" value={formatKoreanDateTime(observed.observedAt, { dateStyle: "medium", timeStyle: "short" })} />
    </dl>
    <p className="mt-3 text-micro leading-5 text-ink-muted">바이트 관측은 파일의 공간적 의미나 분석 적합성을 확인한 결과가 아닙니다.</p>
  </section>;
}

function Fact({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return <div className="min-w-0"><dt className="text-micro text-ink-muted">{label}</dt><dd className={`mt-0.5 break-words text-ink-2 ${mono ? "break-all font-mono text-micro" : ""}`}>{value}</dd></div>;
}

function RasterFacts({ raster }: { raster: SpatialAssetInspectedRasterFacts }) {
  return <>
    <dl className="mt-3 grid gap-3 text-body">
      <Fact label="관측 좌표 기준" value={raster.observedCrsIdentifier} />
      <Fact label="격자 크기" value={`${formatCountKo(raster.width)} × ${formatCountKo(raster.height)} pixels`} />
      <Fact label="관측 좌표 기준 확인값" value={raster.observedCrsDigest} mono />
      <Fact label="검사 보고서 확인값" value={raster.sourceReportDigest} mono />
      <Fact label="검사 도구 빌드 확인값" value={raster.inspectorBuildDigest} mono />
      <Fact label="관측 수직 기준" value={raster.observedVerticalReference ? `${raster.observedVerticalReference.identifier} · ${raster.observedVerticalReference.basis}` : "관측되지 않음"} />
    </dl>
    <Disclosure label="격자 변환·포함 범위 상세" className="mt-3">
      <p className="mt-2 break-all font-mono">{raster.transform.join(", ")}</p>
      <p className="mt-2 break-all font-mono">{raster.footprintWkt}</p>
      <p className="mt-1 break-all font-mono text-ink-muted">범위 확인값: {raster.footprintDigest}</p>
    </Disclosure>
  </>;
}

function InspectionFacts({ inspection }: { inspection: SpatialAssetInspection }) {
  return <section className="rounded-lg border border-line bg-surface p-4">
    <h3 className="text-lead font-bold">파일 검사 결과</h3>
    <p className="mt-2 text-body text-ink-2">상태: {inspectionStateLabel(inspection.state)} · 결과: {inspectionOutcomeLabel(inspection.outcome)}</p>
    {inspection.reason && <p className="mt-1 text-caption text-ink-2">사유: {inspection.reason}</p>}
    <Disclosure label="좌표·격자와 검사 상세" className="mt-2">
    <p className="mt-1">검사 상태 코드 · {inspection.state}</p>
    {inspection.raster ? <RasterFacts raster={inspection.raster} /> : <p className="mt-2 text-caption text-ink-muted">파일에서 확인한 위치·격자 정보가 없습니다.</p>}
    {inspection.reportDigest && <p className="mt-2 break-all font-mono text-micro text-ink-muted">검사 보고서 확인값: {inspection.reportDigest}</p>}
    </Disclosure>
    <p className="mt-3 text-micro leading-5 text-ink-muted">형식·격자 정보 검사만 나타냅니다. 정확도, 좌표 기준의 현장 검증, 분석 적합성은 판정하지 않습니다.</p>
  </section>;
}

function CompactFact({ label, value }: { label: string; value: string }) {
  return <div className="min-w-0">
    <dt className="text-micro text-ink-muted">{label}</dt>
    <dd className="mt-0.5 break-words text-micro leading-4 font-semibold text-ink-2">{value}</dd>
  </div>;
}

/**
 * 선택 자료의 패널 본문 — 먼저 "무엇을 고른지, 지금 무엇을 할 수 있는지"만 둔다.
 * 등록 이력·제출자 입력·검사 원문은 `상세 정보` 안으로 접고, 준비 요청 폼은
 * 필요할 때만 모달로 연다. 정보 밀도가 선택 자체를 가리지 않게 하는 것이 목적이다.
 */
export function DetailBlock({ detail, workName, areaName, headline, compareHref, retryHref, requestsHref, historyResult, requestProps }: {
  detail: SpatialAssetCatalogItem;
  workName: string | null;
  areaName: string;
  headline: string;
  compareHref: string | null;
  retryHref: string | null;
  requestsHref: string;
  historyResult: ReturnType<typeof validateRegistrationHistory> | null;
  requestProps: { siteId: string; workAreaId: string; inspectedRaster: SpatialAssetCatalogItem["inspection"]["raster"]; canRequest: boolean };
}) {
  const availability = availabilityStatus(detail);
  const captureLine = capturePeriodTitle(detail.declared.captureStartedAt, detail.declared.captureEndedAt, {
    captureDate: detail.declared.captureDate ?? null,
  });
  const tone: "neutral" | "positive" | "warning" =
    availability.retry ? "warning" : detail.inspection.outcome === "MEASURED" ? "positive" : "neutral";
  const requestAction = <SpatialDataRequestAction
    siteId={requestProps.siteId}
    workAreaId={requestProps.workAreaId}
    assetRef={detail.assetRef}
    inspectedRaster={requestProps.inspectedRaster}
    observedCrsIdentifier={requestProps.inspectedRaster?.observedCrsIdentifier ?? null}
    observedCrsDigest={requestProps.inspectedRaster?.observedCrsDigest ?? null}
    canRequest={requestProps.canRequest}
  />;
  return <section aria-label="관측 자료 상세" id={`asset-${detail.assetRef}`} className="flex min-w-0 scroll-mt-4 flex-col gap-3">
    <h3 className="break-words text-lead font-bold text-ink-1">{headline}</h3>
    <StateBadge label={availability.label} tone={tone} />
    <dl className="grid grid-cols-2 gap-x-3 gap-y-2">
      <CompactFact label="자료 구성" value={`${dataKindLabel(detail.kind)} · ${detail.declared.format}`} />
      <CompactFact label="관측 시점" value={captureLine} />
      <CompactFact label="파일 검사" value={inspectionStateLabel(detail.inspection.state)} />
      <CompactFact label="좌표 기준" value={detail.inspection.raster?.observedCrsIdentifier ?? "확인 불가"} />
      <CompactFact label="수직 기준" value={detail.inspection.raster?.observedVerticalReference?.identifier ?? "확인 불가"} />
      {detail.inspection.raster && <CompactFact label="파일 범위" value={`${formatCountKo(detail.inspection.raster.width)} × ${formatCountKo(detail.inspection.raster.height)} 픽셀`} />}
    </dl>
    {availability.retry && retryHref && <p className="text-caption text-high-ink">처리 실패는 <Link className="tap-target underline" href={retryHref}>구역 자료 준비</Link>에서 확인하세요.</p>}
    {requestProps.canRequest && <AssetRequestDialog triggerLabel="이 자료 새로 준비 요청">{requestAction}</AssetRequestDialog>}
    {compareHref && <p className="text-caption">분석에 사용할 자료는 <Link href={compareHref} className="tap-target underline">분석 조건에서 선택</Link>하세요.</p>}
    <p className="text-caption">요청한 창은 <Link href={requestsHref} className="tap-target underline">준비 기록</Link>에서 확인하세요.</p>
    <AssetProvenanceNote siteId={detail.siteId} workAreaId={detail.workAreaId} assetRef={detail.assetRef} />
    <Disclosure label="파일·식별 상세" className="border-t border-line">
      <div className="flex min-w-0 flex-col gap-2">
        <TechnicalFileInfo item={detail} workName={workName} areaName={areaName} />
        <DeclaredFacts item={detail} />
        <ObservedFacts item={detail} />
        <InspectionFacts inspection={detail.inspection} />
        {historyResult?.kind === "v3" && <RegistrationHistoryFacts history={historyResult.history} />}
        {historyResult?.kind === "unavailable" && <RegistrationHistoryUnavailable />}
      </div>
    </Disclosure>
  </section>;
}
