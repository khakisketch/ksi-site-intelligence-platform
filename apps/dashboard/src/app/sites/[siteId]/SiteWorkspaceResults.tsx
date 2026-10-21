import Link from "next/link";

import type { AnalysisListItem, AnalysisView } from "@/lib/core-api/analysis";
import { formatKoreanDateTime } from "@/lib/datetime";
import { analysisResultTitle } from "@/lib/operator-language";
import type { ExplicitResultResolution, WorkspaceServerFacts } from "@/lib/site-workspace-entry";
import { matchAnalysisSelectors, workspaceCaptureLine } from "@/lib/site-workspace-entry";
import { capturePeriodTitle } from "@/lib/operator-language";
import { formatKoreanDate } from "@/lib/datetime";
import { analysisStateLabel } from "./SiteSpatialOverview";

function RecordCard({ item }: { item: AnalysisListItem }) {
  return <article className="rounded-lg border border-line px-4 py-3">
    <h3 className="text-[13.5px] font-bold">{analysisResultTitle(item.createdAt)}</h3>
    <p className="mt-1 text-[12px] font-semibold">{analysisStateLabel(item)}</p>
    <p className="mt-0.5 text-[12px] text-ink-2">
      기록 {formatKoreanDateTime(item.createdAt, { dateStyle: "medium", timeStyle: "short" })}
      {item.limitationCount > 0 ? ` · 제한 ${item.limitationCount}건` : " · 기록된 제한 없음"}
    </p>
    <p className="mt-1 text-[12px] leading-5 text-ink-2">
      수치와 근거는 각 기록에 있습니다. 이 목록은 기록의 현재 상태를 옮긴 것이며, 다시 계산하지 않습니다.
    </p>
    <p className="mt-1">
      <Link href={item.analysisHref} className="tap-target inline-block text-[12px] underline">분석 기록 열기</Link>
    </p>
  </article>;
}

/**
 * 결과 모드 — 기존 분석 기록·근거와 그 한계를 새 요청보다 먼저 둔다.
 *
 * - 명시적 기록 링크는 원래 기록 그대로(정확한 입력·구역) 보여주거나 막는다.
 *   모르면 최신으로 바꾸지 않는다.
 * - 새 비교 요청은 기록 목록 "다음"에 둔다. 새 요청이 열람 중인 기록을
 *   바꾸지 않는다고 밝힌다.
 * - V2 계산 기록과 외부 비교 기록을 한 카드에 합치지 않는다.
 */
export function SiteWorkspaceResults({
  sitePath,
  areaLabel,
  areaAnalyses,
  analysesKnown,
  explicitResult,
  explicitDetail,
  facts,
  canCreateAnalysis,
  scopedCompareHref,
}: {
  sitePath: string;
  areaLabel: string | null;
  areaAnalyses: AnalysisListItem[] | null;
  analysesKnown: boolean;
  explicitResult: ExplicitResultResolution | null;
  /** 명시적 링크가 가리킨 실제 기록 — 준비 상태에서만 싣는다. 지어내지 않는다. */
  explicitDetail: AnalysisView | null;
  facts: WorkspaceServerFacts;
  canCreateAnalysis: boolean;
  scopedCompareHref: string;
}) {
  const explicitReady = explicitResult?.status === "ready" && explicitDetail ? explicitDetail : null;
  // 원래 입력(기준·현재 선택자)을 현재 프로젝션 버전에서 찾는다 — 없으면
  // 기록을 바꾸지 않고 그대로 둔다고 밝힌다.
  const matched = explicitReady
    ? matchAnalysisSelectors(facts, {
      analysisId: explicitReady.analysisId,
      workAreaId: explicitReady.workAreaId,
      baseline: explicitReady.baseline,
      current: explicitReady.current,
    })
    : null;
  const matchedLine = (label: string, fact: { captureStartedAt: string | null; captureEndedAt: string | null; captureDate: string | null } | null) =>
    fact
      ? `${label} · ${workspaceCaptureLine(fact, {
        intervalTitle: (startedAt, endedAt) => capturePeriodTitle(startedAt, endedAt),
        calendarDate: (date) => formatKoreanDate(date),
      })}`
      : null;
  return <div className="flex flex-col gap-3">
    <h2 className="text-[14px] font-bold">결과와 근거{areaLabel ? ` · ${areaLabel}` : ""}</h2>

    {explicitResult?.status === "unresolvable" && (
      <div role="alert" className="rounded-lg border border-line bg-surface px-4 py-3">
        <p className="text-[13px] font-bold">{explicitResult.headline}</p>
        <p className="mt-1 text-[12.5px] leading-5 text-ink-2">{explicitResult.detail}</p>
        <p className="mt-2 flex flex-wrap gap-x-3 text-[12px]">
          <Link href={`${sitePath}/analysis`} className="tap-target underline">분석 기록 목록 보기</Link>
          <Link href={sitePath} className="tap-target underline">탐색으로 돌아가기</Link>
        </p>
      </div>
    )}

    {explicitReady ? (
      <article className="rounded-lg border border-line px-4 py-3">
        <h3 className="text-[13.5px] font-bold">{analysisResultTitle(explicitReady.createdAt)}</h3>
        <p className="mt-1 text-[12px] font-semibold">{analysisStateLabel(explicitReady)}</p>
        <p className="mt-0.5 text-[12px] text-ink-2">
          기록 {formatKoreanDateTime(explicitReady.createdAt, { dateStyle: "medium", timeStyle: "short" })}
          {explicitReady.blockers.length > 0 ? ` · 확인된 조건 ${explicitReady.blockers.length}건` : " · 확인된 조건 없음"}
          {explicitReady.result ? " · 확정된 수치 있음" : " · 확정된 수치 없음"}
        </p>
        <p className="mt-1 text-[12px] leading-5 text-ink-2">
          링크의 원래 기록을 그대로 보여줍니다. 수치·선택 정보·근거는 분석 기록에 있으며, 다시 계산하지 않습니다.
        </p>
        {matched && (() => {
          const lines = [matchedLine("기준", matched.baseline), matchedLine("현재", matched.current)].filter((line): line is string => line !== null);
          if (lines.length === 0) {
            return <p className="mt-1 text-[12px] leading-5 text-ink-2">원래 입력을 현재 목록에서 확인할 수 없습니다. 기록은 그대로 둡니다.</p>;
          }
          return <p className="mt-1 text-[12px] leading-5 text-ink-2">
            {lines.join(" · ")}
            {lines.length === 2
              ? " — 원래 입력 2건이 현재 관측 목록에 있습니다."
              : " — 나머지 입력은 현재 목록에서 확인할 수 없습니다. 기록은 그대로 둡니다."}
          </p>;
        })()}
        <p className="mt-1">
          <Link href={`${sitePath}/analysis?analysisId=${encodeURIComponent(explicitReady.analysisId)}`} className="tap-target inline-block text-[12px] underline">분석 기록 열기</Link>
        </p>
      </article>
    ) : !analysesKnown || areaAnalyses === null ? (
      <p className="rounded-lg border border-line bg-surface px-4 py-3 text-[12.5px] leading-5 text-ink-2" role="status">
        분석 기록을 확인할 수 없습니다. 잠시 후 다시 확인하세요. 빈 목록으로 단정하지 않습니다.
      </p>
    ) : areaAnalyses.length === 0 ? (
      <p className="rounded-lg border border-line bg-surface px-4 py-3 text-[12.5px] leading-5 text-ink-2" role="status">
        이 구역에 조회된 분석 결과가 없습니다. 비교할 두 시점이 정해지면 아래에서 분석 요청을 시작합니다.
      </p>
    ) : (
      <div className="flex flex-col gap-2">
        {areaAnalyses.map((item) => <RecordCard key={item.analysisId} item={item} />)}
      </div>
    )}

    <div className="rounded-lg border border-line bg-surface px-4 py-3">
      <h3 className="text-[13px] font-bold">새 비교 요청</h3>
      <p className="mt-1 text-[12.5px] leading-5 text-ink-2">
        새 비교는 기준·현재 두 시점을 다시 고릅니다. 위 기록은 바뀌지 않습니다.
      </p>
      <p className="mt-2">
        {canCreateAnalysis ? (
          <Link href={scopedCompareHref} className="btn">이 구역 변화 비교</Link>
        ) : (
          <span className="text-[12px] text-ink-2">현재 계정으로는 비교를 요청할 수 없습니다. 권한 있는 담당자에게 문의하세요.</span>
        )}
      </p>
    </div>

    <p className="flex flex-wrap gap-x-3 text-[12px]">
      <Link href={`${sitePath}/observations`} className="tap-target underline">외부 비교 기록</Link>
    </p>
  </div>;
}
