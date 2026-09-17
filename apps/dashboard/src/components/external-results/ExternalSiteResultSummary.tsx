import Link from "next/link";

import {
  ExternalVolumeKindBadge,
  isSingleVolumeResult,
  SINGLE_VOLUME_REVIEW_PENDING,
  SingleVolumeResult,
} from "@/components/external-results/SingleVolumeResult";
import { StateBadge } from "@/components/ui/StatusBadge";
import { formatKoreanDateTime } from "@/lib/datetime";
import type { ExternalResultProjectionView, ExternalResultSummaryView } from "@/lib/core-api/types";

function formatNumber(value: number, maximumFractionDigits = 2): string {
  return value.toLocaleString("ko-KR", { maximumFractionDigits });
}

function formatSignedNumber(value: number, maximumFractionDigits = 2): string {
  const rendered = formatNumber(value, maximumFractionDigits);
  return value > 0 ? `+${rendered}` : rendered;
}

function observationRange(from: string, to: string): string {
  const start = formatKoreanDateTime(from, { dateStyle: "medium", timeStyle: "short" });
  const end = formatKoreanDateTime(to, { dateStyle: "medium", timeStyle: "short" });
  return start === end ? start : `${start} ~ ${end}`;
}

/** Relative results only — a single-volume result is summarized by `SingleVolumeSummary`. */
function comparisonCopy(result: ExternalResultSummaryView, workAreaName: string | null | undefined): string {
  const areaLabel = workAreaName ?? result.workAreaId;
  const currentRange = observationRange(result.currentCapturedFrom, result.currentCapturedTo);
  if (result.baselineCapturedFrom === null || result.baselineCapturedTo === null) {
    return `작업구역 ${areaLabel} · ${currentRange}`;
  }
  const baselineRange = observationRange(result.baselineCapturedFrom, result.baselineCapturedTo);
  return `작업구역 ${areaLabel} · ${baselineRange}와 ${currentRange}를 비교했습니다.`;
}

function resultLink(result: ExternalResultSummaryView): string {
  return `/field/work-orders/${encodeURIComponent(result.currentWorkOrderId)}?reportRef=${encodeURIComponent(result.reportRef)}#external-result`;
}

function availabilityCopy(state: Exclude<ExternalResultProjectionView["state"], "AVAILABLE">): string {
  switch (state) {
    case "NOT_CONFIGURED":
      return "외부 관측 결과 연결이 아직 설정되지 않았습니다.";
    case "NO_RESULT":
      return "외부 관측 결과가 아직 없습니다.";
    case "HISTORICAL_SOURCE_UNAVAILABLE":
      return "외부 관측 결과의 보관 근거를 현재 확인할 수 없습니다.";
  }
}

function measurementCopy(result: ExternalResultSummaryView): { label: string; tone: "positive" | "caution" | "progress" } {
  if (result.measurementStatus === "SUCCEEDED" && result.metrics !== null) {
    return { label: "비교 결과 준비됨", tone: "positive" };
  }
  if (result.measurementStatus === "FAILED") {
    return { label: "비교 결과 확인 필요", tone: "caution" };
  }
  return { label: "비교 결과 확인 중", tone: "progress" };
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="border-l border-line px-3 first:border-l-0 first:pl-0">
      <dt className="text-[12px] font-semibold text-ink-muted">{label}</dt>
      <dd className="num mt-1 text-[20px] font-bold tracking-tight text-ink-1">{value}</dd>
    </div>
  );
}

function singleMeasurementCopy(result: ExternalResultSummaryView): { label: string; tone: "positive" | "caution" | "progress" } {
  if (result.measurementStatus === "SUCCEEDED" && result.metrics !== null) {
    return { label: "체적 결과 준비됨", tone: "positive" };
  }
  if (result.measurementStatus === "FAILED") {
    return { label: "체적 결과 확인 필요", tone: "caution" };
  }
  return { label: "체적 결과 확인 중", tone: "progress" };
}

/**
 * Core's `for_site()` merges both external volume families, so the latest result can be
 * a single-epoch stockpile volume: one capture window, no baseline, no net change.
 */
function SingleVolumeSummary({
  result,
  compact,
  workAreaName,
}: {
  result: ExternalResultSummaryView;
  compact: boolean;
  workAreaName: string | null | undefined;
}) {
  const metrics = result.measurementStatus === "SUCCEEDED" ? result.metrics : null;
  const measurement = singleMeasurementCopy(result);
  return (
    <section className="rounded-lg border border-line bg-surface">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-4 py-3">
        <div className="min-w-0">
          <h3 className="text-[15px] font-bold tracking-tight break-keep">단일 시점 체적 결과</h3>
          <p className="mt-1 text-[13px] leading-5 break-keep text-ink-2">
            작업구역 {workAreaName ?? result.workAreaId} · 촬영 {observationRange(result.currentCapturedFrom, result.currentCapturedTo)}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <ExternalVolumeKindBadge single />
          <StateBadge label={measurement.label} tone={measurement.tone} />
        </div>
      </div>

      {metrics ? (
        <div className="px-4 py-4">
          <SingleVolumeResult
            fillM3={metrics.fillM3}
            uncertaintyM3={metrics.uncertaintyM3}
            uncertaintyNote={metrics.uncertaintyNote}
            baseRoughnessM={metrics.baseRoughnessM}
            boundaryValidFraction={metrics.boundaryValidFraction}
          />
        </div>
      ) : (
        <p className="px-4 py-3 text-[13px] leading-5 break-keep text-ink-2">
          {result.measurementStatus === "FAILED"
            ? "체적 측정을 완료하지 못했습니다. 결과 수치는 표시하지 않습니다."
            : "측정이 완료되면 체적 수치가 표시됩니다."}
        </p>
      )}

      {!compact && (
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-4 py-3">
          <p className="text-[12px] break-keep text-ink-muted">{SINGLE_VOLUME_REVIEW_PENDING}</p>
          <Link
            href={`/field/work-orders/${encodeURIComponent(result.currentWorkOrderId)}#external-volume`}
            className="btn shrink-0 print:hidden"
          >
            체적 측정 기록 보기
          </Link>
        </div>
      )}
    </section>
  );
}

/**
 * One exact Core-retained external result. It deliberately does not aggregate
 * Site history or use managed processing results as a fallback.
 */
export function ExternalSiteResultSummary({
  externalResult,
  compact = false,
  workAreaName,
}: {
  externalResult: ExternalResultProjectionView;
  compact?: boolean;
  /** The Site page may resolve the human name; result provenance always remains the WorkArea id. */
  workAreaName?: string | null;
}) {
  if (externalResult.state !== "AVAILABLE") {
    return (
      <section className="rounded-lg border border-line bg-surface px-4 py-3">
        <h3 className="text-[14px] font-bold tracking-tight break-keep">외부 관측 비교 결과</h3>
        <p className="mt-1 text-[13px] leading-5 break-keep text-ink-2">
          {availabilityCopy(externalResult.state)}
        </p>
      </section>
    );
  }

  if (externalResult.result === null || externalResult.result === undefined) {
    return (
      <section className="rounded-lg border border-line bg-surface px-4 py-3">
        <h3 className="text-[14px] font-bold tracking-tight break-keep">외부 관측 비교 결과</h3>
        <p className="mt-1 text-[13px] leading-5 break-keep text-ink-2">비교 결과를 아직 확인할 수 없습니다.</p>
      </section>
    );
  }

  const result = externalResult.result;
  if (isSingleVolumeResult(result)) {
    return <SingleVolumeSummary result={result} compact={compact} workAreaName={workAreaName} />;
  }
  const metrics = result.measurementStatus === "SUCCEEDED" ? result.metrics : null;
  const measurement = measurementCopy(result);

  return (
    <section className="rounded-lg border border-line bg-surface">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-4 py-3">
        <div className="min-w-0">
          <h3 className="text-[15px] font-bold tracking-tight break-keep">외부 관측 비교 결과</h3>
          <p className="mt-1 text-[13px] leading-5 break-keep text-ink-2">
            {comparisonCopy(result, workAreaName)}
          </p>
        </div>
        <StateBadge label={measurement.label} tone={measurement.tone} />
      </div>

      {metrics ? (
        <>
          <dl className="grid grid-cols-3 divide-x divide-line px-4 py-4">
            <Metric label="절토" value={`${formatNumber(metrics.cutM3)} m³`} />
            <Metric label="성토" value={`${formatNumber(metrics.fillM3)} m³`} />
            <Metric label="순변화" value={`${formatSignedNumber(metrics.netM3)} m³`} />
          </dl>
          <div className="border-t border-line bg-sunk px-4 py-3 text-[13px] leading-5 text-ink-2">
            <p>
              측정 영역 {formatNumber(metrics.measuredAreaM2, 1)} m² / 작업구역 {formatNumber(metrics.zoneAreaM2, 1)} m² · 공통 유효 영역 {formatNumber(metrics.commonValidFraction * 100, 1)}%
            </p>
            <p className="mt-1">
              {metrics.uncertaintyM3 === null
                ? `불확실성은 아직 산정되지 않았습니다. ${metrics.uncertaintyNote}`
                : `불확실성 ±${formatNumber(metrics.uncertaintyM3)} m³ · ${metrics.uncertaintyNote}`}
            </p>
            <p className="mt-1 text-[12px] text-ink-muted">절토는 깎아낸 양, 성토는 채워 넣은 양입니다.</p>
          </div>
        </>
      ) : (
        <p className="px-4 py-3 text-[13px] leading-5 break-keep text-ink-2">
          {result.measurementStatus === "FAILED"
            ? "비교를 완료하지 못했습니다. 결과 수치는 표시하지 않습니다."
            : "비교가 완료되면 결과 수치가 표시됩니다."}
        </p>
      )}

      {!compact && (
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-4 py-3">
          <p className="text-[12px] break-keep text-ink-muted">
            {result.reviewedAt ? "결과 검토 기록이 있습니다." : "결과를 확인한 뒤 검토 또는 추가 관측을 선택할 수 있습니다."}
          </p>
          <Link href={resultLink(result)} className="btn btn-primary shrink-0 print:hidden">
            비교 결과 보기
          </Link>
        </div>
      )}
    </section>
  );
}
