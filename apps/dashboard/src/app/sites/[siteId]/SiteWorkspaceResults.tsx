import Link from "next/link";

import type { AnalysisListItem, AnalysisMetrics, AnalysisView } from "@/lib/core-api/analysis";
import { formatKoreanDateTime } from "@/lib/datetime";
import { analysisResultTitle } from "@/lib/operator-language";
import type { ExplicitResultResolution, WorkspaceServerFacts } from "@/lib/site-workspace-entry";
import { matchAnalysisSelectors, workspaceCaptureLine } from "@/lib/site-workspace-entry";
import { capturePeriodTitle } from "@/lib/operator-language";
import { formatKoreanDate } from "@/lib/datetime";
import { formatNumberKo, formatSignificantKo } from "@/lib/number-format";
import { analysisStateLabel } from "./SiteSpatialOverview";

/**
 * 체적 표기 — AnalysisRequestPanel의 formatNumber와 같은 규칙(0.1 미만 0 초과
 * 절대값은 유효숫자 3자리, 나머지는 소수 첫째 자리)이라 0.02가 0으로 뭉개지지
 * 않는다. Core가 기록한 값을 옮길 때만 쓰고 새로 계산하지 않는다.
 */
function formatVolumeM3(value: number): string {
  const rendered = Math.abs(value) > 0 && Math.abs(value) < 0.1
    ? formatSignificantKo(value, 3)
    : formatNumberKo(value, 1);
  return rendered;
}

/** 기록된 Core 수치 3열 — 기본 목록 카드와 명시적 기록이 같은 모양을 쓴다. */
function VolumeMetrics({ metrics }: { metrics: AnalysisMetrics }) {
  return <dl className="mt-2 grid grid-cols-3 gap-2 border-y border-line py-2">
    <div>
      <dt className="text-[11px] text-ink-muted">절토</dt>
      <dd className="text-[15px] font-bold tabular-nums">{formatVolumeM3(metrics.cutM3)} m³</dd>
    </div>
    <div>
      <dt className="text-[11px] text-ink-muted">성토</dt>
      <dd className="text-[15px] font-bold tabular-nums">{formatVolumeM3(metrics.fillM3)} m³</dd>
    </div>
    <div>
      <dt className="text-[11px] text-ink-muted">순변화</dt>
      <dd className="text-[15px] font-bold tabular-nums">{formatVolumeM3(metrics.netM3)} m³</dd>
    </div>
  </dl>;
}

function suitabilityLimitCopy(item: Pick<AnalysisListItem, "suitabilityState">): string {
  // 불확도 null에서 정확도 상태를 추론하지 않는다. Core의 적합성 판정 그대로 둔다.
  switch (item.suitabilityState) {
    case "PROVISIONAL_ACCURACY_UNVERIFIED":
      return "정확도 평가는 아직 확인되지 않았습니다.";
    case "EVALUATED":
      return "분석 조건 확인 결과가 있습니다.";
    case "BLOCKED":
      return "분석을 진행할 수 없는 조건입니다.";
    case "REMEDIATION_REQUIRED":
      return "자료 보완이 필요합니다.";
    case "REASSESSMENT_REQUIRED":
      return "사용 조건 재확인이 필요합니다.";
    default:
      return "분석 조건 확인이 필요합니다.";
  }
}

function RecordCard({ item, sitePath, lead = false, pairLine = null, pairUnknown = false, visualQuery = "" }: {
  item: AnalysisListItem;
  sitePath: string;
  lead?: boolean;
  /** 첫 기록의 실제 비교 구간 한 줄 — 없으면 두지 않는다(추측 금지). */
  pairLine?: string | null;
  /** 원래 입력을 현재 목록에서 확인하지 못했을 때 true. */
  pairUnknown?: boolean;
  /** 탐색 중이던 시각 쌍 복귀 쿼리 — frozen 기록 링크를 바꾸지 않고 덧붙인다. */
  visualQuery?: string;
}) {
  // 결과 모드의 첫 화면은 "무엇이 얼마나 바뀌었나"다. 수치는 이미 Core가
  // 결정해 기록한 값이므로 그대로 옮기고 그 옆에 한계를 함께 둔다. 여기서
  // 다시 계산하거나 수치를 새로 만들지 않는다.
  const metrics = item.metrics;
  return <article className={`rounded-lg border px-4 py-3 ${lead ? "border-line-strong bg-surface" : "border-line"}`}>
    <h3 className={`${lead ? "text-[15px]" : "text-[13.5px]"} font-bold`}>{analysisResultTitle(item.createdAt)}</h3>
    <p className="mt-1 text-[12px] font-semibold">{analysisStateLabel(item)}</p>
    <p className="mt-0.5 text-[12px] text-ink-2">
      기록 {formatKoreanDateTime(item.createdAt, { dateStyle: "medium", timeStyle: "short" })}
      {item.limitationCount > 0 ? ` · 제한 ${item.limitationCount}건` : " · 기록된 제한 없음"}
    </p>
    {pairLine && (
      <p className="mt-1 break-words text-[12px] leading-5 text-ink-1">{pairLine}</p>
    )}
    {pairUnknown && (
      <p className="mt-1 text-[12px] leading-5 text-ink-2">원래 입력을 현재 목록에서 확인할 수 없습니다. 기록은 그대로 둡니다.</p>
    )}
    {metrics ? (
      <VolumeMetrics metrics={metrics} />
    ) : (
      <p className="mt-1 text-[12px] leading-5 text-ink-2">
        이 기록에는 계산된 수치가 없습니다. 확인된 조건과 근거는 분석 기록에서 확인하세요.
      </p>
    )}
    {metrics && (
      <>
        <p className="mt-1 text-[12px] leading-5 text-ink-2">
          {suitabilityLimitCopy(item)} 이 값은 물량 정확도 보증·측량 승인·정산 근거가 아닙니다.
        </p>
        {metrics.uncertaintyM3 === null ? (
          <p className="mt-1 text-[12px] leading-5 text-ink-2">
            불확실성 미기록 — 기록된 값이 없으므로 0으로 볼 수 없습니다. 검사점 평가와 별개입니다.
          </p>
        ) : typeof metrics.uncertaintyM3 === "number" && Number.isFinite(metrics.uncertaintyM3) ? (
          <p className="num mt-1 break-words text-[12px] leading-5 text-ink-2">
            {`불확실성 ±${formatVolumeM3(metrics.uncertaintyM3)} m³ (기록값)`}
          </p>
        ) : null}
      </>
    )}
    <p className="mt-1 text-[12px] leading-5 text-ink-2">
      이 화면은 기록된 값을 옮긴 것이며 다시 계산하지 않습니다. 계산에 쓰인 자료·조건·근거는 분석 기록에 있습니다.
    </p>
    <p className="mt-1">
      <Link href={`${sitePath}/analysis?workAreaId=${encodeURIComponent(item.workAreaId)}&analysisId=${encodeURIComponent(item.analysisId)}${visualQuery}`} className="tap-target inline-block text-[12px] underline">자료·근거와 검토 보기</Link>
    </p>
  </article>;
}

/**
 * 결과 모드 — 기존 분석 기록·근거와 그 한계를 새 요청보다 먼저 둔다.
 *
 * - 명시적 기록 링크는 원래 기록 그대로(정확한 입력·구역) 보여주거나 막는다.
 *   모르면 최신으로 바꾸지 않는다.
 * - 새 변화량 분석 요청은 기록 목록 "다음"에 둔다. 새 요청이 열람 중인 기록을
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
  leadDetail,
  facts,
  canCreateAnalysis,
  scopedCompareHref,
  visualContext = null,
}: {
  sitePath: string;
  areaLabel: string | null;
  areaAnalyses: AnalysisListItem[] | null;
  analysesKnown: boolean;
  explicitResult: ExplicitResultResolution | null;
  /** 명시적 링크가 가리킨 실제 기록 — 준비 상태에서만 싣는다. 지어내지 않는다. */
  explicitDetail: AnalysisView | null;
  /** 결과 목록 첫 기록의 상세(선택자 복원용, 1건만) — 없으면 조용히 둔다. */
  leadDetail: AnalysisView | null;
  facts: WorkspaceServerFacts;
  canCreateAnalysis: boolean;
  scopedCompareHref: string;
  /** 탐색 중이던 시각 쌍 맥락 — 결과의 frozen 입력과 구분해 복귀한다. */
  visualContext?: { workAreaId: string; visualAAssetRef: string; visualBAssetRef: string } | null;
}) {
  const normalizedVisualContext = visualContext ?? null;
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
  // 목록 첫 기록의 실제 비교 구간 — 상세의 원래 선택자를 현재 목록에서
  // 찾는다. 없으면 추측하지 않고 그대로 둔다고만 밝힌다.
  const leadItem = !explicitReady && areaAnalyses && areaAnalyses.length > 0 ? areaAnalyses[0]! : null;
  const leadMatched = leadItem && leadDetail && leadDetail.analysisId === leadItem.analysisId
    ? matchAnalysisSelectors(facts, {
      analysisId: leadDetail.analysisId,
      workAreaId: leadDetail.workAreaId,
      baseline: leadDetail.baseline,
      current: leadDetail.current,
    })
    : null;
  const leadPairLine = leadMatched
    ? [matchedLine("기준", leadMatched.baseline), matchedLine("현재", leadMatched.current)]
      .filter((line): line is string => line !== null)
      .join(" · ") || null
    : null;
  const leadPairUnknown = Boolean(leadItem && leadDetail && leadDetail.analysisId === leadItem.analysisId && leadPairLine === null);
  // 탐색 복귀 주소 — 검증된 시각 쌍 맥락만 싣는다. 구역이 바뀌면 쌍을 싣지 않고
  // 비교 모드 주소로만 둔다(조용히 다른 구역의 쌍을 복원하지 않는다).
  // 탐색 복귀 쿼리 — 정식 맥락에서만 덧붙인다. frozen 기록 식별자는 그대로 둔다.
  const visualQuery = normalizedVisualContext
    ? `&visualAAssetRef=${encodeURIComponent(normalizedVisualContext.visualAAssetRef)}&visualBAssetRef=${encodeURIComponent(normalizedVisualContext.visualBAssetRef)}`
    : "";
  const visualReturnHref = normalizedVisualContext
    ? `${sitePath}?mode=compare&workAreaId=${encodeURIComponent(normalizedVisualContext.workAreaId)}${visualQuery}`
    : null;
  return <div className="flex flex-col gap-3">
    <h2 className="text-[14px] font-bold">결과와 근거{areaLabel ? ` · ${areaLabel}` : ""}</h2>
    {visualReturnHref && (
      <p className="rounded-lg border border-line bg-surface px-4 py-3 text-[12.5px] leading-5 text-ink-2">
        탐색 중이던 독립 보기 쌍이 있습니다.{" "}
        <Link href={visualReturnHref} className="tap-target underline">독립 보기로 돌아가기</Link>
        <span className="text-ink-muted"> · 돌아가면 같은 두 자료·층을 그대로 둡니다. 이 결과의 계산 입력과는 다를 수 있습니다.</span>
      </p>
    )}

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
          {explicitReady.result ? " · 계산 수치 있음" : " · 계산 수치 없음"}
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
        {explicitReady.result ? (
          <>
            <VolumeMetrics metrics={explicitReady.result.metrics} />
            <p className="mt-1 text-[12px] leading-5 text-ink-2">
              {suitabilityLimitCopy(explicitReady)} 이 값은 물량 정확도 보증·측량 승인·정산 근거가 아닙니다.
            </p>
            {explicitReady.result.metrics.uncertaintyM3 === null ? (
              <p className="mt-1 text-[12px] leading-5 text-ink-2">
                불확실성 미기록 — 기록된 값이 없으므로 0으로 볼 수 없습니다. 검사점 평가와 별개입니다.
              </p>
            ) : typeof explicitReady.result.metrics.uncertaintyM3 === "number" && Number.isFinite(explicitReady.result.metrics.uncertaintyM3) ? (
              <p className="num mt-1 break-words text-[12px] leading-5 text-ink-2">
                {`불확실성 ±${formatVolumeM3(explicitReady.result.metrics.uncertaintyM3)} m³ (기록값)`}
              </p>
            ) : null}
            <p className="mt-1 text-[12px] leading-5 text-ink-2">
              이 화면은 기록된 값을 옮긴 것이며 다시 계산하지 않습니다. 계산에 쓰인 자료·조건·근거는 분석 기록에 있습니다.
            </p>
          </>
        ) : (
          <p className="mt-1 text-[12px] leading-5 text-ink-2">
            이 기록에는 계산된 수치가 없습니다. 확인된 조건과 근거는 분석 기록에서 확인하세요.
          </p>
        )}
        {normalizedVisualContext && (
          <p className="mt-1 text-[12px] leading-5 text-ink-2">
            탐색 중 자료와 이 결과의 계산 입력은 다를 수 있습니다. 위의 원래 입력이 이 결과의 계산 입력이며,
            탐색 중 자료는 독립 보기 쌍 그대로 둡니다.
          </p>
        )}
        <p className="mt-1">
          <Link href={`${sitePath}/analysis?analysisId=${encodeURIComponent(explicitReady.analysisId)}${explicitReady.workAreaId && normalizedVisualContext && explicitReady.workAreaId === normalizedVisualContext.workAreaId ? `&workAreaId=${encodeURIComponent(explicitReady.workAreaId)}${visualQuery}` : ""}`} className="tap-target inline-block text-[12px] underline">자료·근거와 검토 보기</Link>
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
        {/* 첫 화면은 가장 최근 기록 하나다. 나머지는 겹쳐 두지 않고 펼침에 둔다. */}
        <RecordCard item={areaAnalyses[0]!} sitePath={sitePath} lead pairLine={leadPairLine} pairUnknown={leadPairUnknown} visualQuery={visualQuery} />
        {areaAnalyses.length > 1 && (
          <details className="rounded-lg border border-line px-4 py-3">
            <summary className="tap-target cursor-pointer text-[13px] font-semibold">이전 기록 {areaAnalyses.length - 1}건</summary>
            <div className="mt-2 flex flex-col gap-2">
              {areaAnalyses.slice(1).map((item) => <RecordCard key={item.analysisId} item={item} sitePath={sitePath} visualQuery={visualQuery} />)}
            </div>
          </details>
        )}
      </div>
    )}

    <div className="rounded-lg border border-line bg-surface px-4 py-3">
      <h3 className="text-[13px] font-bold">새 변화량 분석 요청</h3>
      <p className="mt-1 text-[12.5px] leading-5 text-ink-2">
        새 변화량 분석은 기준·현재 두 시점을 다시 고릅니다. 위 기록은 바뀌지 않습니다.
      </p>
      <p className="mt-2">
        {canCreateAnalysis ? (
          <Link href={scopedCompareHref} className="btn">변화량 분석</Link>
        ) : (
          <span className="text-[12px] text-ink-2">현재 계정으로는 변화량 분석을 요청할 수 없습니다. 권한 있는 담당자에게 문의하세요.</span>
        )}
      </p>
    </div>

    <p className="flex flex-wrap gap-x-3 text-[12px]">
      <Link href={`${sitePath}/observations`} className="tap-target underline">외부 비교 기록</Link>
    </p>
  </div>;
}
