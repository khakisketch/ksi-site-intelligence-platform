"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { StateBadge } from "@/components/ui/StatusBadge";
import { ActionUnavailable } from "@/components/ui/ActionUnavailable";
import { ResponsiveActionBoundary } from "@/components/responsive/ResponsiveActionBoundary";
import { formatBytesKo, formatCountKo, formatNumberKo, formatSignificantKo } from "@/lib/number-format";
import type {
  AnalysisEvidenceItem,
  AnalysisEvidencePage,
  AnalysisListItem,
  AnalysisListPage,
  AnalysisObservationOption,
  AnalysisReviewDecision,
  AnalysisReviewPage,
  AnalysisReviewReceipt,
  AnalysisReviewTarget,
  AnalysisResult,
  AnalysisSelector,
  AnalysisView,
} from "@/lib/core-api/analysis";
import { formatKoreanDateTime } from "@/lib/datetime";
import { latestAnalysisReview, sameAnalysisReviewTarget } from "@/lib/analysis-review";
import {
  deriveNewerObservationNotice,
  findEpochCaptureEndedAt,
  type NewerAnalysisCandidate,
} from "@/lib/analysis-newer-observation";
import {
  analysisEvidenceKindLabel,
  analysisEvidenceReasonLine,
  analysisEvidenceSummary,
  getAnalysisIssueGuidance,
} from "@/lib/analysis-guidance";
import {
  observationChoiceLabels,
  type WorkOrderNameMap,
} from "@/lib/human-labels";
import {
  analysisResultTitle,
  capturePeriodTitle,
  dataKindLabel,
  isSupportedDataKind,
  registrationVersionLabel,
} from "@/lib/operator-language";
import { describePairSelection, isKnownBadPairSelection, shouldAutoSuggestBaseline } from "./pair-selection";

type Attempt = {
  key: string;
  workAreaId: string;
  body: { baseline: AnalysisSelector; current: AnalysisSelector };
  activationBlockCode: ActivationBlockCode | null;
};

type AttemptScope = { organizationId: string; principalId: string; siteId: string };
type AttributedAnalysisObservation = AnalysisObservationOption & { workAreaIds: readonly string[] };
type IndexedAnalysisObservation = { item: AttributedAnalysisObservation; index: number };

function latestPriorObservationIndex(
  options: readonly IndexedAnalysisObservation[],
  current: AnalysisObservationOption,
): string {
  const currentStart = Date.parse(current.captureStartedAt);
  if (!Number.isFinite(currentStart)) return "";
  const priors = options.flatMap(({ item, index }) => {
    if (sameSelector(item.selector, current.selector)) return [];
    const start = Date.parse(item.captureStartedAt);
    const end = Date.parse(item.captureEndedAt);
    if (!Number.isFinite(start) || !Number.isFinite(end) || start > end || end > currentStart) return [];
    return [{ index, end }];
  });
  if (priors.length === 0) return "";
  const latestEnd = Math.max(...priors.map(({ end }) => end));
  const latest = priors.filter(({ end }) => end === latestEnd);
  return latest.length === 1 ? String(latest[0]!.index) : "";
}
type AnalysisListRow = Omit<AnalysisListItem, "analysisHref">;
type AnalysisPageState = Omit<AnalysisListPage, "items"> & { items: AnalysisListRow[] };
type LoadedEvidence = { analysisId: string; pages: AnalysisEvidencePage[] };
type LoadedReviews = AnalysisReviewPage & { analysisId: string; target: AnalysisReviewTarget };

const pendingAttemptPrefix = "ksi.analysis.pending.v2";
const legacyPendingAttemptPrefix = "ksi.analysis.pending.v1";
const maxStoredAttemptLength = 4_096;
const submissionRefPattern = /^ers-v1-[0-9a-f]{64}$/;
const activationBlockMessages = {
  ANALYSIS_ACTIVATION_UNAVAILABLE: "이 환경에서는 변화 분석 실행이 활성화되어 있지 않아 요청을 처리할 수 없습니다. 재시도로는 해결되지 않으니 운영자나 관리자에게 변화 분석 실행 활성화 상태를 확인해 달라고 요청하세요.",
  ANALYSIS_ACTIVATION_EXPIRED: "변화 분석 실행 활성화가 만료되어 요청을 처리할 수 없습니다. 재시도로는 해결되지 않으니 관리자에게 활성화를 갱신해 달라고 요청하세요.",
} as const;
type ActivationBlockCode = keyof typeof activationBlockMessages;

function isActivationBlockCode(value: unknown): value is ActivationBlockCode {
  return value === "ANALYSIS_ACTIVATION_UNAVAILABLE" || value === "ANALYSIS_ACTIVATION_EXPIRED";
}

function activationBlockCode(status: number, value: unknown): ActivationBlockCode | null {
  if (status !== 503 || !isRecord(value) || typeof value.code !== "string") return null;
  return isActivationBlockCode(value.code) ? value.code : null;
}

function pendingAttemptKey(scope: AttemptScope, prefix = pendingAttemptPrefix) {
  return `${prefix}:${encodeURIComponent(scope.organizationId)}:${encodeURIComponent(scope.principalId)}:${encodeURIComponent(scope.siteId)}`;
}

function isBoundedString(value: unknown, maximum: number): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= maximum;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function hasExactKeys(value: Record<string, unknown>, expected: readonly string[]) {
  const keys = Object.keys(value);
  return keys.length === expected.length && expected.every((key) => Object.hasOwn(value, key));
}

function parseSelector(value: unknown): AnalysisSelector | null {
  if (!isRecord(value) || !hasExactKeys(value, ["workOrderId", "submissionRef", "revision"])) return null;
  const { workOrderId, submissionRef, revision } = value;
  if (!isBoundedString(workOrderId, 255) || workOrderId.trim().length === 0 || !isBoundedString(submissionRef, 71) || !submissionRefPattern.test(submissionRef) || typeof revision !== "number" || !Number.isSafeInteger(revision) || revision <= 0) return null;
  return { workOrderId, submissionRef, revision };
}

function parseStoredAttempt(value: unknown, scope: AttemptScope, version: 1 | 2): Attempt | null {
  if (!isRecord(value) || !hasExactKeys(value, ["version", "organizationId", "principalId", "siteId", "attempt"]) || value.version !== version || value.organizationId !== scope.organizationId || value.principalId !== scope.principalId || value.siteId !== scope.siteId || !isRecord(value.attempt)) return null;
  const storedAttempt = value.attempt;
  let activationBlock: ActivationBlockCode | null;
  if (version === 1) {
    if (!hasExactKeys(storedAttempt, ["key", "workAreaId", "body"])) return null;
    activationBlock = null;
  } else {
    if (!hasExactKeys(storedAttempt, ["key", "workAreaId", "body", "activationBlockCode"]) || (storedAttempt.activationBlockCode !== null && !isActivationBlockCode(storedAttempt.activationBlockCode))) return null;
    activationBlock = storedAttempt.activationBlockCode;
  }
  const { key, workAreaId, body } = storedAttempt;
  if (!isBoundedString(key, 255) || key.trim().length === 0 || !isBoundedString(workAreaId, 255) || !isRecord(body) || !hasExactKeys(body, ["baseline", "current"])) return null;
  const baseline = parseSelector(body.baseline);
  const current = parseSelector(body.current);
  if (!baseline || !current || sameSelector(baseline, current)) return null;
  return { key, workAreaId, body: { baseline, current }, activationBlockCode: activationBlock };
}

function readPendingAttemptAtKey(key: string, scope: AttemptScope, version: 1 | 2): Attempt | null {
  try {
    const raw = window.sessionStorage.getItem(key);
    if (!raw) return null;
    if (raw.length > maxStoredAttemptLength) {
      window.sessionStorage.removeItem(key);
      return null;
    }
    try {
      const parsed: unknown = JSON.parse(raw);
      const attempt = parseStoredAttempt(parsed, scope, version);
      if (attempt) return attempt;
    } catch {
      // Invalid JSON is treated exactly like an invalid record below.
    }
    window.sessionStorage.removeItem(key);
  } catch {
    return null;
  }
  return null;
}

function readPendingAttempt(scope: AttemptScope): Attempt | null {
  const current = readPendingAttemptAtKey(pendingAttemptKey(scope), scope, 2);
  if (current) return current;

  const legacyKey = pendingAttemptKey(scope, legacyPendingAttemptPrefix);
  const legacy = readPendingAttemptAtKey(legacyKey, scope, 1);
  if (!legacy) return null;
  if (writePendingAttempt(scope, legacy)) {
    try {
      window.sessionStorage.removeItem(legacyKey);
    } catch {
      // The validated legacy attempt remains usable even if cleanup is unavailable.
    }
  }
  return legacy;
}

function writePendingAttempt(scope: AttemptScope, attempt: Attempt): boolean {
  const encoded = JSON.stringify({ version: 2, ...scope, attempt });
  try {
    window.sessionStorage.setItem(pendingAttemptKey(scope), encoded);
    return window.sessionStorage.getItem(pendingAttemptKey(scope)) === encoded;
  } catch {
    return false;
  }
}

function clearPendingAttempt(scope: AttemptScope | null): boolean {
  if (!scope) return true;
  try {
    const keys = [pendingAttemptKey(scope), pendingAttemptKey(scope, legacyPendingAttemptPrefix)];
    keys.forEach((key) => window.sessionStorage.removeItem(key));
    return keys.every((key) => window.sessionStorage.getItem(key) === null);
  } catch {
    return false;
  }
}

function sameSelector(left: AnalysisSelector, right: AnalysisSelector) {
  return left.workOrderId === right.workOrderId && left.submissionRef === right.submissionRef && left.revision === right.revision;
}

function selectorKey(selector: AnalysisSelector) {
  return `${selector.workOrderId}|${selector.submissionRef}|${selector.revision}`;
}

function createIdempotencyKey() {
  return `analysis-${crypto.randomUUID()}`;
}

function toListRow(analysis: AnalysisView): AnalysisListRow {
  return {
    analysisId: analysis.analysisId,
    siteId: analysis.siteId,
    workAreaId: analysis.workAreaId,
    executionState: analysis.executionState,
    suitabilityState: analysis.suitabilityState,
    createdAt: analysis.createdAt,
    resultId: analysis.result?.resultId ?? null,
    metrics: analysis.result?.metrics ?? null,
    limitationCount: analysis.blockers.length + (analysis.result?.limitationCodes.length ?? 0),
  };
}

function fromListPage(page: AnalysisListPage): AnalysisPageState {
  return {
    siteId: page.siteId,
    items: page.items.map((item) => ({
      analysisId: item.analysisId,
      siteId: item.siteId,
      workAreaId: item.workAreaId,
      executionState: item.executionState,
      suitabilityState: item.suitabilityState,
      createdAt: item.createdAt,
      resultId: item.resultId,
      metrics: item.metrics,
      limitationCount: item.limitationCount,
    })),
    nextCursor: page.nextCursor,
  };
}

function executionLabel(state: AnalysisView["executionState"]) {
  const labels = {
    NOT_STARTED: { label: "시작 전", tone: "neutral" },
    QUEUED: { label: "대기열", tone: "progress" },
    RUNNING: { label: "실행 중", tone: "progress" },
    COMPLETED: { label: "실행 완료", tone: "positive" },
    FAILED: { label: "실패", tone: "warning" },
  } as const;
  return labels[state];
}

function suitabilityLabel(state: AnalysisView["suitabilityState"]) {
  const labels = {
    BLOCKED: { label: "차단됨", tone: "warning" },
    REMEDIATION_REQUIRED: { label: "보완 필요", tone: "warning" },
    PROVISIONAL_ACCURACY_UNVERIFIED: { label: "정확도 미확인", tone: "progress" },
    EVALUATED: { label: "평가 근거 있음", tone: "positive" },
    REASSESSMENT_REQUIRED: { label: "재평가 필요", tone: "warning" },
  } as const;
  return labels[state];
}

function analysisCodeLabel(code: string): string {
  return getAnalysisIssueGuidance(code).label;
}

function formatNumber(value: number, suffix: string) {
  const rendered = Math.abs(value) > 0 && Math.abs(value) < 0.1
    ? formatSignificantKo(value, 3)
    : formatNumberKo(value, 1);
  return `${rendered} ${suffix}`;
}

function ResultIdentity({ result }: { result: AnalysisResult }) {
  return <details className="mt-3 text-[11.5px] text-ink-2">
    <summary className="tap-target cursor-pointer font-semibold text-ink-muted">처리 상세</summary>
    <dl className="mt-1 grid gap-1 border-l-2 border-line pl-3 sm:grid-cols-2">
      <div className="min-w-0"><dt className="text-ink-muted">결과 ID</dt><dd className="break-all">{result.resultId}</dd></div>
      <div className="min-w-0"><dt className="text-ink-muted">계산 시각</dt><dd>{formatKoreanDateTime(result.computedAt, { dateStyle: "short", timeStyle: "short" })}</dd></div>
      <div className="min-w-0"><dt className="text-ink-muted">보고서 확인값</dt><dd className="break-all">{result.reportDigest}</dd></div>
      <div className="min-w-0"><dt className="text-ink-muted">수치 결과 확인값</dt><dd className="break-all">{result.numericResultIdentityDigest}</dd></div>
    </dl>
  </details>;
}

function IssueCodeList({ codes }: { codes: string[] }) {
  return <ul className="mt-2 space-y-1 text-[12px] leading-5 text-ink-2" aria-label="결과 제한 사항">
    {codes.map((code, index) => <li key={`${code}-${index}`} className="flex flex-wrap items-center gap-x-2">
      <span>{analysisCodeLabel(code)}</span>
      <details>
        <summary className="tap-target inline-flex cursor-pointer items-center text-[11px] text-ink-muted">원문 코드</summary>
        <code className="break-all text-[11px] text-ink-muted">{code}</code>
      </details>
    </li>)}
  </ul>;
}

function MetricSummary({ summary, detail }: { summary: AnalysisListRow; detail: AnalysisView | null }) {
  const result = detail?.result;
  const metrics = result?.metrics ?? summary.metrics;
  if (!metrics) return null;
  // 같은 날 여러 기록이 있어도 랜드마크 이름이 겹치지 않게 생성 시각을 붙인다
  // (같은 이름의 랜드마크가 둘 이상이면 화면 낭독기에서 구분할 수 없다).
  const label = `계산 결과 · ${formatKoreanDateTime(summary.createdAt, { dateStyle: "medium", timeStyle: "short" })}`;
  return <section className="border-t border-line px-4 py-3" aria-label={label}>
    <h3 className="text-[13px] font-bold">계산 결과</h3>
    <dl className="mt-2 grid gap-2 border-t border-line pt-2 sm:grid-cols-3 sm:gap-3">
      <div className="min-w-0"><dt className="text-[12px] font-semibold text-ink-muted">절토</dt><dd className="num mt-1 break-words text-[16px] font-bold">{formatNumber(metrics.cutM3, "m³")}</dd></div>
      <div className="min-w-0"><dt className="text-[12px] font-semibold text-ink-muted">성토</dt><dd className="num mt-1 break-words text-[16px] font-bold">{formatNumber(metrics.fillM3, "m³")}</dd></div>
      <div className="min-w-0"><dt className="text-[12px] font-semibold text-ink-muted">순변화</dt><dd className="num mt-1 break-words text-[16px] font-bold">{formatNumber(metrics.netM3, "m³")}</dd></div>
    </dl>
    {result && <>
      <dl className="mt-3 grid gap-2 text-[12px] text-ink-2 sm:grid-cols-2">
        <div><dt className="text-ink-muted">선택 면적</dt><dd>{formatNumber(result.coverage.selectedAreaM2, "m²")}</dd></div>
        <div><dt className="text-ink-muted">공통 유효 면적</dt><dd>{formatNumber(result.coverage.commonValidAreaM2, "m²")}</dd></div>
        <div><dt className="text-ink-muted">선택 셀</dt><dd>{formatCountKo(result.coverage.selectedCellCount)}</dd></div>
        <div><dt className="text-ink-muted">공통 유효 셀</dt><dd>{formatCountKo(result.coverage.commonValidCellCount)}</dd></div>
      </dl>
      <p className="mt-2 text-[12px] leading-5 text-ink-muted">임계값 {formatNumber(metrics.thresholdM, "m")}: 높이 차이 기준으로 제외되는 셀이 없습니다. 공통 유효 영역은 두 관측에서 유효한 셀로 별도 제한됩니다.</p>
      <ResultIdentity result={result} />
      <p className="mt-2 text-[12px] leading-5 text-ink-muted">{detail.suitabilityState === "EVALUATED" ? "독립 평가 근거가 있습니다. 이 기록은 물량 정확도 보증, 측량 승인 또는 정산 사용 승인을 뜻하지 않습니다." : "독립 정확도 평가는 아직 확인되지 않았습니다. 이 기록은 물량 정확도 보증, 측량 승인 또는 정산 사용 승인을 뜻하지 않습니다."}</p>
      {result.limitationCodes.length > 0 && <IssueCodeList codes={result.limitationCodes} />}
    </>}
    {!result && summary.limitationCount > 0 && <p className="mt-2 text-[12px] text-ink-muted">제한 코드 {summary.limitationCount}개 · 상세에서 확인</p>}
  </section>;
}

function evidenceLines(item: AnalysisEvidenceItem): string[] {
  switch (item.kind) {
    case "EPOCH_IDENTITY": {
      const epoch = item.epoch === "BASELINE" ? "기준" : "현재";
      const artifactKind = isSupportedDataKind(item.artifactId)
        ? dataKindLabel(item.artifactId)
        : `자료 종류 확인 필요(원문: ${item.artifactId})`;
      return [
        `${epoch} 관측 기록 · ${item.observationEpochId}`,
        `선택 자료 정보 · 작업 지시 ${item.selector.workOrderId} · 제출 ${item.selector.submissionRef} · ${registrationVersionLabel(item.selector.revision)}`,
        `관측 좌표 기준 · ${item.observedCrsIdentifier} · 확인값 ${item.observedCrsDigest}`,
        `높이 기준 · ${item.verticalReferenceBasis} · ${item.verticalReferenceIdentifier} · ${item.verticalUnit}`,
        `${artifactKind} · 파일 확인값 ${item.observedSha256} · ${formatBytesKo(item.observedSizeBytes)}`,
        `검사 보고서 · ${item.inspectionReportDigest} · 기록 ${item.inspectionReportRecordId}`,
        `입력 확인값 · ${item.inputDigest}`,
      ];
    }
    case "CALCULATION_IDENTITY":
      return [
        `계산 기록 ID · ${item.calculation.calculationId}`,
        `작업구역 정의 확인값 · ${item.calculation.workAreaDefinitionDigest}`,
        `계산 프로필 · ${item.calculation.policy.profileId} · 프로필 확인값 ${item.calculation.policy.profileDigest}`,
        `정책 확인값 · ${item.calculation.policy.policyDigest}`,
        `실행 이미지 · ${item.calculation.runtime.runtimeImageVersion} · 이미지 확인값 ${item.calculation.runtime.runtimeImageOciDigest}`,
        `실행물 확인값 · ${item.calculation.runtime.workerExecutableDigest} · 빌드 확인값 ${item.calculation.runtime.workerBuildDigest}`,
      ];
    case "EVALUATION": {
      const outcome = item.outcome === "PASS" ? "통과" : item.outcome === "FAIL" ? "거부" : item.outcome === "UNASSESSED" ? "평가 전" : "확인 불가";
      return [
        `${item.epoch === "BASELINE" ? "기준" : "현재"} 관측 평가 · ${outcome} · 평가 버전 ${item.revision}`,
        `평가 기록 ID · ${item.evaluationId} · 확인값 ${item.evaluationDigest}`,
        `사유: ${item.reasonCodes.map(analysisEvidenceReasonLine).join(", ")}`,
        `평가 시각 · ${formatKoreanDateTime(item.assessedAt, { dateStyle: "short", timeStyle: "short" })}`,
      ];
    }
    case "CHECKPOINT_FACT": {
      const verdict = item.coreVerdict === "VALIDATED" ? "검증됨" : "거부됨";
      return [
        `검사점 근거 기록 · ${item.evidenceRecordId} · 판정 ${verdict}`,
        `평가 연결 · ${item.epoch === "BASELINE" ? "기준" : "현재"} 관측 · ${item.evaluationId} · 평가 버전 ${item.evaluationRevision}`,
        `참조 · ${item.evidenceRef} · 맥락 ${item.contextId}`,
        `근거 기록 확인값 · ${item.evidenceRecordDigest} · 목록 확인값 ${item.evidenceManifestDigest}`,
      ];
    }
    case "AUTHORITY_REFERENCE":
      return [
        `권위 기록 연결 · ${item.referenceName} · ${item.recordId}`,
        ...(item.sourceDigest ? [`원본 확인값 · ${item.sourceDigest}`] : []),
      ];
    case "SOURCE_REFERENCE":
      return [`출처 기록 연결 · ${item.referenceKind} · ${item.recordId}`, ...(item.sourceDigest ? [`출처 확인값 · ${item.sourceDigest}`] : [])];
    case "NUMERIC_RESULT":
      return [`수치 결과 기록 · ${item.resultId} · 보고서 ${item.reportDigest}`, `수치 결과 확인값 · ${item.numericResultIdentityDigest}`];
    case "LIMITATION":
      return [`제한 (${item.source}): ${analysisEvidenceReasonLine(item.code)}`, ...(item.detail ? [item.detail] : []), ...(item.evidenceRef ? [`근거 참조 · ${item.evidenceRef}`] : [])];
  }
}

function EvidenceSummary({ pages }: { pages: AnalysisEvidencePage[] }) {
  const items = pages.flatMap((page) => page.items);
  const first = pages[0];
  const hasMore = pages.at(-1)?.nextCursor !== null;
  return <section className="border-t border-line px-4 py-3" aria-label="근거">
    <h3 className="text-[13px] font-bold">근거</h3>
    {first && <p className="mt-1 break-all text-[11.5px] text-ink-muted">현재 불러온 근거 {formatCountKo(items.length)}개 · 근거 버전 {first.evidenceRevision} · 근거 목록 확인값 {first.evidenceDigest}</p>}
    <p className="mt-1 text-[11.5px] leading-5 text-ink-muted">{hasMore ? "현재 페이지까지 표시 중입니다. 다음 근거를 불러오면 이어서 확인할 수 있습니다." : "현재 불러온 페이지의 모든 근거 항목을 표시합니다. 각 항목을 펼치면 원문 ID와 확인값을 볼 수 있습니다."}</p>
    {items.length > 0 ? <ul className="mt-3 space-y-2">{items.map((item) => <li key={`${item.recordId}:${item.digest}`}>
      <details className="rounded-md border border-line bg-surface text-[12px] text-ink-2">
        <summary className="tap-target flex cursor-pointer flex-wrap items-center gap-x-2 px-3 py-2">
          <span className="font-semibold">{analysisEvidenceKindLabel(item.kind)}</span>
          <span className="min-w-0 break-words text-ink-muted">{analysisEvidenceSummary(item)}</span>
          {item.limitationCodes.length > 0 && <span className="basis-full break-words leading-5 text-high-ink">이 근거의 제한 · {item.limitationCodes.map(analysisCodeLabel).join(", ")}</span>}
        </summary>
        <div className="border-t border-line px-3 py-2">
          <p className="break-all font-semibold">기록 ID · {item.recordId}</p>
          <p className="mt-1 break-all text-ink-muted">확인값 · {item.digest}</p>
          <ul className="mt-2 space-y-1 break-all">{evidenceLines(item).map((line) => <li key={line}>{line}</li>)}</ul>
          {item.limitationCodes.length > 0 && <ul className="mt-2 space-y-1 break-all text-crit-ink" aria-label="근거 제한">{item.limitationCodes.map((code) => <li key={code}>제한 · {analysisEvidenceReasonLine(code)}</li>)}</ul>}
        </div>
      </details>
    </li>)}</ul> : <p className="mt-3 rounded-md border border-line bg-sunk/50 px-3 py-2 text-[12px] text-ink-2">Core가 반환한 근거 항목이 없습니다.</p>}
  </section>;
}

function NewerObservationNotice({ siteId, detail, observations, siteObservations, analyses }: {
  siteId: string;
  detail: AnalysisView;
  observations: readonly AttributedAnalysisObservation[];
  siteObservations: readonly AnalysisObservationOption[];
  analyses: readonly NewerAnalysisCandidate[];
}) {
  const { current: currentSelector, workAreaId } = detail;
  const resolved = useMemo(() => {
    // 결과 자신의 epoch 시각은 Site 범위 목록에서 귀속과 무관하게 찾는다.
    // 귀속 목록에만 있으면 귀속 없는 epoch의 결과에는 알림이 붙지 않는다.
    const currentEndedAt = findEpochCaptureEndedAt(siteObservations, currentSelector);
    if (!currentEndedAt) return null;
    const notice = deriveNewerObservationNotice({
      workAreaId,
      currentSelector,
      currentCaptureEndedAt: currentEndedAt,
      observations,
      analyses,
    });
    if (!notice) return null;
    return { notice, currentEndedAt };
  }, [currentSelector, workAreaId, observations, siteObservations, analyses]);
  if (!resolved) return null;
  const { notice, currentEndedAt } = resolved;
  const newerTime = formatKoreanDateTime(notice.captureEndedAt, { dateStyle: "medium", timeStyle: "short" });
  const currentTime = formatKoreanDateTime(currentEndedAt, { dateStyle: "medium", timeStyle: "short" });
  return <p className="border-t border-line px-4 py-2 text-[12px] leading-5 text-ink-2">
    이 작업구역에 더 새 관측이 있습니다. 새 관측 시각 {newerTime}. 이 결과는 {currentTime} 관측 기준 기록입니다.{" "}
    {notice.analysisId ? (
      <Link
        className="font-semibold text-accent-text hover:underline"
        href={`/sites/${encodeURIComponent(siteId)}/analysis?analysisId=${encodeURIComponent(notice.analysisId)}`}
      >
        새 분석 결과 보기
      </Link>
    ) : (
      "새 관측에 대한 분석 결과는 아직 없습니다."
    )}
  </p>;
}

function AnalysisCard({ summary, detail, selected, onSelect, evidencePages, siteId, workAreaId, workAreaName, scopeLine, canCreate, reviewState, reviewLoading, reviewError, onRefreshReview, onRefreshAfterReviewConflict, observations, siteObservations, newerAnalyses }: {
  summary: AnalysisListRow;
  detail: AnalysisView | null;
  selected: boolean;
  onSelect: () => void;
  evidencePages: AnalysisEvidencePage[];
  siteId: string;
  workAreaId: string;
  workAreaName: string;
  scopeLine: string | null;
  canCreate: boolean;
  reviewState: LoadedReviews | null;
  reviewLoading: boolean;
  reviewError: string | null;
  onRefreshReview: (analysisId: string) => Promise<boolean>;
  onRefreshAfterReviewConflict: (analysisId: string) => Promise<boolean>;
  observations: readonly AttributedAnalysisObservation[];
  siteObservations: readonly AnalysisObservationOption[];
  newerAnalyses: readonly NewerAnalysisCandidate[];
}) {
  const execution = executionLabel(summary.executionState);
  const suitability = suitabilityLabel(summary.suitabilityState);
  return <article id={`analysis-${summary.analysisId}`} className={`scroll-mt-5 rounded-lg border bg-surface ${selected ? "border-accent" : "border-line"}`}>
    <div className="flex flex-wrap items-start justify-between gap-3 px-4 py-3">
      <div className="min-w-0">
        <p className="text-[14px] font-bold">{analysisResultTitle(summary.createdAt)} · {formatKoreanDateTime(summary.createdAt, { timeStyle: "short" })}</p>
        <p className="mt-1 text-[12px] text-ink-2">{workAreaName} · {formatKoreanDateTime(summary.createdAt, { dateStyle: "medium", timeStyle: "short" })} 변화 분석 기록 생성</p>
        {scopeLine && <p className="mt-0.5 text-[12px] text-ink-2">{scopeLine}</p>}
        <details className="mt-1 text-[11px] text-ink-muted">
          <summary className="tap-target cursor-pointer font-semibold">처리 상세</summary>
          <p className="mt-1 break-all">분석 ID · {summary.analysisId}</p>
        </details>
      </div>
      <button type="button" className="btn" onClick={onSelect} aria-current={selected ? "page" : undefined}>이 변화 분석 보기</button>
    </div>
    {detail && <NewerObservationNotice siteId={siteId} detail={detail} observations={observations} siteObservations={siteObservations} analyses={newerAnalyses} />}
      <div className="grid gap-2 border-t border-line px-4 py-3 sm:grid-cols-2"><div><p className="mb-1 text-[12px] text-ink-muted">실행 상태</p><StateBadge label={execution.label} tone={execution.tone} /></div><div><p className="mb-1 text-[12px] text-ink-muted">적합성 상태</p><StateBadge label={suitability.label} tone={suitability.tone} /></div>{summary.executionState === "COMPLETED" && summary.suitabilityState === "REASSESSMENT_REQUIRED" && <p className="rounded-md bg-high-bg px-3 py-2 text-[12.5px] leading-5 text-high-ink sm:col-span-2">계산은 완료됐습니다. 현장 적합성은 재평가가 필요합니다.</p>}{summary.executionState === "FAILED" && <p className="rounded-md bg-crit-bg px-3 py-2 text-[12.5px] leading-5 text-crit-ink sm:col-span-2">{detail?.blockers.length ? "Core의 실패 사유와 필요한 조치를 아래에서 확인하세요. 원인을 확인하기 전에는 같은 요청을 반복하지 마세요." : canCreate ? "Core가 변화 분석을 완료하지 못했습니다. 아래 상세의 실패 사유를 검토하고 자료 또는 운영 담당자와 해결 여부를 확인하세요. 결과를 0으로 해석하거나 같은 요청을 바로 반복하지 마세요." : "Core가 변화 분석을 완료하지 못했습니다. 현장 변화 분석 담당자에게 실패 사유와 근거 검토를 요청하세요."}</p>}</div>
    {detail?.blockers.length ? <section className="border-t border-line px-4 py-3" aria-label="확인 및 보완"><h3 className="text-[13px] font-bold">확인 및 보완</h3><ul className="mt-2 space-y-2">{detail.blockers.map((blocker, index) => <AnalysisBlockerItem key={`${blocker.code}-${index}`} blocker={blocker} siteId={siteId} workAreaId={workAreaId} />)}</ul></section> : null}
    {detail ? <MetricSummary summary={summary} detail={detail} /> : !selected && summary.metrics ? <MetricSummary summary={summary} detail={null} /> : null}
    {selected && detail?.executionState === "COMPLETED" && detail.result && <AnalysisReviewSection
      siteId={siteId}
      analysisId={detail.analysisId}
      reviewState={reviewState}
      loading={reviewLoading}
      loadError={reviewError}
      canReview={canCreate}
      onRefresh={onRefreshReview}
      onRefreshAfterConflict={onRefreshAfterReviewConflict}
    />}
    {selected && evidencePages.length > 0 && <EvidenceSummary pages={evidencePages} />}
  </article>;
}

function isListPage(value: unknown): value is AnalysisListPage {
  return isRecord(value)
    && typeof value.siteId === "string"
    && Array.isArray(value.items)
    && value.items.length <= 50
    && (value.nextCursor === null || typeof value.nextCursor === "string");
}

function isAnalysisView(value: unknown): value is AnalysisView {
  return isRecord(value)
    && typeof value.analysisId === "string"
    && typeof value.siteId === "string"
    && typeof value.workAreaId === "string"
    && typeof value.executionState === "string"
    && typeof value.suitabilityState === "string"
    && Array.isArray(value.blockers)
    && typeof value.evidenceDigest === "string"
    && typeof value.evidenceRevision === "number"
    && (value.result === null || isRecord(value.result));
}

function isEvidencePage(value: unknown): value is AnalysisEvidencePage {
  return isRecord(value)
    && typeof value.analysisId === "string"
    && typeof value.evidenceDigest === "string"
    && typeof value.evidenceRevision === "number"
    && Array.isArray(value.items)
    && value.items.length <= 32
    && (value.nextCursor === null || typeof value.nextCursor === "string");
}

function isAnalysisReviewTarget(value: unknown): value is AnalysisReviewTarget {
  if (!isRecord(value) || !Array.isArray(value.evaluations) || value.evaluations.length !== 2) return false;
  const evaluation = (item: unknown, epoch: "BASELINE" | "CURRENT") => isRecord(item)
    && item.epoch === epoch
    && typeof item.evaluationId === "string"
    && typeof item.revision === "number"
    && Number.isSafeInteger(item.revision)
    && item.revision > 0
    && typeof item.evaluationDigest === "string";
  return typeof value.resultId === "string"
    && typeof value.resultRevision === "number"
    && Number.isSafeInteger(value.resultRevision)
    && value.resultRevision > 0
    && typeof value.reportDigest === "string"
    && typeof value.numericResultIdentityDigest === "string"
    && typeof value.calculationIdentityDigest === "string"
    && typeof value.admissionDigest === "string"
    && evaluation(value.evaluations[0], "BASELINE")
    && evaluation(value.evaluations[1], "CURRENT");
}

function isAnalysisReviewReceipt(value: unknown): value is AnalysisReviewReceipt {
  return isRecord(value)
    && typeof value.reviewRef === "string"
    && typeof value.reviewerId === "string"
    && (value.decision === "ACKNOWLEDGED" || value.decision === "NEEDS_FOLLOW_UP")
    && typeof value.comment === "string"
    && typeof value.reviewedAt === "string"
    && typeof value.receiptDigest === "string"
    && isAnalysisReviewTarget(value.target)
    && Array.isArray(value.factualLimitations)
    && value.factualLimitations.every((item) => typeof item === "string");
}

function isAnalysisReviewPage(value: unknown): value is AnalysisReviewPage & { target: AnalysisReviewTarget } {
  return isRecord(value)
    && isAnalysisReviewTarget(value.target)
    && Array.isArray(value.items)
    && value.items.length <= 50
    && value.items.every(isAnalysisReviewReceipt)
    && (value.nextCursor === null || typeof value.nextCursor === "string");
}

function analysisReviewDecisionLabel(decision: AnalysisReviewDecision): string {
  return decision === "ACKNOWLEDGED" ? "결과와 한계 확인" : "추가 확인·조치 필요";
}

function reviewResponseError(status: number): string {
  if (status === 401) return "세션이 만료되었습니다. 다시 로그인하세요.";
  if (status === 403) return "검토 기록에는 현장 쓰기 권한이 필요합니다. 권한 있는 현장 담당자에게 요청하세요.";
  if (status === 404) return "이 분석 결과는 아직 검토할 수 없습니다. 변화 분석 상세를 다시 불러오세요.";
  if (status === 409) return "변화 분석 기록이 갱신되었습니다. 상세를 다시 불러온 뒤 검토하세요.";
  if (status === 503) return "검토 기록 저장소를 사용할 수 없습니다. 잠시 후 검토 상태를 확인하세요.";
  return "검토 기록을 저장하지 못했습니다. 입력과 현장 상태를 확인하세요.";
}

function analysisReviewLoadError(status: number): string {
  if (status === 401) return "세션이 만료되었습니다. 다시 로그인하세요.";
  if (status === 403) return "검토 상태를 조회할 권한이 없습니다.";
  if (status === 404) return "검토할 결과를 찾을 수 없습니다. 변화 분석 상세를 다시 불러오세요.";
  if (status === 409) return "변화 분석 기록이 갱신되었습니다. 상세를 다시 불러오세요.";
  if (status === 503) return "검토 상태 저장소를 사용할 수 없습니다. 잠시 후 다시 시도하세요.";
  return "검토 상태를 불러오지 못했습니다.";
}

function reviewUrl(siteId: string, analysisId: string) {
  return `/api/sites/${encodeURIComponent(siteId)}/analyses/${encodeURIComponent(analysisId)}/reviews?limit=50`;
}

function AnalysisReviewAuditDetail({ review }: { review: AnalysisReviewReceipt }) {
  const { target } = review;
  return <details className="mt-2 rounded-md border border-line bg-surface px-3 py-2 text-[12px] text-ink-2">
    <summary className="tap-target flex cursor-pointer flex-wrap items-center gap-x-2 font-semibold">검토 기록 <span className="min-w-0 break-all font-normal text-ink-muted">· {analysisReviewDecisionLabel(review.decision)} · {review.reviewRef}</span></summary>
    <div className="mt-2 flex flex-col gap-1 break-all border-t border-line pt-2">
      <p>검토 기록 확인값 · {review.receiptDigest}</p>
      <p>검토 의견 · {review.comment}</p>
      <p>검토 대상 · {target.resultId} · 결과 버전 {target.resultRevision}</p>
      <p>보고서 확인값 · {target.reportDigest}</p>
      <p>수치 결과 확인값 · {target.numericResultIdentityDigest}</p>
      <p>계산 기록 확인값 · {target.calculationIdentityDigest}</p>
      <p>admission 확인값 · {target.admissionDigest}</p>
      {target.evaluations.map((evaluation) => <p key={evaluation.epoch}>
        {evaluation.epoch === "BASELINE" ? "기준" : "현재"} 평가 · {evaluation.evaluationId} · 평가 버전 {evaluation.revision} · {evaluation.evaluationDigest}
      </p>)}
      <p className="mt-1 text-ink-muted">검토 한계 · 정확도 검증, 현장·비행 권한, 정산·완료 증명을 뜻하지 않습니다.</p>
    </div>
  </details>;
}

function AnalysisReviewSection({
  siteId,
  analysisId,
  reviewState,
  loading,
  loadError,
  canReview,
  onRefresh,
  onRefreshAfterConflict,
}: {
  siteId: string;
  analysisId: string;
  reviewState: LoadedReviews | null;
  loading: boolean;
  loadError: string | null;
  canReview: boolean;
  onRefresh: (analysisId: string) => Promise<boolean>;
  onRefreshAfterConflict: (analysisId: string) => Promise<boolean>;
}) {
  const [decision, setDecision] = useState<AnalysisReviewDecision | "">("");
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [needsDetailRefresh, setNeedsDetailRefresh] = useState(false);
  const latest = reviewState ? latestAnalysisReview(reviewState.items) : null;
  const latestMatchesCurrentTarget = Boolean(latest && reviewState && sameAnalysisReviewTarget(latest.target, reviewState.target));
  const currentDecision = latestMatchesCurrentTarget && latest ? latest.decision : null;
  const status = needsDetailRefresh
    ? { label: "상세 새로고침 필요", tone: "warning" as const }
    : loading
      ? { label: "상태 확인 중", tone: "progress" as const }
      : loadError || !reviewState
        ? { label: "상태 확인 불가", tone: "warning" as const }
        : currentDecision === "ACKNOWLEDGED"
      ? { label: "확인됨", tone: "positive" as const }
      : currentDecision === "NEEDS_FOLLOW_UP"
        ? { label: "추가 확인·조치 필요", tone: "caution" as const }
        : { label: "미검토", tone: "neutral" as const };
  const commentLength = [...comment].length;
  const canSubmit = canReview
    && !loading
    && !busy
    && !loadError
    && Boolean(reviewState)
    && !needsDetailRefresh
    && Boolean(decision)
    && comment.trim().length > 0
    && commentLength <= 1_000;

  const submitReview = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canSubmit || !decision) return;
    setBusy(true);
    setActionError(null);
    setNotice(null);
    try {
      const response = await fetch(`/api/sites/${encodeURIComponent(siteId)}/analyses/${encodeURIComponent(analysisId)}/reviews`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ decision, comment: comment.trim() }),
      });
      const value: unknown = await response.json().catch(() => null);
      if (response.status === 403) throw new Error(reviewResponseError(403));
      if (response.status === 409) {
        setNeedsDetailRefresh(true);
        throw new Error(reviewResponseError(409));
      }
      if (!response.ok || !isAnalysisReviewReceipt(value)) {
        setNeedsDetailRefresh(true);
        throw new Error(response.status ? reviewResponseError(response.status) : "검토 기록 저장 여부를 확인하지 못했습니다. 먼저 상세를 새로고침하세요.");
      }

      setDecision("");
      setComment("");
      const refreshed = await onRefresh(analysisId);
      setNotice(refreshed
        ? "검토 기록을 저장하고 최신 상태를 다시 불러왔습니다."
        : "검토 기록은 저장됐지만 최신 상태를 불러오지 못했습니다. 상태를 새로고침하세요.");
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "검토 기록 저장 여부를 확인하지 못했습니다. 먼저 상세를 새로고침하세요.");
    } finally {
      setBusy(false);
    }
  };

  const refreshAfterConflict = async () => {
    setBusy(true);
    setActionError(null);
    setNotice(null);
    const refreshed = await onRefreshAfterConflict(analysisId);
    if (refreshed) setNeedsDetailRefresh(false);
    else setActionError("상세 또는 검토 상태를 새로 불러오지 못했습니다. 다시 시도하세요.");
    setBusy(false);
  };

  return <section className="border-t border-line px-4 py-3" aria-label="변화 분석 결과 검토">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h3 className="text-[13px] font-bold">결과 검토</h3>
      <StateBadge label={status.label} tone={status.tone} />
    </div>
    {loading && <p role="status" className="mt-2 text-[12px] text-ink-2">현재 결과 검토 상태를 불러오는 중입니다.</p>}
    {loadError && <div className="mt-2 flex flex-wrap items-center gap-2 text-[12px] text-crit-ink" role="alert">
      <span>{loadError}</span>
      <button type="button" className="btn" disabled={busy || loading} onClick={() => {
        if (loadError.includes("변화 분석 기록이 갱신되었습니다")) void refreshAfterConflict();
        else void onRefresh(analysisId);
      }}>{loadError.includes("변화 분석 기록이 갱신되었습니다") ? "변화 분석 상세 다시 불러오기" : "검토 상태 다시 불러오기"}</button>
    </div>}
    {!loading && !loadError && reviewState && <>
      {latest && !needsDetailRefresh
        ? <p className="mt-2 break-words text-[12px] text-ink-2">최근 검토 · {latest.reviewerId} · {formatKoreanDateTime(latest.reviewedAt, { dateStyle: "short", timeStyle: "short" })}</p>
        : !latest && !needsDetailRefresh
          ? <p className="mt-2 text-[12px] text-ink-2">현재 결과에 대한 검토 기록이 없습니다.</p>
          : null}
      {latest && !needsDetailRefresh && !latestMatchesCurrentTarget && <p className="mt-2 rounded-md bg-high-bg px-3 py-2 text-[12px] leading-5 text-high-ink">최근 기록은 이전 결과 또는 평가를 대상으로 해 현재 결과 검토로 인정되지 않습니다.</p>}
      {latest && !needsDetailRefresh && <AnalysisReviewAuditDetail review={latest} />}
    </>}
    {!loading && !loadError && !reviewState && <p className="mt-2 text-[12px] text-ink-2">현재 결과 검토 상태를 확인할 수 없습니다.</p>}
    <p className="mt-2 text-[11.5px] leading-5 text-ink-muted">이 검토는 결과 활용에 대한 사람의 기록이며 정확도 검증이나 정산·완료 승인이 아닙니다.</p>
    {actionError && <p role="alert" className="mt-3 rounded-md border border-crit bg-crit-bg px-3 py-2 text-[12px] leading-5 text-crit-ink">{actionError}</p>}
    {notice && <p role="status" className="mt-3 rounded-md border border-line bg-sunk/50 px-3 py-2 text-[12px] leading-5 text-ink-2">{notice}</p>}
    {needsDetailRefresh && <button type="button" className="btn mt-3" disabled={busy} onClick={() => void refreshAfterConflict()}>{busy ? "상세 다시 불러오는 중" : "변화 분석 상세 다시 불러오기"}</button>}
    {canReview ? <form className="mt-3 grid gap-3 border-t border-line pt-3" onSubmit={(event) => void submitReview(event)}>
      <fieldset className="grid gap-2 sm:grid-cols-2" disabled={busy || loading || Boolean(loadError) || needsDetailRefresh}>
        <legend className="mb-1 text-[12.5px] font-semibold">검토 결정 선택</legend>
        <label className="flex min-h-11 items-center gap-2 rounded-md border border-line px-3 py-2 text-[12.5px]">
          <input type="radio" name={`review-decision-${analysisId}`} value="ACKNOWLEDGED" checked={decision === "ACKNOWLEDGED"} onChange={() => { setDecision("ACKNOWLEDGED"); setActionError(null); }} />
          결과와 한계 확인
        </label>
        <label className="flex min-h-11 items-center gap-2 rounded-md border border-line px-3 py-2 text-[12.5px]">
          <input type="radio" name={`review-decision-${analysisId}`} value="NEEDS_FOLLOW_UP" checked={decision === "NEEDS_FOLLOW_UP"} onChange={() => { setDecision("NEEDS_FOLLOW_UP"); setActionError(null); }} />
          추가 확인·조치 필요
        </label>
      </fieldset>
      <label className="text-[12.5px] font-semibold" htmlFor={`review-comment-${analysisId}`}>검토 의견 <span className="font-normal text-ink-muted">· 필수, 최대 1,000자</span>
        <textarea
          id={`review-comment-${analysisId}`}
          className="input mt-1 min-h-24 w-full resize-y"
          required
          minLength={1}
          aria-invalid={commentLength > 1_000}
          aria-describedby={`review-comment-help-${analysisId}`}
          value={comment}
          disabled={busy || loading || Boolean(loadError) || needsDetailRefresh}
          onChange={(event) => { setComment(event.target.value); setActionError(null); }}
        />
        <span
          id={`review-comment-help-${analysisId}`}
          className={`mt-1 block text-right text-[11.5px] font-normal ${commentLength > 1_000 ? "text-crit-ink" : "text-ink-muted"}`}
          aria-live="polite"
        >
          {commentLength > 1_000 ? "최대 1,000자까지 입력할 수 있습니다. " : null}
          {formatCountKo(commentLength)} / 1,000자
        </span>
      </label>
      <div className="flex flex-wrap items-center gap-2">
        <button type="submit" className="btn btn-primary" disabled={!canSubmit}>{busy ? "검토 기록 중" : "검토 기록 추가"}</button>
        {!decision || comment.trim().length === 0 ? <p className="text-[11.5px] text-ink-muted">결정과 검토 의견을 입력하면 기록할 수 있습니다.</p> : null}
      </div>
    </form> : <div className="mt-3 border-t border-line pt-3"><ActionUnavailable label="검토 기록 추가" description="검토 기록 추가는 현장 쓰기 권한이 있는 담당자에게 요청하세요." /></div>}
  </section>;
}

function AnalysisBlockerItem({ blocker, siteId, workAreaId }: {
  blocker: AnalysisView["blockers"][number];
  siteId: string;
  workAreaId: string;
}) {
  const guidance = getAnalysisIssueGuidance(blocker.code);
  const sitePath = `/sites/${encodeURIComponent(siteId)}`;
  const evidencePath = `${sitePath}/spatial-assets?workAreaId=${encodeURIComponent(workAreaId)}`;
  const destination = guidance.destination === "work-areas"
    ? { href: `${sitePath}/work-areas`, label: "작업구역 현황 확인" }
    : guidance.destination === "spatial-assets"
      ? { href: evidencePath, label: "공간 자산 기록 확인" }
      : null;

  return <li className="rounded-md border border-line bg-surface px-3 py-3 text-[12.5px] leading-5 text-ink-2">
    <p className="font-semibold text-ink-1">{guidance.label}{blocker.epoch ? ` · ${blocker.epoch === "BASELINE" ? "기준 관측" : "현재 관측"}` : ""}</p>
    <p className="mt-1">{guidance.nextStep}</p>
    <p className="mt-1 text-[11.5px] text-ink-muted">확인 담당 · {guidance.owner}</p>
    {destination && <Link className="mt-2 inline-flex min-h-11 items-center text-[12px] font-semibold text-accent-text hover:underline" href={destination.href}>{destination.label}</Link>}
    <details className="mt-1">
      <summary className="tap-target flex cursor-pointer items-center text-[11.5px] font-semibold text-ink-muted">원문 코드·설명 보기</summary>
      <div className="break-all border-l-2 border-line pl-3 text-[11.5px] text-ink-muted">
        <p>기술 코드 · <code>{blocker.code}</code></p>
        {blocker.detail && <p className="mt-1">Core 설명 · {blocker.detail}</p>}
        {blocker.evidenceRef && <p className="mt-1">근거 참조 · {blocker.evidenceRef}</p>}
      </div>
    </details>
  </li>;
}

function listUrl(siteId: string, cursor?: string | null) {
  const query = new URLSearchParams({ limit: "50" });
  if (cursor) query.set("cursor", cursor);
  return `/api/sites/${encodeURIComponent(siteId)}/analyses?${query.toString()}`;
}

function evidenceUrl(siteId: string, analysisId: string, cursor?: string | null) {
  const query = new URLSearchParams({ limit: "32" });
  if (cursor) query.set("cursor", cursor);
  return `/api/sites/${encodeURIComponent(siteId)}/analyses/${encodeURIComponent(analysisId)}/evidence?${query.toString()}`;
}

export function AnalysisRequestPanel({
  siteId,
  workAreas,
  observations,
  siteObservations,
  unattributedObservationCount = 0,
  workOrderNames = {},
  initialPage,
  initialSelectedDetail,
  canCreate,
  initialAnalysisId,
  organizationId,
  principalId,
  initialWorkAreaId = "",
  initialCurrentWorkOrderId = null,
  scopeNotice = null,
  currentHintNotice = null,
}: {
  siteId: string;
  workAreas: readonly { workAreaId: string; name: string }[];
  observations: readonly AttributedAnalysisObservation[];
  /** Site 범위 관측 목록(귀속 무관). 결과 epoch 시각 조회 전용, Core 추가 조회 없음. */
  siteObservations: readonly AnalysisObservationOption[];
  unattributedObservationCount?: number;
  workOrderNames?: WorkOrderNameMap;
  initialPage: AnalysisListPage;
  initialSelectedDetail: AnalysisView | null;
  canCreate: boolean;
  initialAnalysisId: string | null;
  organizationId?: string;
  principalId?: string;
  initialWorkAreaId?: string;
  initialCurrentWorkOrderId?: string | null;
  scopeNotice?: string | null;
  currentHintNotice?: string | null;
}) {
  const router = useRouter();
  const firstPage = fromListPage(initialPage);
  const initialPinned = initialSelectedDetail && !firstPage.items.some((item) => item.analysisId === initialSelectedDetail.analysisId)
    ? [toListRow(initialSelectedDetail)]
    : [];
  const [pages, setPages] = useState<AnalysisPageState[]>([firstPage]);
  const pagesRef = useRef<AnalysisPageState[]>([firstPage]);
  const [pinnedRows, setPinnedRows] = useState<AnalysisListRow[]>(initialPinned);
  const pinnedRowsRef = useRef<AnalysisListRow[]>(initialPinned);
  const initialDetails = new Map<string, AnalysisView>();
  if (initialSelectedDetail) initialDetails.set(initialSelectedDetail.analysisId, initialSelectedDetail);
  const [details, setDetails] = useState<Map<string, AnalysisView>>(initialDetails);
  const detailsRef = useRef<Map<string, AnalysisView>>(initialDetails);
  const [selectedId, setSelectedId] = useState<string | null>(initialAnalysisId ?? initialPage.items[0]?.analysisId ?? null);
  const [workAreaId, setWorkAreaId] = useState(initialWorkAreaId ?? "");
  const [baselineIndex, setBaselineIndex] = useState("");
  const [currentIndex, setCurrentIndex] = useState(() => {
    if (!initialWorkAreaId || !initialCurrentWorkOrderId) return "";
    const matches = observations.flatMap((item, index) =>
      item.selector.workOrderId === initialCurrentWorkOrderId && item.workAreaIds.includes(initialWorkAreaId)
        ? [String(index)]
        : [],
    );
    return matches.length === 1 && matches[0] ? matches[0] : "";
  });
  const [baselineTouched, setBaselineTouched] = useState(false);
  const [areaSwitchNotice, setAreaSwitchNotice] = useState<string | null>(null);
  const [justCreatedId, setJustCreatedId] = useState<string | null>(null);
  const [attempt, setAttempt] = useState<Attempt | null>(null);
  const [activationBlock, setActivationBlock] = useState<ActivationBlockCode | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ analysisId: string | null; message: string } | null>(null);
  const [detailLoadingId, setDetailLoadingId] = useState<string | null>(null);
  const [listLoading, setListLoading] = useState(false);
  const [listLoadError, setListLoadError] = useState(false);
  const [listRestartRequired, setListRestartRequired] = useState(false);
  const [evidence, setEvidence] = useState<LoadedEvidence | null>(null);
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [evidenceRestartRequired, setEvidenceRestartRequired] = useState(false);
  const [reviewData, setReviewData] = useState<LoadedReviews | null>(null);
  const [reviewLoadingId, setReviewLoadingId] = useState<string | null>(null);
  const [reviewLoadError, setReviewLoadError] = useState<{ analysisId: string; message: string } | null>(null);
  const selectedIdRef = useRef<string | null>(selectedId);
  const mountedRef = useRef(true);
  const createController = useRef<AbortController | null>(null);
  const detailController = useRef<AbortController | null>(null);
  const evidenceController = useRef<AbortController | null>(null);
  const reviewController = useRef<AbortController | null>(null);
  const listController = useRef<AbortController | null>(null);
  const createGeneration = useRef(0);
  const detailGeneration = useRef(0);
  const evidenceGeneration = useRef(0);
  const reviewGeneration = useRef(0);
  const listGeneration = useRef(0);
  const pollGeneration = useRef(0);
  const attemptScope = useMemo(() => organizationId && principalId ? { organizationId, principalId, siteId } : null, [organizationId, principalId, siteId]);

  const rows = useMemo(() => {
    const unique = new Map<string, AnalysisListRow>();
    for (const row of [...pinnedRows, ...pages.flatMap((page) => page.items)]) {
      if (!unique.has(row.analysisId)) unique.set(row.analysisId, row);
    }
    return [...unique.values()];
  }, [pages, pinnedRows]);
  const selectedSummary = rows.find((item) => item.analysisId === selectedId) ?? null;
  const selectedDetail = selectedId ? details.get(selectedId) ?? null : null;
  const selectedExecutionState = selectedSummary?.executionState;
  const selectedReviewKey = selectedId && selectedDetail?.executionState === "COMPLETED" && selectedDetail.result
    ? [selectedId, selectedDetail.result.resultId, selectedDetail.result.reportDigest, selectedDetail.evidenceRevision, selectedDetail.evidenceDigest, selectedDetail.suitabilityState].join(":")
    : null;
  const hasTerminalItems = rows.some((item) => item.executionState === "COMPLETED" || item.executionState === "FAILED");
  const evidencePages = evidence?.analysisId === selectedId ? evidence.pages : [];
  const lastEvidencePage = evidencePages.at(-1);
  const nextListCursor = pages.at(-1)?.nextCursor ?? null;
  const workAreaNameById = new Map(workAreas.map((area) => [area.workAreaId, area.name]));
  const scopedObservations = useMemo<IndexedAnalysisObservation[]>(() => workAreaId
    ? observations.flatMap((item, index) => item.workAreaIds.includes(workAreaId) ? [{ item, index }] : [])
    : [], [observations, workAreaId]);
  const pickedBaseline = scopedObservations.find(({ index }) => String(index) === baselineIndex)?.item;
  const pickedCurrent = scopedObservations.find(({ index }) => String(index) === currentIndex)?.item;
  const choiceLabelByIndex = useMemo(() => {
    const labels = observationChoiceLabels(scopedObservations.map(({ item }) => item), workOrderNames);
    return new Map(scopedObservations.map(({ index }, position) => [String(index), labels[position]!]));
  }, [scopedObservations, workOrderNames]);
  const selectionReady = Boolean(workAreaId && pickedBaseline && pickedCurrent && !sameSelector(pickedBaseline.selector, pickedCurrent.selector));
  const observationBySelectorKey = useMemo(() => {
    const map = new Map<string, AttributedAnalysisObservation>();
    for (const option of observations) {
      map.set(selectorKey(option.selector), option);
    }
    return map;
  }, [observations]);
  // 새 관측 알림의 링크 후보: 이미 불러온 상세 중 결과가 실제로 있는 분석만.
  // 목록 요약에는 선택자가 없어 상세 없이는 새 관측과의 연결을 증명할 수
  // 없으므로, 읽지 못한 분석에는 가짜 링크를 만들지 않는다.
  const newerAnalyses = useMemo<NewerAnalysisCandidate[]>(() =>
    [...details.values()].map((view) => ({
      analysisId: view.analysisId,
      workAreaId: view.workAreaId,
      currentSelector: view.current,
      hasResult: view.result !== null,
    })), [details]);
  const scopeLineByAnalysisId = useMemo(() => {
    const lines = new Map<string, string>();
    for (const [analysisId, analysisDetail] of details) {
      const baseline = observationBySelectorKey.get(selectorKey(analysisDetail.baseline));
      const current = observationBySelectorKey.get(selectorKey(analysisDetail.current));
      if (!baseline && !current) continue;
      const part = (option: AttributedAnalysisObservation | undefined) =>
        option ? capturePeriodTitle(option.captureStartedAt, option.captureEndedAt) : "확인 불가";
      lines.set(analysisId, `비교 구간 · 기준 ${part(baseline)} → 현재 ${part(current)}`);
    }
    return lines;
  }, [details, observationBySelectorKey]);
  const selectedSelectors = pickedBaseline && pickedCurrent
    ? [{ label: "기준", selector: pickedBaseline.selector }, { label: "현재", selector: pickedCurrent.selector }]
    : [];
  const pairIssue = describePairSelection({
    workAreaId,
    baseline: pickedBaseline ? { captureStartedAt: pickedBaseline.captureStartedAt, captureEndedAt: pickedBaseline.captureEndedAt } : null,
    current: pickedCurrent ? { captureStartedAt: pickedCurrent.captureStartedAt, captureEndedAt: pickedCurrent.captureEndedAt } : null,
    sameSelection: Boolean(pickedBaseline && pickedCurrent && sameSelector(pickedBaseline.selector, pickedCurrent.selector)),
  });
  const pairBlocked = isKnownBadPairSelection(pairIssue.kind);
  // 보류 재시도(attempt)는 고정된 selector·멱등 키로만 다시 보낸다. 새 조합의
  // 시간 판독 게이트는 보류 재시도 경로에 적용하지 않는다.
  const canSubmit = !busy && (attempt !== null || (selectionReady && !pairBlocked));
  const latestRow = pages[0]?.items[0] ?? null;
  const latestNextAction = !latestRow
    ? ""
    : latestRow.executionState === "QUEUED" || latestRow.executionState === "RUNNING"
      ? "진행 중인 변화 분석입니다. 아래 이력에서 최신 상태를 확인하세요."
      : latestRow.executionState === "FAILED"
        ? "실패한 변화 분석이 있습니다. 아래 이력의 실패 사유와 보완 안내를 먼저 확인하세요."
        : latestRow.suitabilityState === "BLOCKED" || latestRow.suitabilityState === "REMEDIATION_REQUIRED" || latestRow.suitabilityState === "REASSESSMENT_REQUIRED"
          ? "적합성 확인이 필요합니다. 아래 이력의 확인 및 보완 안내를 확인하세요."
          : "최신 기록의 근거와 검토 상태를 아래에서 확인하세요. 이 기록은 정확도 보증이 아닙니다.";

  const setPagesAndRef = useCallback((update: (current: AnalysisPageState[]) => AnalysisPageState[]) => {
    const next = update(pagesRef.current);
    pagesRef.current = next;
    setPages(next);
    return next;
  }, []);

  const setPinnedAndRef = useCallback((update: (current: AnalysisListRow[]) => AnalysisListRow[]) => {
    const next = update(pinnedRowsRef.current);
    pinnedRowsRef.current = next;
    setPinnedRows(next);
  }, []);

  const setDetailsAndRef = useCallback((update: (current: Map<string, AnalysisView>) => Map<string, AnalysisView>) => {
    const next = update(detailsRef.current);
    detailsRef.current = next;
    setDetails(next);
  }, []);

  const retireDetail = useCallback((analysisId: string) => {
    setDetailsAndRef((current) => {
      const next = new Map(current);
      next.delete(analysisId);
      return next;
    });
    setEvidence((current) => current?.analysisId === analysisId ? null : current);
    if (selectedIdRef.current === analysisId) {
      evidenceGeneration.current += 1;
      evidenceController.current?.abort();
      setEvidenceLoading(false);
      setEvidenceRestartRequired(false);
      reviewGeneration.current += 1;
      reviewController.current?.abort();
      setReviewData(null);
      setReviewLoadingId(null);
      setReviewLoadError(null);
    }
  }, [setDetailsAndRef]);

  const upsertDetail = useCallback((detail: AnalysisView) => {
    const previous = detailsRef.current.get(detail.analysisId);
    setDetailsAndRef((current) => new Map(current).set(detail.analysisId, detail));
    if (selectedIdRef.current === detail.analysisId && (detail.executionState !== "COMPLETED" || !detail.result)) {
      reviewGeneration.current += 1;
      reviewController.current?.abort();
      setReviewData(null);
      setReviewLoadingId(null);
      setReviewLoadError(null);
    }
    if (previous && (previous.evidenceRevision !== detail.evidenceRevision || previous.evidenceDigest !== detail.evidenceDigest)) {
      setEvidence((current) => current?.analysisId === detail.analysisId ? null : current);
      setEvidenceRestartRequired(false);
    }
    const row = toListRow(detail);
    const foundInPages = pagesRef.current.some((page) => page.items.some((item) => item.analysisId === detail.analysisId));
    if (foundInPages) {
      setPagesAndRef((current) => current.map((page) => ({
        ...page,
        items: page.items.map((item) => item.analysisId === detail.analysisId ? row : item),
      })));
    } else {
      setPinnedAndRef((current) => [row, ...current.filter((item) => item.analysisId !== detail.analysisId)]);
    }
  }, [setDetailsAndRef, setPagesAndRef, setPinnedAndRef]);

  useEffect(() => { selectedIdRef.current = selectedId; }, [selectedId]);
  useEffect(() => {
    if (!attemptScope) return;
    const timer = setTimeout(() => {
      const restored = readPendingAttempt(attemptScope);
      if (!restored) return;
      setAttempt(restored);
      if (restored.activationBlockCode) {
        setActivationBlock(restored.activationBlockCode);
        setError({ analysisId: null, message: activationBlockMessages[restored.activationBlockCode] });
      }
      setWorkAreaId(restored.workAreaId);
      const baseline = observations.findIndex((option) => option.workAreaIds.includes(restored.workAreaId) && sameSelector(option.selector, restored.body.baseline));
      const current = observations.findIndex((option) => option.workAreaIds.includes(restored.workAreaId) && sameSelector(option.selector, restored.body.current));
      setBaselineIndex(baseline >= 0 ? String(baseline) : "");
      setCurrentIndex(current >= 0 ? String(current) : "");
      // 복원된 보류 선택은 사용자가 이미 고른 값이다. 이후 현재 관측 변경이
      // 기준을 조용히 덮어쓰지 않도록 직접 선택으로 취급한다.
      setBaselineTouched(true);
      setAreaSwitchNotice(null);
    }, 0);
    return () => clearTimeout(timer);
  }, [attemptScope, observations]);

  const discardAttempt = () => {
    if (!attempt) return true;
    if (!clearPendingAttempt(attemptScope)) {
      setError({ analysisId: null, message: "보류 요청을 제거하지 못했습니다. 다시 시도하세요." });
      return false;
    }
    setAttempt(null);
    setActivationBlock(null);
    setError(null);
    return true;
  };

  const choose = (analysisId: string, hasFreshDetail = false) => {
    if (analysisId === selectedIdRef.current) return;
    setJustCreatedId((current) => (current === analysisId ? current : null));
    if (!hasFreshDetail) retireDetail(analysisId);
    detailGeneration.current += 1;
    evidenceGeneration.current += 1;
    pollGeneration.current += 1;
    detailController.current?.abort();
    evidenceController.current?.abort();
    reviewGeneration.current += 1;
    reviewController.current?.abort();
    selectedIdRef.current = analysisId;
    setSelectedId(analysisId);
    setEvidence(null);
    setReviewData(null);
    setReviewLoadingId(null);
    setReviewLoadError(null);
    setEvidenceRestartRequired(false);
    setEvidenceLoading(false);
    setError(null);
    router.replace(`/sites/${encodeURIComponent(siteId)}/analysis?analysisId=${encodeURIComponent(analysisId)}`);
  };

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      createGeneration.current += 1;
      detailGeneration.current += 1;
      evidenceGeneration.current += 1;
      reviewGeneration.current += 1;
      pollGeneration.current += 1;
      createController.current?.abort();
      detailController.current?.abort();
      evidenceController.current?.abort();
      reviewController.current?.abort();
      listController.current?.abort();
    };
  }, []);

  const refreshDetail = useCallback(async (analysisId: string, generation: number) => {
    detailController.current?.abort();
    const controller = new AbortController();
    detailController.current = controller;
    if (mountedRef.current && selectedIdRef.current === analysisId && detailGeneration.current === generation) {
      setDetailLoadingId(analysisId);
    }
    try {
      const response = await fetch(
        `/api/sites/${encodeURIComponent(siteId)}/analyses/${encodeURIComponent(analysisId)}`,
        { cache: "no-store", signal: controller.signal },
      );
      const value: unknown = await response.json().catch(() => null);
      if (!response.ok || !isAnalysisView(value) || value.analysisId !== analysisId) {
        throw new Error(response.status === 409 ? "변화 분석 기록이 갱신되었습니다. 상세를 다시 불러오세요." : "변화 분석 상세를 불러오지 못했습니다.");
      }
      if (mountedRef.current && selectedIdRef.current === analysisId && detailGeneration.current === generation) {
        upsertDetail(value);
        setError((current) => current?.analysisId === analysisId ? null : current);
      }
    } catch (loadError) {
      if (!(loadError instanceof DOMException && loadError.name === "AbortError") && mountedRef.current && selectedIdRef.current === analysisId && detailGeneration.current === generation) {
        retireDetail(analysisId);
        setError({ analysisId, message: loadError instanceof Error ? loadError.message : "변화 분석 상세를 불러오지 못했습니다." });
      }
    } finally {
      if (mountedRef.current && selectedIdRef.current === analysisId && detailGeneration.current === generation) {
        setDetailLoadingId(null);
      }
    }
  }, [retireDetail, siteId, upsertDetail]);

  const loadReviewState = useCallback(async (analysisId: string): Promise<boolean> => {
    reviewController.current?.abort();
    const controller = new AbortController();
    reviewController.current = controller;
    const generation = ++reviewGeneration.current;
    if (mountedRef.current && selectedIdRef.current === analysisId) {
      setReviewData(null);
      setReviewLoadError(null);
      setReviewLoadingId(analysisId);
    }
    try {
      const response = await fetch(reviewUrl(siteId, analysisId), { cache: "no-store", signal: controller.signal });
      const value: unknown = await response.json().catch(() => null);
      if (!response.ok || !isAnalysisReviewPage(value)) throw new Error(analysisReviewLoadError(response.status));
      if (!mountedRef.current || controller.signal.aborted || selectedIdRef.current !== analysisId || reviewGeneration.current !== generation) return false;
      setReviewData({ analysisId, target: value.target, items: value.items, nextCursor: value.nextCursor });
      setReviewLoadError(null);
      return true;
    } catch (loadError) {
      if (loadError instanceof DOMException && loadError.name === "AbortError") return false;
      if (mountedRef.current && selectedIdRef.current === analysisId && reviewGeneration.current === generation) {
        setReviewData(null);
        setReviewLoadError({ analysisId, message: loadError instanceof Error ? loadError.message : "검토 상태를 불러오지 못했습니다." });
      }
      return false;
    } finally {
      if (mountedRef.current && selectedIdRef.current === analysisId && reviewGeneration.current === generation) setReviewLoadingId(null);
    }
  }, [siteId]);

  const fetchListPage = useCallback(async (cursor: string | null, signal: AbortSignal) => {
    const response = await fetch(listUrl(siteId, cursor), { cache: "no-store", signal });
    const payload: unknown = await response.json().catch(() => null);
    if (response.status === 409) return { stale: true as const };
    if (!response.ok || !isListPage(payload) || payload.siteId !== siteId) throw new Error("현장 변화 분석 목록을 불러오지 못했습니다.");
    return { stale: false as const, page: fromListPage(payload) };
  }, [siteId]);

  const refreshAnalyses = useCallback(async () => {
    listController.current?.abort();
    const controller = new AbortController();
    listController.current = controller;
    const generation = ++listGeneration.current;
    setListLoadError(false);
    setListLoading(true);
    try {
      const loaded = await fetchListPage(null, controller.signal);
      if (loaded.stale) {
        setListLoadError(true);
        setListRestartRequired(true);
        setError({ analysisId: selectedIdRef.current, message: "변화 분석 목록이 변경되었습니다. 첫 페이지부터 다시 불러오세요." });
        return;
      }
      if (!mountedRef.current || controller.signal.aborted || listGeneration.current !== generation) return;
      setPagesAndRef(() => [loaded.page]);
      // A completed execution can lose current numeric suitability without changing
      // its execution state. Retire contradicted cached detail before awaiting I/O.
      const invalidIds = new Set(loaded.page.items.filter((row) => {
        const cached = detailsRef.current.get(row.analysisId);
        if (!cached) return false;
        const previous = toListRow(cached);
        return previous.executionState !== row.executionState
          || previous.suitabilityState !== row.suitabilityState
          || previous.resultId !== row.resultId
          || JSON.stringify(previous.metrics) !== JSON.stringify(row.metrics);
      }).map((row) => row.analysisId));
      invalidIds.forEach(retireDetail);
      const freshIds = new Set(loaded.page.items.map((item) => item.analysisId));
      const selectedId = selectedIdRef.current;
      const selectedDetail = selectedId ? detailsRef.current.get(selectedId) : null;
      setPinnedAndRef((current) => {
        const remaining = current.filter((item) => !freshIds.has(item.analysisId));
        if (selectedDetail && !freshIds.has(selectedDetail.analysisId)) {
          return [toListRow(selectedDetail), ...remaining.filter((item) => item.analysisId !== selectedDetail.analysisId)];
        }
        return remaining;
      });
      setListLoadError(false);
      setListRestartRequired(false);
      setError((current) => current?.message.includes("변화 분석 목록") ? null : current);
      if (selectedId) await refreshDetail(selectedId, ++detailGeneration.current);
    } catch (loadError) {
      if (!(loadError instanceof DOMException && loadError.name === "AbortError") && mountedRef.current && listGeneration.current === generation) {
        setListLoadError(true);
        setError({ analysisId: selectedIdRef.current, message: loadError instanceof Error ? loadError.message : "현장 변화 분석 목록을 불러오지 못했습니다." });
      }
    } finally {
      if (mountedRef.current && listGeneration.current === generation) setListLoading(false);
    }
  }, [fetchListPage, refreshDetail, retireDetail, setPagesAndRef, setPinnedAndRef]);

  const refreshReviewAfterConflict = useCallback(async (analysisId: string): Promise<boolean> => {
    await refreshAnalyses();
    return loadReviewState(analysisId);
  }, [loadReviewState, refreshAnalyses]);

  const loadMoreAnalyses = async () => {
    const cursor = pagesRef.current.at(-1)?.nextCursor ?? null;
    if (!cursor || listLoading) return;
    listController.current?.abort();
    const controller = new AbortController();
    listController.current = controller;
    const generation = ++listGeneration.current;
    setListLoadError(false);
    setListLoading(true);
    try {
      const loaded = await fetchListPage(cursor, controller.signal);
      if (loaded.stale) {
        setListLoadError(true);
        setListRestartRequired(true);
        setError({ analysisId: selectedIdRef.current, message: "목록 페이지가 바뀌었습니다. 첫 페이지부터 다시 불러오세요." });
        return;
      }
      if (!mountedRef.current || listGeneration.current !== generation) return;
      setPagesAndRef((current) => [...current, loaded.page]);
      setListLoadError(false);
    } catch (loadError) {
      if (!(loadError instanceof DOMException && loadError.name === "AbortError") && mountedRef.current && listGeneration.current === generation) {
        setListLoadError(true);
        setError({ analysisId: selectedIdRef.current, message: loadError instanceof Error ? loadError.message : "변화 분석 목록을 불러오지 못했습니다." });
      }
    } finally {
      if (mountedRef.current && listGeneration.current === generation) setListLoading(false);
    }
  };

  const restartAnalyses = async () => {
    setPagesAndRef(() => []);
    setListRestartRequired(false);
    await refreshAnalyses();
  };

  useEffect(() => {
    if (!selectedId) return;
    const generation = ++detailGeneration.current;
    const detail = detailsRef.current.get(selectedId);
    if (!detail || selectedExecutionState === "COMPLETED" || selectedExecutionState === "FAILED") {
      void refreshDetail(selectedId, generation);
    }
    return () => detailController.current?.abort();
  }, [selectedExecutionState, selectedId, refreshDetail]);

  useEffect(() => {
    if (!selectedId || !selectedReviewKey) {
      reviewGeneration.current += 1;
      reviewController.current?.abort();
      return;
    }
    const timer = setTimeout(() => { void loadReviewState(selectedId); }, 0);
    return () => {
      clearTimeout(timer);
      reviewController.current?.abort();
    };
  }, [loadReviewState, selectedId, selectedReviewKey]);

  useEffect(() => {
    if (!hasTerminalItems) return;
    const refreshWhenVisible = () => { if (document.visibilityState === "visible") void refreshAnalyses(); };
    const timer = setInterval(refreshWhenVisible, 15_000);
    const refreshOnFocus = () => {
      void refreshAnalyses();
      if (selectedIdRef.current && selectedReviewKey) void loadReviewState(selectedIdRef.current);
    };
    window.addEventListener("focus", refreshOnFocus);
    document.addEventListener("visibilitychange", refreshWhenVisible);
    return () => {
      clearInterval(timer);
      window.removeEventListener("focus", refreshOnFocus);
      document.removeEventListener("visibilitychange", refreshWhenVisible);
    };
  }, [hasTerminalItems, loadReviewState, refreshAnalyses, selectedReviewKey]);

  useEffect(() => {
    if (!selectedId || (selectedExecutionState !== "QUEUED" && selectedExecutionState !== "RUNNING")) return;
    const generation = ++pollGeneration.current;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | null = null;
    let active = true;
    const canApply = () => active && mountedRef.current && selectedIdRef.current === selectedId && pollGeneration.current === generation;
    const schedule = () => { if (canApply()) timer = setTimeout(() => { void poll(); }, 3_000); };
    const poll = async () => {
      try {
        const response = await fetch(`/api/sites/${encodeURIComponent(siteId)}/analyses/${encodeURIComponent(selectedId)}`, { cache: "no-store", signal: controller.signal });
        const value: unknown = await response.json().catch(() => null);
        if (!response.ok || !isAnalysisView(value) || value.analysisId !== selectedId) throw new Error("변화 분석 상태를 새로 불러오지 못했습니다.");
        if (canApply()) {
          upsertDetail(value);
          setError((current) => current?.analysisId === selectedId ? null : current);
          if (value.executionState === "QUEUED" || value.executionState === "RUNNING") schedule();
        }
      } catch (pollError) {
        if (!(pollError instanceof DOMException && pollError.name === "AbortError") && canApply()) {
          setError({ analysisId: selectedId, message: pollError instanceof Error ? pollError.message : "변화 분석 상태를 새로 불러오지 못했습니다." });
          schedule();
        }
      }
    };
    schedule();
    return () => { active = false; controller.abort(); if (timer !== null) clearTimeout(timer); };
  }, [selectedExecutionState, selectedId, siteId, upsertDetail]);

  const submit = async () => {
    if (busy) return;
    let nextAttempt: Attempt | null = attempt ?? (() => {
      if (!workAreaId || baselineIndex === "" || currentIndex === "") {
        setError({ analysisId: null, message: "작업구역과 서로 다른 기준·현재 관측을 선택하세요." });
        return null;
      }
      const baseline = pickedBaseline;
      const current = pickedCurrent;
      if (!baseline || !current || sameSelector(baseline.selector, current.selector)) {
        setError({ analysisId: null, message: "작업구역과 서로 다른 기준·현재 관측을 선택하세요." });
        return null;
      }
      // Disabled 버튼만으로는 Enter·프로그래밍 제출을 막지 못한다. 알려진 문제
      // 조합(시간 역전·겹침·동일·구간 불명)은 attempt 생성·POST 전에 여기서도
      // 차단한다. 보류 재시도(attempt)는 이 분기를 타지 않는다.
      if (pairBlocked) {
        setError({ analysisId: null, message: pairIssue.message });
        return null;
      }
      const created: Attempt = { key: createIdempotencyKey(), workAreaId, body: { baseline: baseline.selector, current: current.selector }, activationBlockCode: null };
      if (!attemptScope || !writePendingAttempt(attemptScope, created)) {
        setError({ analysisId: null, message: "이 브라우저에서는 요청 재시도 정보를 저장할 수 없습니다. 다시 시도하세요." });
        return null;
      }
      setAttempt(created);
      return created;
    })();
    if (!nextAttempt) return;
    if (nextAttempt.activationBlockCode) {
      nextAttempt = { ...nextAttempt, activationBlockCode: null };
      if (attemptScope) writePendingAttempt(attemptScope, nextAttempt);
      setAttempt(nextAttempt);
    }
    setBusy(true);
    setError(null);
    setActivationBlock(null);
    const generation = ++createGeneration.current;
    createController.current?.abort();
    const controller = new AbortController();
    createController.current = controller;
    try {
      const response = await fetch(`/api/sites/${encodeURIComponent(siteId)}/work-areas/${encodeURIComponent(nextAttempt.workAreaId)}/analyses`, {
        method: "POST",
        headers: { "content-type": "application/json", "Idempotency-Key": nextAttempt.key },
        body: JSON.stringify(nextAttempt.body),
        signal: controller.signal,
      });
      const value: unknown = await response.json().catch(() => null);
      if (!mountedRef.current || createGeneration.current !== generation) return;
      const blockedBy = activationBlockCode(response.status, value);
      if (blockedBy) {
        const blockedAttempt = { ...nextAttempt, activationBlockCode: blockedBy };
        setAttempt(blockedAttempt);
        if (attemptScope) writePendingAttempt(attemptScope, blockedAttempt);
        setActivationBlock(blockedBy);
        setError({ analysisId: null, message: activationBlockMessages[blockedBy] });
        return;
      }
      if (!response.ok || !isAnalysisView(value)) throw new Error("요청을 다시 시도하세요.");
      if (!clearPendingAttempt(attemptScope)) throw new Error("요청은 접수됐지만 재시도 기록을 제거하지 못했습니다. 같은 요청으로 다시 확인하세요.");
      setAttempt(null);
      upsertDetail(value);
      setJustCreatedId(value.analysisId);
      choose(value.analysisId, true);
    } catch (requestError) {
      if (!(requestError instanceof DOMException && requestError.name === "AbortError") && mountedRef.current && createGeneration.current === generation) {
        setError({ analysisId: null, message: requestError instanceof Error ? requestError.message : "요청을 다시 시도하세요." });
      }
    } finally {
      if (mountedRef.current && createGeneration.current === generation) setBusy(false);
    }
  };

  const fetchEvidencePage = useCallback(async (analysisId: string, cursor: string | null, append: boolean) => {
    evidenceController.current?.abort();
    const controller = new AbortController();
    evidenceController.current = controller;
    const generation = ++evidenceGeneration.current;
    setEvidenceLoading(true);
    setError(null);
    try {
      const response = await fetch(evidenceUrl(siteId, analysisId, cursor), { cache: "no-store", signal: controller.signal });
      const value: unknown = await response.json().catch(() => null);
      if (response.status === 409) {
        setEvidenceRestartRequired(true);
        throw new Error("근거 개정이 변경되었습니다. 처음부터 다시 불러오세요.");
      }
      if (!response.ok || !isEvidencePage(value) || value.analysisId !== analysisId) throw new Error("근거를 불러오지 못했습니다.");
      const current = evidence?.analysisId === analysisId ? evidence.pages : [];
      const first = current[0];
      if (append && first && (first.evidenceDigest !== value.evidenceDigest || first.evidenceRevision !== value.evidenceRevision)) {
        setEvidenceRestartRequired(true);
        throw new Error("근거 개정이 변경되었습니다. 처음부터 다시 불러오세요.");
      }
      if (mountedRef.current && selectedIdRef.current === analysisId && evidenceGeneration.current === generation) {
        setEvidence({ analysisId, pages: append ? [...current, value] : [value] });
        setEvidenceRestartRequired(false);
      }
    } catch (loadError) {
      if (!(loadError instanceof DOMException && loadError.name === "AbortError") && mountedRef.current && selectedIdRef.current === analysisId && evidenceGeneration.current === generation) {
        setError({ analysisId, message: loadError instanceof Error ? loadError.message : "근거를 불러오지 못했습니다." });
      }
    } finally {
      if (mountedRef.current && selectedIdRef.current === analysisId && evidenceGeneration.current === generation) setEvidenceLoading(false);
    }
  }, [evidence, siteId]);

  const loadEvidence = () => {
    if (selectedId && !evidenceLoading) void fetchEvidencePage(selectedId, null, false);
  };
  const loadNextEvidence = () => {
    if (selectedId && lastEvidencePage?.nextCursor && !evidenceLoading) {
      void fetchEvidencePage(selectedId, lastEvidencePage.nextCursor, true);
    }
  };
  const restartEvidence = () => {
    setEvidence(null);
    setEvidenceRestartRequired(false);
    if (selectedId) void fetchEvidencePage(selectedId, null, false);
  };
  const collapseEvidence = () => {
    evidenceController.current?.abort();
    evidenceGeneration.current += 1;
    setEvidence(null);
    setEvidenceLoading(false);
    setEvidenceRestartRequired(false);
  };

  const selectedEvidencePages = evidence?.analysisId === selectedId ? evidence.pages : [];
  const evidenceLoaded = selectedEvidencePages.length > 0;
  const evidenceItemCount = selectedEvidencePages.reduce((total, page) => total + page.items.length, 0);
  const showError = error && (error.analysisId === null || error.analysisId === selectedId);

  return <div className="flex flex-col gap-4">
    {latestRow && <section aria-label="최근 변화 분석 요약" className="rounded-lg border border-line bg-surface px-4 py-3">
      <p className="text-[12.5px] leading-5 text-ink-2">
        <span className="font-bold text-ink-1">최근 변화 분석 요약</span>
        {` · 기록 ${rows.length}개${nextListCursor ? " 이상" : ""}`}
      </p>
      <p className="mt-1 text-[12px] leading-5 text-ink-2">최근 실행 상태: {executionLabel(latestRow.executionState).label}. 적합성 상태: {suitabilityLabel(latestRow.suitabilityState).label}.</p>
      <p className="mt-1 text-[12px] leading-5 text-ink-2">{latestNextAction}</p>
      <div className="mt-1 flex flex-wrap gap-x-5">
        <a href="#analysis-history" className="inline-flex min-h-11 items-center text-[12px] font-semibold text-accent-text hover:underline">변화 분석 이력으로 이동</a>
        {canCreate && <a href="#new-analysis-request" className="inline-flex min-h-11 items-center text-[12px] font-semibold text-accent-text hover:underline">{attempt ? "보류 요청 이어가기" : "새 변화 분석 요청으로 이동"}</a>}
      </div>
      {attempt && <p role="status" className="text-[12px] text-ink-2">중단된 요청이 남아 있습니다. 보류 요청에서 같은 요청 식별자로 확인하거나 취소할 수 있습니다.</p>}
    </section>}
    {!canCreate && <ActionUnavailable label="새 변화 분석 요청" description="새 변화 분석 요청은 권한 있는 현장 담당자가 진행해야 합니다. 필요한 작업구역과 관측을 담당자에게 알려 주세요." />}
    {showError && <div role="alert" className="rounded-lg border border-crit bg-crit-bg px-4 py-3 text-[12.5px] text-crit-ink">
      <span>{error.message}</span>
      {error.analysisId === selectedId && selectedId && <button type="button" className="btn ml-2" disabled={detailLoadingId === selectedId} onClick={() => void refreshDetail(selectedId, ++detailGeneration.current)}>{detailLoadingId === selectedId ? "상세 불러오는 중" : "변화 분석 상세 다시 불러오기"}</button>}
      {listRestartRequired && <button type="button" className="btn ml-2" disabled={listLoading} onClick={() => void restartAnalyses()}>{listLoading ? "목록 불러오는 중" : "목록 처음부터 다시 불러오기"}</button>}
      {evidenceRestartRequired && <button type="button" className="btn ml-2" disabled={evidenceLoading} onClick={restartEvidence}>{evidenceLoading ? "근거 불러오는 중" : "근거 처음부터 다시 불러오기"}</button>}
    </div>}
    {selectedId && selectedDetail && <div className="flex justify-end"><button type="button" className="btn" onClick={evidenceLoaded ? collapseEvidence : loadEvidence} disabled={evidenceLoading} aria-expanded={evidenceLoaded}>{evidenceLoading ? "근거 불러오는 중" : evidenceLoaded ? `근거 닫기 · ${evidenceItemCount}개 항목` : "근거 확인"}</button></div>}
    {selectedId && !selectedDetail && detailLoadingId === selectedId && <p role="status" className="rounded-lg border border-line bg-surface px-4 py-3 text-[12.5px]">변화 분석 상세를 불러오는 중입니다.</p>}
    <section id="analysis-history" className="flex flex-col gap-3" aria-label="변화 분석 이력">
      {rows.map((summary) => <AnalysisCard
        key={summary.analysisId}
        summary={summary}
        detail={details.get(summary.analysisId) ?? null}
        selected={summary.analysisId === selectedId}
        onSelect={() => choose(summary.analysisId)}
        evidencePages={summary.analysisId === selectedId ? selectedEvidencePages : []}
        siteId={siteId}
        workAreaId={summary.workAreaId}
        workAreaName={workAreaNameById.get(summary.workAreaId) ?? "이름을 확인할 수 없는 구역"}
        scopeLine={scopeLineByAnalysisId.get(summary.analysisId) ?? null}
        canCreate={canCreate}
        reviewState={reviewData?.analysisId === summary.analysisId ? reviewData : null}
        reviewLoading={reviewLoadingId === summary.analysisId}
        reviewError={reviewLoadError?.analysisId === summary.analysisId ? reviewLoadError.message : null}
        onRefreshReview={loadReviewState}
        onRefreshAfterReviewConflict={refreshReviewAfterConflict}
        observations={observations}
        newerAnalyses={newerAnalyses}
        siteObservations={siteObservations}
      />)}
      {rows.length === 0 && listLoading && <p role="status" className="rounded-lg border border-line bg-surface px-4 py-3 text-[13px] text-ink-2">변화 분석 목록을 불러오는 중입니다.</p>}
      {rows.length === 0 && !listLoading && !listLoadError && <p className="rounded-lg border border-line bg-surface px-4 py-3 text-[13px] leading-5 text-ink-2">{nextListCursor
        ? "현재 페이지에 변화 분석 요청이 없습니다. 다음 페이지를 불러와 나머지 이력을 확인하세요."
        : canCreate
          ? "이 현장에는 아직 변화 분석 요청이 없습니다. 새 변화 분석 요청에서 실제 작업구역과 관측 후보를 확인한 뒤 진행하세요."
          : "이 현장에는 아직 변화 분석 요청이 없습니다. 권한 있는 현장 담당자가 요청을 제출하면 상태와 근거가 여기에 표시됩니다."}</p>}
    </section>
    {lastEvidencePage?.nextCursor && <div className="flex justify-center"><button type="button" className="btn" disabled={evidenceLoading} onClick={loadNextEvidence}>{evidenceLoading ? "근거 불러오는 중" : "다음 근거 보기"}</button></div>}
    {nextListCursor && <div className="flex justify-center"><button type="button" className="btn" disabled={listLoading} onClick={() => void loadMoreAnalyses()}>{listLoading ? "변화 분석 목록 불러오는 중" : "다음 변화 분석 보기"}</button></div>}
    {canCreate && <section id="new-analysis-request" className="rounded-lg border border-line bg-surface px-4 py-4">
      <h2 className="text-[16px] font-bold">새 변화 분석 요청</h2>
      <ResponsiveActionBoundary action="ANALYSIS_REQUEST" reason="변화 분석 요청은 노트북 이상의 화면에서 진행하세요. 모바일에서는 결과와 근거 검토를 이어갈 수 있습니다.">
      <p className="mt-1 text-[12.5px] leading-5 text-ink-2">기준 관측과 현재 관측을 선택하면 Core가 권한·자료 적합성·계산 실행을 확인합니다. 이 화면은 그 판단을 대신하지 않습니다.</p>
      <p className="mt-1 text-[11.5px] leading-5 text-ink-muted">선택지는 작업명·촬영 구간으로 구분합니다. 겹치는 후보에만 등록 버전을, 그래도 겹치면 관측 기록 정보를 함께 표시합니다.</p>
      {unattributedObservationCount > 0 && <p className="mt-1 text-[11.5px] leading-5 text-ink-muted">작업구역 연결을 확인할 수 없는 관측은 선택지에서 제외했습니다.</p>}
      {scopeNotice && !attempt && <p role="status" className="mt-2 rounded-md border border-line bg-sunk/50 px-3 py-2 text-[11.5px] leading-5 text-ink-2">{scopeNotice}</p>}
      {currentHintNotice && !attempt && <p role="status" className="mt-2 rounded-md border border-line bg-sunk/50 px-3 py-2 text-[11.5px] leading-5 text-ink-2">{currentHintNotice} <Link className="font-semibold text-accent-text underline" href={`/sites/${encodeURIComponent(siteId)}/spatial-assets${workAreaId ? `?workAreaId=${encodeURIComponent(workAreaId)}` : ""}`}>등록 자료와 검사 상태 확인</Link></p>}
      {attempt && <p className="mt-2 text-[12px] text-ink-2">{activationBlock ? "보류된 요청은 변화 분석 실행 활성화가 복구되기 전에는 처리되지 않습니다. 활성화 상태가 확인된 뒤 다시 시도하거나 보류 요청을 취소하세요." : "중단된 요청이 있습니다. 다시 시도하면 같은 요청 식별자로 Core에 확인합니다."}</p>}
      <form className="mt-4 grid gap-3 lg:grid-cols-2" noValidate onSubmit={(event) => { event.preventDefault(); void submit(); }}>
        <label className="min-w-0 text-[12.5px] font-semibold lg:col-span-2">작업구역
          <select className="input mt-1 w-full" value={workAreaId} disabled={busy} onChange={(event) => { if (discardAttempt()) { setJustCreatedId(null); setWorkAreaId(event.target.value); setBaselineIndex(""); setCurrentIndex(""); setBaselineTouched(false); setAreaSwitchNotice("작업구역이 바뀌어 기준·현재 선택을 모두 지웠습니다. 바뀐 구역의 후보에서 다시 고르세요."); } }}>
            <option value="">작업구역 선택</option>
            {workAreas.map((area) => <option key={area.workAreaId} value={area.workAreaId}>{area.name}</option>)}
          </select>
        </label>
        <label className="min-w-0 text-[12.5px] font-semibold">기준 관측
          <select className="input mt-1 w-full" value={baselineIndex} disabled={busy || !workAreaId} onChange={(event) => { if (discardAttempt()) { setJustCreatedId(null); setBaselineIndex(event.target.value); setBaselineTouched(true); setAreaSwitchNotice(null); } }}>
            <option value="">{workAreaId ? "기준 관측 선택" : "먼저 작업구역 선택"}</option>
            {scopedObservations.map(({ item, index }) => <option key={`${item.observationEpochId}-${index}`} value={index}>{choiceLabelByIndex.get(String(index))}</option>)}
          </select>
        </label>
        <label className="min-w-0 text-[12.5px] font-semibold">현재 관측
          <select className="input mt-1 w-full" value={currentIndex} disabled={busy || !workAreaId} onChange={(event) => {
            if (!discardAttempt()) return;
            const value = event.target.value;
            setJustCreatedId(null); setCurrentIndex(value);
            setAreaSwitchNotice(null);
            // 직접 고른 기준은 현재 변경으로 덮어쓰지 않는다. 기준이 비어 있을
            // 때만 가장 최근 선행 관측을 제안하고, 요청은 직접 눌러야 한다.
            if (baselineTouched || !shouldAutoSuggestBaseline(baselineIndex)) return;
            const selected = scopedObservations.find(({ index }) => String(index) === value)?.item;
            setBaselineIndex(selected ? latestPriorObservationIndex(scopedObservations, selected) : "");
          }}>
            <option value="">{workAreaId ? "현재 관측 선택" : "먼저 작업구역 선택"}</option>
            {scopedObservations.map(({ item, index }) => <option key={`${item.observationEpochId}-${index}`} value={index}>{choiceLabelByIndex.get(String(index))}</option>)}
          </select>
        </label>
        <p className="text-[11.5px] leading-5 text-ink-muted lg:col-span-2">기준이 비어 있을 때만 현재 관측보다 앞서 끝난 가장 최근 관측을 제안합니다. 직접 고른 기준은 현재를 바꿔도 유지됩니다. 변화 분석 요청은 직접 눌러야 합니다.</p>
        {areaSwitchNotice && <p role="status" className="rounded-md border border-line bg-sunk/50 px-3 py-2 text-[11.5px] leading-5 text-ink-2 lg:col-span-2">{areaSwitchNotice}</p>}
        {pickedBaseline && pickedCurrent && <div className="rounded-md border border-line bg-sunk/50 px-3 py-2 text-[11.5px] leading-5 text-ink-2 lg:col-span-2" aria-live="polite">
          <p className="font-semibold">선택 확인 · 작업구역 연결은 Core가 요청 시 확인합니다.</p>
          <div className="mt-2 grid gap-2 sm:grid-cols-2">
            <p className="min-w-0 break-words rounded border border-line bg-surface px-2 py-1.5"><span className="font-semibold">기준</span> · {choiceLabelByIndex.get(baselineIndex)}</p>
            <p className="min-w-0 break-words rounded border border-line bg-surface px-2 py-1.5"><span className="font-semibold">현재</span> · {choiceLabelByIndex.get(currentIndex)}</p>
          </div>
          <details className="mt-1">
            <summary className="tap-target flex cursor-pointer items-center font-semibold">요청 선택 정보 전체 확인</summary>
            <dl className="grid gap-2 border-l-2 border-line pl-3 sm:grid-cols-2">
              {selectedSelectors.map(({ label, selector }) => (
                <div key={label} className="min-w-0">
                  <dt className="font-semibold">{label} 관측</dt>
                  <dd className="break-all">작업 지시 ID · {selector.workOrderId}</dd>
                  <dd className="break-all">관측 기록 ID · {(label === "기준" ? pickedBaseline : pickedCurrent).observationEpochId}</dd>
                  <dd className="break-all">제출 참조 · {selector.submissionRef}</dd>
                  <dd>{registrationVersionLabel(selector.revision)}</dd>
                </div>
              ))}
            </dl>
          </details>
        </div>}
        <div className="flex flex-wrap items-center gap-2 lg:col-span-2">
          <button type="submit" className="btn btn-primary" disabled={!canSubmit}>{busy ? "요청 중" : attempt ? "다시 시도" : "변화 분석 요청"}</button>
          {attempt && <button type="button" className="btn" disabled={busy} onClick={discardAttempt}>보류 요청 취소</button>}
          {!busy && !attempt && !areaSwitchNotice && pairIssue.kind !== "ready" && (workAreaId !== "" || baselineIndex !== "" || currentIndex !== "") && <p role="status" className="basis-full text-[12px] leading-5 text-ink-2">{pairIssue.message}</p>}
          {!busy && !attempt && workAreaId === "" && baselineIndex === "" && currentIndex === "" && <p className="text-[12px] leading-5 text-ink-2">작업구역과 서로 다른 기준·현재 관측을 고르면 요청할 수 있습니다.</p>}
        </div>
      </form>
      </ResponsiveActionBoundary>
      {justCreatedId && !attempt && (
        <p role="status" className="mt-3 rounded-md border border-line bg-sunk/50 px-3 py-2 text-[12.5px] leading-5 text-ink-2">
          요청이 접수됐습니다. 결과는 위 이력 맨 앞에 있습니다.{" "}
          <a href={`#analysis-${justCreatedId}`} className="font-semibold text-accent-text underline underline-offset-2">
            이번 분석 결과 보기
          </a>
        </p>
      )}
    </section>}
  </div>;
}
