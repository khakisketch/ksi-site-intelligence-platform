"use client";

import dynamic from "next/dynamic";
import { useMemo } from "react";
import type { ChangeRegionSetReport } from "@/lib/core-api/types";
import {
  partitionSurveyRegionDisplay,
  unsupportedSurveyRegionsNote,
} from "@/lib/geo/survey-region-geometry";
import { SkeletonBlock } from "@/components/ui/Skeleton";

const Inner = dynamic(
  () => import("./SurveyRegionMapInner").then((module) => module.SurveyRegionMapInner),
  { ssr: false, loading: () => <SkeletonBlock className="h-80" /> },
);

export function SurveyRegionMap(props: {
  report: ChangeRegionSetReport;
  selectedId: string | null;
  onSelect: (regionId: string | null) => void;
}) {
  const { supported, unsupported } = useMemo(
    () => partitionSurveyRegionDisplay(props.report.regions),
    [props.report.regions],
  );
  const omittedNote = unsupportedSurveyRegionsNote(unsupported);

  if (props.report.regions.length === 0) {
    return (
      <section aria-label="후보 구역 지도">
        <p className="rounded border border-line px-3 py-6 text-center text-sm leading-6 text-ink-2">
          후보 구역이 없습니다.
          {props.report.filteredRegionCount > 0
            ? ` 최소면적 미만으로 제외된 후보가 ${props.report.filteredRegionCount}개 있습니다.`
            : " 변화가 감지되지 않았거나 아직 계산되지 않은 상태와 구분하려면 계산 시각·정책 스냅샷을 확인하세요."}
        </p>
      </section>
    );
  }

  return (
    <section aria-label="후보 구역 지도">
      {supported.length > 0 ? (
        <Inner shapes={supported} selectedId={props.selectedId} onSelect={props.onSelect} />
      ) : (
        <p className="rounded border border-line px-3 py-6 text-center text-sm leading-6 text-ink-2">
          그릴 수 있는 후보 구역이 없습니다. 아래 사유를 확인하세요.
        </p>
      )}
      {props.report.filteredRegionCount > 0 && (
        <p role="note" className="mt-2 text-xs leading-5 text-ink-2">
          {`최소면적 미만으로 제외된 후보 ${props.report.filteredRegionCount}개는 지도에 표시되지 않습니다.`}
        </p>
      )}
      {omittedNote && (
        <p role="note" className="mt-2 text-xs leading-5 text-ink-2">{omittedNote}</p>
      )}
      <p className="mt-2 text-xs leading-5 text-ink-2">
        후보 구역의 볼록 껍질 경계입니다. 등록 경계선이 아닌 계산 결과의 껍질이며, 배경 지도는 현장 관측
        영상이 아닙니다. 물량 크기·정확도·정산 적합성을 나타내지 않습니다.
      </p>
    </section>
  );
}
