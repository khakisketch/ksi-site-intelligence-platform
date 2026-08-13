"use client";

import dynamic from "next/dynamic";
import { useCallback, useState } from "react";

import { SkeletonBlock } from "@/components/ui/Skeleton";
import { DIFF_CELL_COLOR, DIFF_CELL_LABEL, type DiffCellClass } from "@/lib/design-conformance";
import type { DiffLoadState } from "./DiffHeatmapOverlayInner";

// leaflet·georaster 는 window/document/canvas 를 직접 참조해 SSR 불가 —
// 클라이언트 전용 로드(OrthophotoOverlay 와 같은 관용구).
const DiffHeatmapOverlayInner = dynamic(
  () => import("./DiffHeatmapOverlayInner").then((m) => m.DiffHeatmapOverlayInner),
  { ssr: false, loading: () => <SkeletonBlock className="h-full min-h-80" /> },
);

const LEGEND_ORDER: DiffCellClass[] = ["cut", "fill", "below-threshold", "unknown"];

/**
 * 설계 대비 높이차 히트맵 — **저장된 차분 래스터 그대로**.
 *
 * 지도가 읽는 데이터는 워커가 체적 집계에 실제로 쓴 그 격자다(`GET .../diff-raster`
 * 가 유일한 경로). 그래서 표의 숫자와 지도의 색이 구조적으로 같은 배열에서 나온다.
 *
 * ## 범례가 3상태인 이유
 *
 * - **측정 불가(모름)** 은 회색이다. 0 으로 칠하면 "설계대로 됐다"는 뜻이 되는데,
 *   그건 확인된 적 없는 사실이다.
 * - **문턱 미만**은 중립색이다. 값은 있지만 **집계에서 빠졌다** — 그 사실이 색으로
 *   드러나야 표의 합계와 지도가 같은 말을 한다.
 * - 나머지만 발산형 팔레트로 그린다. 방향은 색상(주황=깎기 / 파랑=쌓기), 양은
 *   진하기가 말한다.
 *
 * `thresholdM` 은 **리포트가 실어 온 값**이다 — 이 컴포넌트는 자기 상수를 갖지
 * 않는다(계산 쪽 기준이 바뀌어도 범례가 옛 숫자를 말하는 일이 생기지 않는다).
 */
export function DiffHeatmapOverlay({
  missionId,
  designConformanceId,
  thresholdM,
  center = [37.5665, 126.978],
}: {
  missionId: string;
  designConformanceId: string;
  thresholdM: number;
  center?: [number, number];
}) {
  const [state, setState] = useState<DiffLoadState>({ phase: "loading" });
  const onState = useCallback((next: DiffLoadState) => setState(next), []);

  return (
    <section className="flex flex-col gap-2">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h4 className="text-[13px] font-bold break-keep">설계 대비 높이차 지도</h4>
        <span className="num text-[11.5px] whitespace-nowrap text-ink-muted">
          {state.phase === "ready"
            ? `최대 높이차 ${state.maxAbsM.toFixed(2)} m`
            : "불러오는 중…"}
        </span>
      </div>

      {state.phase === "unavailable" && (
        <p className="text-[12.5px] break-keep text-high-ink">
          높이차 지도를 불러오지 못했습니다 — {state.detail}
        </p>
      )}

      <div className="h-80 w-full overflow-hidden rounded-lg border border-line sm:h-96">
        <DiffHeatmapOverlayInner
          missionId={missionId}
          designConformanceId={designConformanceId}
          thresholdM={thresholdM}
          center={center}
          onState={onState}
        />
      </div>

      <ul className="flex flex-wrap gap-x-4 gap-y-1">
        {LEGEND_ORDER.map((cell) => (
          <li key={cell} className="flex items-center gap-1.5 text-[11.5px] break-keep">
            <span
              aria-hidden="true"
              className="size-3 shrink-0 rounded-[3px] border border-line-strong"
              style={{ backgroundColor: DIFF_CELL_COLOR[cell] }}
            />
            {DIFF_CELL_LABEL[cell]}
          </li>
        ))}
      </ul>

      <p className="text-[12px] break-keep text-ink-muted">
        색이 진할수록 차이가 큽니다(최대{" "}
        {state.phase === "ready" ? `${state.maxAbsM.toFixed(2)} m` : "—"}). 높이차가{" "}
        {thresholdM} m 미만인 곳은 재구성 잡음으로 보고 물량 합계에서 뺐습니다 — 지도에는
        중립색으로 남겨 두었습니다.
      </p>
    </section>
  );
}
