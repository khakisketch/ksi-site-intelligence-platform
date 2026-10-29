"use client";

import dynamic from "next/dynamic";
import type { AnalysisCoverageWire, CoverageGridReference } from "@/lib/analysis-coverage";
import { SkeletonBlock } from "@/components/ui/Skeleton";

const Inner = dynamic(() => import("./AnalysisCoverageMapInner").then((module) => module.AnalysisCoverageMapInner), {
  ssr: false, loading: () => <SkeletonBlock className="h-80" />,
});

export function AnalysisCoverageMap(props: { witness: AnalysisCoverageWire; reference: CoverageGridReference }) {
  return <section className="mt-3" aria-label="계산 셀 위치 지도">
    <Inner {...props} />
    <p className="mt-2 text-xs leading-5 text-ink-2">검사 근거의 좌표계·기준 격자에 연결한 셀 위치입니다. 등록 경계선이 아닌 계산 셀의 경계이며, 배경 지도는 현장 관측 영상이 아닙니다. 물량 크기·정확도·정산 적합성을 나타내지 않습니다.</p>
  </section>;
}
