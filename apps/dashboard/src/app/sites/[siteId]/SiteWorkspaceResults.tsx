import Link from "next/link";

import type { AnalysisCoverageSummary, AnalysisListItem, AnalysisMetrics, AnalysisReviewDecision, AnalysisView } from "@/lib/core-api/analysis";
import type { Tone } from "@/lib/core-api/labels";
import { analysisResultTitle } from "@/lib/operator-language";
import type { ExplicitResultResolution, WorkspaceServerFacts } from "@/lib/site-workspace-entry";
import { matchAnalysisSelectors } from "@/lib/site-workspace-entry";
import { AnalysisCoverage } from "@/components/analysis/AnalysisCoverage";
import { Disclosure } from "@/components/ui/Disclosure";
import { InlineNotice } from "@/components/ui/InlineNotice";
import { PageHeader } from "@/components/ui/PageHeader";
import { StateBadge } from "@/components/ui/StatusBadge";
import { formatNumberKo } from "@/lib/number-format";
import { analysisStateLabel } from "./SiteSpatialOverview";
import {
  CoverageStrip,
  ResultTrend,
  UncertaintyChip,
  VolumeBalance,
  shortDateLabel,
  shortDateTimeLabel,
  fullDateTimeLabel,
  yearOf,
  type TrendPoint,
} from "./AnalysisResultVisuals";

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

/** 상태 칩 색 — 진행·판정에 따라 주의가 필요한 것만 채운다. */
function stateTone(item: Pick<AnalysisListItem, "executionState" | "suitabilityState">): Tone {
  if (item.executionState === "FAILED") return "warning";
  if (item.executionState !== "COMPLETED") return "progress";
  switch (item.suitabilityState) {
    case "EVALUATED": return "positive";
    case "PROVISIONAL_ACCURACY_UNVERIFIED": return "neutral";
    default: return "caution";
  }
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="flex min-w-0 flex-col gap-3 rounded-lg border border-line bg-surface p-4">
    <h4 className="text-body font-bold">{title}</h4>
    {children}
  </section>;
}

/** 접힌 상세 — 숫자 옆 문장을 늘리지 않고, 한계의 근거 문구는 여기에 둔다. */
function LimitDetails({ metrics, limitCopy }: { metrics: AnalysisMetrics; limitCopy: string }) {
  return <Disclosure label="한계 자세히" className="text-caption text-ink-2">
    <div className="mt-1 flex flex-col gap-1">
      {metrics.uncertaintyM3 === null && (
        <p>불확실성 미기록 — 기록된 값이 없으므로 0으로 볼 수 없습니다. 검사점 평가와 별개입니다.</p>
      )}
      <p>{limitCopy} 이 값은 물량 정확도 보증·측량 승인·정산 근거가 아닙니다.</p>
      <p>기록된 값을 옮긴 것이며 다시 계산하지 않습니다.</p>
    </div>
  </Disclosure>;
}

/**
 * 이 결과에 남은 사람 검토의 요약. 조회하지 못하면 "unavailable"로 두고 화면은 검토 상태를
 * 말하지 않는다 — 못 읽은 것을 "검토 없음"으로 바꾸지 않는다.
 */
export type ResultReviewSummary =
  | { status: "ready"; count: number; latest: { decision: AnalysisReviewDecision; reviewedAt: string } | null }
  | { status: "unavailable" };

const REVIEW_DECISION_LABEL: Record<AnalysisReviewDecision, string> = {
  ACKNOWLEDGED: "결과와 한계 확인",
  NEEDS_FOLLOW_UP: "추가 확인 필요",
};

const PAIR_MISSING = "원래 입력 일부를 현재 목록에서 확인할 수 없습니다.";

type PairFacts = { baseline: WorkspaceCaptureLike | null; current: WorkspaceCaptureLike | null } | null;
type WorkspaceCaptureLike = { captureEndedAt: string | null; captureDate: string | null };

/** 관측일을 한 줄로 — 시각은 촬영이 끝난 때, 날짜만 알면 날짜만 적는다. */
function pairSummary(matched: PairFacts): { line: string | null; warning: string | null } {
  if (!matched) return { line: null, warning: null };
  const when = (fact: WorkspaceCaptureLike | null): string | null => fact?.captureEndedAt ?? fact?.captureDate ?? null;
  // 두 날짜가 모두 올해면 해를 생략하고, 아니면 해를 밝힌다(다른 해의 같은 월·일과 헷갈리지 않게).
  const thisYear = new Date().getFullYear();
  const years = [when(matched.baseline), when(matched.current)].flatMap((value) => (value ? [yearOf(value)] : []));
  const short = years.length > 0 && years.every((year) => year === thisYear);
  const label = (fact: WorkspaceCaptureLike | null): string | null => {
    const value = when(fact);
    if (!fact || !value) return null;
    if (fact.captureEndedAt) return (short ? shortDateTimeLabel(value) : fullDateTimeLabel(value)) || null;
    return (short ? shortDateLabel(value) : fullDateTimeLabel(value).split(" ")[0]) || null;
  };
  const base = label(matched.baseline);
  const cur = label(matched.current);
  if (!base && !cur) return { line: null, warning: PAIR_MISSING };
  const line = `기준 ${base ?? "확인 불가"} → 현재 ${cur ?? "확인 불가"}`;
  return { line, warning: matched.baseline && matched.current ? null : PAIR_MISSING };
}

type TrendResult = { points: TrendPoint[]; currentId: string; conditions: string };

/**
 * 같은 영역에서 비교할 수 있다고 말할 수 있는 결과만 관측일 순으로 모은다.
 * - 완료됐고 결과 수치가 있으며 같은 영역일 것
 * - 임계값·셀 크기가 같을 것(다른 조건의 수치를 한 눈금에 올리지 않는다)
 * - 현재 관측을 현재 관측 목록에서 찾아 관측일을 알 수 있을 것
 * - 같은 기준·현재 쌍을 다시 계산한 기록은 가장 나중 것 하나만 쓴다
 * 조건을 확인하지 못한 기록은 빼며, 두 건 미만이면 추이를 그리지 않는다.
 */
function buildTrend(focal: AnalysisView, peers: readonly AnalysisView[], facts: WorkspaceServerFacts): TrendResult | null {
  const base = focal.result;
  if (!base || focal.executionState !== "COMPLETED") return null;
  const pairs = new Map<string, { view: AnalysisView; sortKey: string; label: string; timed: string }>();
  for (const view of [focal, ...peers]) {
    const result = view.result;
    if (!result || view.executionState !== "COMPLETED" || view.workAreaId !== focal.workAreaId) continue;
    if (result.metrics.thresholdM !== base.metrics.thresholdM || result.coverage.cellAreaM2 !== base.coverage.cellAreaM2) continue;
    const matched = matchAnalysisSelectors(facts, {
      analysisId: view.analysisId, workAreaId: view.workAreaId, baseline: view.baseline, current: view.current,
    });
    const when = matched.current?.captureEndedAt ?? matched.current?.captureDate ?? null;
    const label = when ? shortDateLabel(when) : "";
    const timed = when ? shortDateTimeLabel(when) : "";
    if (!when || !label) continue;
    const key = `${view.baseline.submissionRef}@${view.baseline.revision}>${view.current.submissionRef}@${view.current.revision}`;
    const known = pairs.get(key);
    // 같은 쌍의 재계산은 나중 기록 하나만 쓰되, 지금 보는 결과는 항상 남긴다.
    if (known && known.view.analysisId !== focal.analysisId && (view.analysisId === focal.analysisId || view.createdAt > known.view.createdAt)) pairs.set(key, { view, sortKey: when, label, timed });
    else if (!known) pairs.set(key, { view, sortKey: when, label, timed });
  }
  if (!pairs.has(`${focal.baseline.submissionRef}@${focal.baseline.revision}>${focal.current.submissionRef}@${focal.current.revision}`)) return null;
  const entries = [...pairs.values()];
  // 같은 날 촬영이 둘 이상이면 날짜만으로는 점을 구분할 수 없어 시각까지 적는다.
  const sameDay = new Set(entries.map((entry) => entry.label)).size !== entries.length;
  const points = entries.map(({ view, sortKey, label, timed }) => ({
    analysisId: view.analysisId, sortKey, label: sameDay && timed ? timed : label, metrics: view.result!.metrics,
  }));
  if (points.length < 2) return null;
  return {
    points,
    currentId: focal.analysisId,
    conditions: `같은 영역 · 임계값 ${formatNumberKo(base.metrics.thresholdM, 2)} m · 셀 ${formatNumberKo(base.coverage.cellAreaM2 ** 0.5, 2)} m`,
  };
}

type ResultSheetProps = {
  item: Pick<AnalysisListItem, "executionState" | "suitabilityState" | "createdAt">;
  title: string;
  metrics: AnalysisMetrics | null;
  /** "기준 11.15 22:18 → 현재 11.15 22:21" — 관측일을 확인한 쪽만 적는다(추측 금지). */
  pairLine?: string | null;
  /** 원래 입력 일부를 현재 목록에서 확인할 수 없을 때만 두는 한 줄. */
  pairWarning?: string | null;
  blockerCount?: number;
  /** Core가 기록한 제한 건수 — 0이면 두지 않는다(없음을 길게 말하지 않는다). */
  limitationCount?: number;
  coverage?: AnalysisCoverageSummary | null;
  /** 계산 범위 격자를 여는 기존 보기에 줄 상세 — 없으면 요약 막대만 둔다. */
  coverageDetail?: AnalysisView | null;
  trend: TrendResult | null;
  reviewSummary?: ResultReviewSummary | null;
  evidenceHref: string;
  canCreateAnalysis: boolean;
  requestHref: string;
};

/**
 * 결과 판독 — 한눈에(순변화·방향·깎임↔쌓임) → 이전과 비교 → 분석 범위 → 근거로 이동.
 * 숫자는 Core가 기록한 값을 옮긴 것이며 여기서 새로 계산하지 않는다.
 * 모르는 값(불확실성)은 0이 아니라 "미기록"으로 말한다.
 */
function ResultSheet({
  item, title, metrics, pairLine = null, pairWarning = null, blockerCount = 0,
  limitationCount = 0, coverage = null, coverageDetail = null, trend, reviewSummary = null,
  evidenceHref, canCreateAnalysis, requestHref,
}: ResultSheetProps) {
  const limitCopy = suitabilityLimitCopy(item);
  return <article className="flex flex-col gap-4">
    <header className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <h3 className="text-title font-bold break-keep">{title}</h3>
        <div className="flex flex-wrap items-center gap-1.5">
          {item.executionState === "COMPLETED" && <StateBadge label="계산 완료" tone="positive" />}
          <StateBadge label={analysisStateLabel(item)} tone={stateTone(item)} />
          {reviewSummary?.status === "ready" && (reviewSummary.latest
            ? <StateBadge label={`검토됨 · ${REVIEW_DECISION_LABEL[reviewSummary.latest.decision]}`} tone={reviewSummary.latest.decision === "NEEDS_FOLLOW_UP" ? "caution" : "neutral"} />
            : <StateBadge label="검토 기록 없음" tone="neutral" />)}
        </div>
        {limitationCount > 0 && <span className="text-caption text-ink-muted">제한 {limitationCount}건</span>}
      </div>
      {pairLine && <p className="font-mono text-body tabular-nums text-ink-1 break-words">{pairLine}</p>}
      {pairWarning && <p className="text-caption leading-5 text-high-ink">{pairWarning}</p>}
    </header>

    {metrics ? (
      <div className="grid items-start gap-4 lg:grid-cols-2">
        <section className="flex min-w-0 flex-col gap-3 rounded-lg border border-line-strong bg-surface p-4 sm:p-5">
          <VolumeBalance metrics={metrics} />
          <div className="flex flex-wrap gap-1.5">
            <UncertaintyChip uncertaintyM3={metrics.uncertaintyM3} />
            <span className="inline-flex w-fit items-center rounded-md border border-line-strong bg-surface px-2 py-0.5 text-caption font-semibold text-ink-2">참고용 · 보증 아님</span>
          </div>
          <LimitDetails metrics={metrics} limitCopy={limitCopy} />
        </section>
        <div className="flex min-w-0 flex-col gap-4">
          <Panel title="이전 결과와 비교">
            {trend
              ? <ResultTrend points={trend.points} currentId={trend.currentId} conditions={trend.conditions} />
              : <p className="text-body text-ink-2">비교할 수 있는 이전 결과가 없습니다.</p>}
          </Panel>
          {coverage && <Panel title="계산 범위">
            <CoverageStrip coverage={coverage} />
            {coverageDetail && <AnalysisCoverage detail={coverageDetail} allowMap={false} terse />}
          </Panel>}
        </div>
      </div>
    ) : (
      <section className="flex flex-col gap-1 rounded-lg border border-line bg-surface p-4">
        <p className="text-body leading-5 text-ink-1">
          이 기록에는 계산된 수치가 없습니다. 확인된 조건과 근거는 분석 기록에서 확인하세요.
        </p>
        {blockerCount > 0 && <p className="text-caption text-ink-2">확인된 조건 {blockerCount}건</p>}
      </section>
    )}

    <div className="flex flex-wrap gap-2">
      <Link href={evidenceHref} className="btn btn-primary tap-target">자료·근거와 검토 보기</Link>
      {canCreateAnalysis && <Link href={requestHref} className="btn tap-target">새 분석 요청</Link>}
    </div>
  </article>;
}

/** 이전 결과 한 줄 — 최신이 아닌 기록은 숫자만 가볍게 보이고 상세는 분석 기록으로 보낸다. */
function CompactRecord({ item, evidenceHref }: { item: AnalysisListItem; evidenceHref: string }) {
  const metrics = item.metrics;
  return <article className="flex flex-col gap-2 rounded-lg border border-line px-4 py-3">
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <h3 className="text-lead font-bold">{analysisResultTitle(item.createdAt)}</h3>
      <StateBadge label={analysisStateLabel(item)} tone={stateTone(item)} />
      {item.limitationCount > 0 && <span className="text-caption text-ink-muted">제한 {item.limitationCount}건</span>}
    </div>
    {metrics ? (
      <>
        <VolumeBalance metrics={metrics} compact />
        <div className="flex flex-wrap gap-1.5">
          <UncertaintyChip uncertaintyM3={metrics.uncertaintyM3} />
          <span className="inline-flex w-fit items-center rounded-md border border-line-strong bg-surface px-2 py-0.5 text-caption font-semibold text-ink-2">참고용 · 보증 아님</span>
        </div>
        <LimitDetails metrics={metrics} limitCopy={suitabilityLimitCopy(item)} />
      </>
    ) : (
      <p className="text-caption leading-5 text-ink-2">
        이 기록에는 계산된 수치가 없습니다. 확인된 조건과 근거는 분석 기록에서 확인하세요.
      </p>
    )}
    <Link href={evidenceHref} className="tap-target inline-block w-fit text-caption underline">자료·근거와 검토 보기</Link>
  </article>;
}

/**
 * 결과 모드 — 기존 분석 기록·근거와 그 한계를 새 요청보다 먼저 둔다.
 *
 * - 명시적 기록 링크는 원래 기록 그대로(정확한 입력·영역) 보여주거나 막는다.
 *   모르면 최신으로 바꾸지 않는다.
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
  peerDetails = [],
  reviewSummary = null,
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
  /** 같은 영역의 다른 완료 결과 상세 — 추이에 쓸 수 있는지는 buildTrend가 가린다. */
  peerDetails?: readonly AnalysisView[];
  /** 지금 보는 결과의 사람 검토 요약. */
  reviewSummary?: ResultReviewSummary | null;
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
  const leadPair = pairSummary(leadMatched);
  const leadPairUnknown = Boolean(leadItem && leadDetail && leadDetail.analysisId === leadItem.analysisId && leadPair.line === null);
  // 탐색 복귀 주소 — 검증된 시각 쌍 맥락만 싣는다. 영역이 바뀌면 쌍을 싣지 않고
  // 비교 모드 주소로만 둔다(조용히 다른 영역의 쌍을 복원하지 않는다).
  // 탐색 복귀 쿼리 — 정식 맥락에서만 덧붙인다. frozen 기록 식별자는 그대로 둔다.
  const visualQuery = normalizedVisualContext
    ? `&visualAAssetRef=${encodeURIComponent(normalizedVisualContext.visualAAssetRef)}&visualBAssetRef=${encodeURIComponent(normalizedVisualContext.visualBAssetRef)}`
    : "";
  const visualReturnHref = normalizedVisualContext
    ? `${sitePath}?mode=compare&workAreaId=${encodeURIComponent(normalizedVisualContext.workAreaId)}${visualQuery}`
    : null;
  const [requestPath, requestQuery] = scopedCompareHref.split("#")[0]!.split("?");
  const requestParams = new URLSearchParams(requestQuery);
  requestParams.set("request", "new");
  const requestHref = `${requestPath}?${requestParams.toString()}`;
  const explicitPair = pairSummary(matched);
  return <div className="flex flex-col gap-3">
    <PageHeader title="분석 결과" description={areaLabel} headingLevel={2}
      actions={<Link className="btn" href={`${sitePath}/analysis`}>분석 이력</Link>} />
    {visualReturnHref && (
      <p className="rounded-lg border border-line bg-surface px-4 py-3 text-body leading-5 text-ink-2">
        탐색 중이던 독립 보기 쌍이 있습니다.{" "}
        <Link href={visualReturnHref} className="tap-target underline">독립 보기로 돌아가기</Link>
        <span className="text-ink-muted"> · 돌아가면 같은 두 자료·층을 그대로 둡니다. 이 결과의 계산 입력과는 다를 수 있습니다.</span>
      </p>
    )}

    {explicitResult?.status === "unresolvable" ? (
      <InlineNotice tone="high" role="alert">
        <strong>{explicitResult.headline}</strong>{" "}{explicitResult.detail}
      </InlineNotice>
    ) : explicitReady ? (
      <ResultSheet
        item={explicitReady}
        title={analysisResultTitle(explicitReady.createdAt)}
        metrics={explicitReady.result?.metrics ?? null}
        pairLine={explicitPair.line}
        pairWarning={explicitPair.warning}
        blockerCount={explicitReady.blockers.length}
        limitationCount={explicitReady.result?.limitationCodes.length ?? 0}
        coverage={explicitReady.result?.coverage ?? null}
        coverageDetail={explicitReady}
        trend={buildTrend(explicitReady, peerDetails, facts)}
        reviewSummary={reviewSummary}
        evidenceHref={`${sitePath}/analysis?analysisId=${encodeURIComponent(explicitReady.analysisId)}${explicitReady.workAreaId && normalizedVisualContext && explicitReady.workAreaId === normalizedVisualContext.workAreaId ? `&workAreaId=${encodeURIComponent(explicitReady.workAreaId)}${visualQuery}` : ""}`}
        canCreateAnalysis={canCreateAnalysis}
        requestHref={requestHref}
      />
    ) : !analysesKnown || areaAnalyses === null ? (
      <p className="rounded-lg border border-line bg-surface px-4 py-3 text-body leading-5 text-ink-2" role="status">
        분석 기록을 확인할 수 없습니다. 잠시 후 다시 확인하세요.
      </p>
    ) : areaAnalyses.length === 0 ? (
      <p className="rounded-lg border border-line bg-surface px-4 py-3 text-body leading-5 text-ink-2" role="status">
        이 영역에 조회된 분석 결과가 없습니다.
      </p>
    ) : (
      <div className="flex flex-col gap-4">
        <ResultSheet
          item={areaAnalyses[0]!}
          title={analysisResultTitle(areaAnalyses[0]!.createdAt)}
          metrics={areaAnalyses[0]!.metrics}
          limitationCount={areaAnalyses[0]!.limitationCount}
          pairLine={leadPair.line}
          pairWarning={leadPairUnknown ? PAIR_MISSING : leadPair.warning}
          coverage={leadDetail && leadDetail.analysisId === areaAnalyses[0]!.analysisId ? leadDetail.result?.coverage ?? null : null}
          coverageDetail={leadDetail && leadDetail.analysisId === areaAnalyses[0]!.analysisId ? leadDetail : null}
          trend={leadDetail && leadDetail.analysisId === areaAnalyses[0]!.analysisId ? buildTrend(leadDetail, peerDetails, facts) : null}
          reviewSummary={reviewSummary}
          evidenceHref={`${sitePath}/analysis?workAreaId=${encodeURIComponent(areaAnalyses[0]!.workAreaId)}&analysisId=${encodeURIComponent(areaAnalyses[0]!.analysisId)}${visualQuery}`}
          canCreateAnalysis={canCreateAnalysis}
          requestHref={requestHref}
        />
        {areaAnalyses.length > 1 && (
          <Disclosure label={`이전 분석 결과 ${areaAnalyses.length - 1}건`} className="text-body">
            <section aria-label="이전 분석 결과" className="mt-2 flex flex-col gap-2">
              {areaAnalyses.slice(1).map((item) => <CompactRecord key={item.analysisId} item={item}
                evidenceHref={`${sitePath}/analysis?workAreaId=${encodeURIComponent(item.workAreaId)}&analysisId=${encodeURIComponent(item.analysisId)}${visualQuery}`} />)}
            </section>
          </Disclosure>
        )}
      </div>
    )}
  </div>;
}
