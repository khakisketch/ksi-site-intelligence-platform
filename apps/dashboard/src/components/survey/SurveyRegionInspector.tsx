"use client";

import type { ChangeRegionSetReport } from "@/lib/core-api/types";
import { formatCountKo, formatNumberKo } from "@/lib/number-format";

/**
 * `designConformanceId`가 `survey:` 로 시작하면 전수측량 실행 id 로만 다룬다 —
 * 설계 정합 리포트로 해석·조회하지 않는다(Task 1 인계 a).
 */
export function describeSurveyReference(designConformanceId: string): {
  kind: "survey-run" | "design-conformance";
  id: string;
} {
  if (designConformanceId.startsWith("survey:")) {
    return { kind: "survey-run", id: designConformanceId.slice("survey:".length) };
  }
  return { kind: "design-conformance", id: designConformanceId };
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1">
      <dt className="text-xs text-ink-2">{label}</dt>
      <dd className="text-sm font-medium tabular-nums">{value}</dd>
    </div>
  );
}

export function SurveyRegionInspector(props: {
  report: ChangeRegionSetReport;
  selectedId: string | null;
}) {
  const reference = describeSurveyReference(props.report.designConformanceId);
  const region = props.selectedId
    ? (props.report.regions.find((item) => item.regionId === props.selectedId) ?? null)
    : null;

  return (
    <section aria-label="후보 구역 지표" className="rounded border border-line px-3 py-2">
      <p className="text-xs leading-5 text-ink-2">
        {reference.kind === "survey-run"
          ? `전수측량 실행 ${reference.id}`
          : `설계 정합 ${reference.id}`}
        {` · 정책 ${props.report.extractionPolicy.policyVersion}`}
      </p>
      {region === null ? (
        <p className="py-3 text-center text-sm leading-6 text-ink-2">
          {props.selectedId === null
            ? "지도에서 후보 구역을 선택하면 지표를 표시합니다."
            : `선택한 후보(${props.selectedId})가 이 계산에 없습니다. 목록에서 다시 선택하세요.`}
        </p>
      ) : (
        <dl className="mt-1 divide-y divide-line">
          <Row label="후보" value={region.regionId} />
          <Row label="절토" value={`${formatNumberKo(region.volume.cutM3)} ㎥`} />
          <Row label="성토" value={`${formatNumberKo(region.volume.fillM3)} ㎥`} />
          <Row label="순변화" value={`${formatNumberKo(region.volume.netM3)} ㎥`} />
          <Row label="면적" value={`${formatNumberKo(region.volume.areaM2)} ㎡`} />
          <Row label="픽셀 수" value={`${formatCountKo(region.pixelCount)} 개`} />
          <Row
            label="측정 불가 비율"
            value={formatNumberKo(region.unmeasurableRatio * 100)}
          />
          <Row
            label="껍질 과대포함 비율"
            value={
              region.hullOvercaptureRatio === null
                ? "계산 안 됨"
                : formatNumberKo(region.hullOvercaptureRatio)
            }
          />
          {region.aoiDraftUnavailableReason && (
            <Row label="껍질 미계산 사유" value={region.aoiDraftUnavailableReason} />
          )}
        </dl>
      )}
      <p className="mt-1 text-xs leading-5 text-ink-2">
        서버가 계산한 값의 표시이며, 판정·정산 적합성을 나타내지 않습니다.
      </p>
    </section>
  );
}
