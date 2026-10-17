"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { StateBadge } from "@/components/ui/StatusBadge";
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
  analysisEvidenceKindLabel,
  analysisEvidenceReasonLine,
  analysisEvidenceSummary,
  analysisObservationLabel,
  getAnalysisIssueGuidance,
} from "@/lib/analysis-guidance";

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
  ANALYSIS_ACTIVATION_UNAVAILABLE: "이 환경에서는 분석 실행이 활성화되어 있지 않아 요청을 처리할 수 없습니다. 재시도로는 해결되지 않으니 운영자나 관리자에게 분석 실행 활성화 상태를 확인해 달라고 요청하세요.",
  ANALYSIS_ACTIVATION_EXPIRED: "분석 실행 활성화가 만료되어 요청을 처리할 수 없습니다. 재시도로는 해결되지 않으니 관리자에게 활성화를 갱신해 달라고 요청하세요.",
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
  return <dl className="mt-3 grid gap-1 text-[11.5px] text-ink-2 sm:grid-cols-2">
    <div><dt className="text-ink-muted">결과 ID</dt><dd className="break-all">{result.resultId}</dd></div>
    <div><dt className="text-ink-muted">계산 시각</dt><dd>{formatKoreanDateTime(result.computedAt, { dateStyle: "short", timeStyle: "short" })}</dd></div>
    <div><dt className="text-ink-muted">보고서 digest</dt><dd className="break-all">{result.reportDigest}</dd></div>
    <div><dt className="text-ink-muted">수치 결과 ID digest</dt><dd className="break-all">{result.numericResultIdentityDigest}</dd></div>
  </dl>;
}

function IssueCodeList({ codes }: { codes: string[] }) {
  return <ul className="mt-2 space-y-1 text-[12px] leading-5 text-ink-2" aria-label="결과 제한 사항">
    {codes.map((code, index) => <li key={`${code}-${index}`} className="flex flex-wrap items-center gap-x-2">
      <span>{analysisCodeLabel(code)}</span>
      <details>
        <summary className="tap-target inline-flex cursor-pointer items-center text-[11px] text-ink-muted">Core 코드</summary>
        <code className="break-all text-[11px] text-ink-muted">{code}</code>
      </details>
    </li>)}
  </ul>;
}

function MetricSummary({ summary, detail }: { summary: AnalysisListRow; detail: AnalysisView | null }) {
  const result = detail?.result;
  const metrics = result?.metrics ?? summary.metrics;
  if (!metrics) return null;
  return <section className="border-t border-line px-4 py-3" aria-label="계산 결과">
    <h3 className="text-[13px] font-bold">계산 결과{summary.resultId ? ` · ${summary.resultId}` : ""}</h3>
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
    case "EPOCH_IDENTITY":
      return [
        `${item.epoch === "BASELINE" ? "기준" : "현재"} 관측 · ${item.observationEpochId}`,
        `선택: ${item.selector.workOrderId} · ${item.selector.submissionRef} · revision ${item.selector.revision}`,
        `CRS: ${item.observedCrsIdentifier} · ${item.observedCrsDigest}`,
        `높이 기준: ${item.verticalReferenceBasis} · ${item.verticalReferenceIdentifier} · ${item.verticalUnit}`,
        `DSM: ${item.observedSha256} · ${formatBytesKo(item.observedSizeBytes)}`,
        `검사 보고서: ${item.inspectionReportDigest} · ${item.inspectionReportRecordId}`,
        `입력 digest: ${item.inputDigest}`,
      ];
    case "CALCULATION_IDENTITY":
      return [
        `계산 ID: ${item.calculation.calculationId}`,
        `WorkArea 정의 digest: ${item.calculation.workAreaDefinitionDigest}`,
        `계산 프로필: ${item.calculation.policy.profileId} · ${item.calculation.policy.profileDigest}`,
        `정책 digest: ${item.calculation.policy.policyDigest}`,
        `런타임 이미지: ${item.calculation.runtime.runtimeImageVersion} · ${item.calculation.runtime.runtimeImageOciDigest}`,
        `실행물 digest: ${item.calculation.runtime.workerExecutableDigest} · ${item.calculation.runtime.workerBuildDigest}`,
      ];
    case "EVALUATION":
      return [
        `평가 ${item.epoch}: ${item.outcome} · revision ${item.revision}`,
        `평가 ID · digest: ${item.evaluationId} · ${item.evaluationDigest}`,
        `사유: ${item.reasonCodes.map(analysisEvidenceReasonLine).join(", ")}`,
        `평가 시각: ${formatKoreanDateTime(item.assessedAt, { dateStyle: "short", timeStyle: "short" })}`,
      ];
    case "CHECKPOINT_FACT":
      return [
        `검사점 근거: ${item.evidenceRecordId} · ${item.coreVerdict}`,
        `평가: ${item.epoch} · ${item.evaluationId} · revision ${item.evaluationRevision}`,
        `참조: ${item.evidenceRef} · context ${item.contextId}`,
        `근거 기록 digest: ${item.evidenceRecordDigest} · manifest ${item.evidenceManifestDigest}`,
      ];
    case "AUTHORITY_REFERENCE":
      return [
        `권위 참조: ${item.referenceName} · ${item.recordId}`,
        ...(item.sourceDigest ? [`원본 digest: ${item.sourceDigest}`] : []),
      ];
    case "SOURCE_REFERENCE":
      return [`출처 참조: ${item.referenceKind} · ${item.recordId}`, ...(item.sourceDigest ? [`출처 digest: ${item.sourceDigest}`] : [])];
    case "NUMERIC_RESULT":
      return [`수치 결과: ${item.resultId} · ${item.reportDigest}`, `결과 identity digest: ${item.numericResultIdentityDigest}`];
    case "LIMITATION":
      return [`제한 (${item.source}): ${analysisEvidenceReasonLine(item.code)}`, ...(item.detail ? [item.detail] : []), ...(item.evidenceRef ? [`근거 참조: ${item.evidenceRef}`] : [])];
  }
}

function EvidenceSummary({ pages }: { pages: AnalysisEvidencePage[] }) {
  const items = pages.flatMap((page) => page.items);
  const first = pages[0];
  const hasMore = pages.at(-1)?.nextCursor !== null;
  return <section className="border-t border-line px-4 py-3" aria-label="근거">
    <h3 className="text-[13px] font-bold">근거</h3>
    {first && <p className="mt-1 break-all text-[11.5px] text-ink-muted">현재 불러온 {formatCountKo(items.length)}개 항목 · 개정 {first.evidenceRevision} · evidence digest {first.evidenceDigest}</p>}
    <p className="mt-1 text-[11.5px] leading-5 text-ink-muted">{hasMore ? "현재 페이지까지 표시 중입니다. 다음 근거를 불러오면 이어서 확인할 수 있습니다." : "현재 불러온 페이지의 모든 근거 항목을 표시합니다. 각 항목을 펼치면 원문 ID와 digest를 확인할 수 있습니다."}</p>
    {items.length > 0 ? <ul className="mt-3 space-y-2">{items.map((item) => <li key={`${item.recordId}:${item.digest}`}>
      <details className="rounded-md border border-line bg-surface text-[12px] text-ink-2">
        <summary className="tap-target flex cursor-pointer flex-wrap items-center gap-x-2 px-3 py-2">
          <span className="font-semibold">{analysisEvidenceKindLabel(item.kind)}</span>
          <span className="min-w-0 break-words text-ink-muted">{analysisEvidenceSummary(item)}</span>
          {item.limitationCodes.length > 0 && <span className="basis-full break-words leading-5 text-high-ink">이 근거의 제한 · {item.limitationCodes.map(analysisCodeLabel).join(", ")}</span>}
        </summary>
        <div className="border-t border-line px-3 py-2">
          <p className="break-all font-semibold">기록 ID · {item.recordId}</p>
          <p className="mt-1 break-all text-ink-muted">digest · {item.digest}</p>
          <ul className="mt-2 space-y-1 break-all">{evidenceLines(item).map((line) => <li key={line}>{line}</li>)}</ul>
          {item.limitationCodes.length > 0 && <ul className="mt-2 space-y-1 break-all text-crit-ink" aria-label="근거 제한">{item.limitationCodes.map((code) => <li key={code}>제한 · {analysisEvidenceReasonLine(code)}</li>)}</ul>}
        </div>
      </details>
    </li>)}</ul> : <p className="mt-3 rounded-md border border-line bg-sunk/50 px-3 py-2 text-[12px] text-ink-2">Core가 반환한 근거 항목이 없습니다.</p>}
  </section>;
}

function AnalysisCard({ summary, detail, selected, onSelect, evidencePages, siteId, workAreaId, workAreaName, canCreate, reviewState, reviewLoading, reviewError, onRefreshReview, onRefreshAfterReviewConflict }: {
  summary: AnalysisListRow;
  detail: AnalysisView | null;
  selected: boolean;
  onSelect: () => void;
  evidencePages: AnalysisEvidencePage[];
  siteId: string;
  workAreaId: string;
  workAreaName: string;
  canCreate: boolean;
  reviewState: LoadedReviews | null;
  reviewLoading: boolean;
  reviewError: string | null;
  onRefreshReview: (analysisId: string) => Promise<boolean>;
  onRefreshAfterReviewConflict: (analysisId: string) => Promise<boolean>;
}) {
  const execution = executionLabel(summary.executionState);
  const suitability = suitabilityLabel(summary.suitabilityState);
  return <article className={`rounded-lg border bg-surface ${selected ? "border-accent" : "border-line"}`}>
    <div className="flex flex-wrap items-start justify-between gap-3 px-4 py-3">
      <div><p className="text-[14px] font-bold">{workAreaName} · {formatKoreanDateTime(summary.createdAt, { dateStyle: "short", timeStyle: "short" })}</p><p className="mt-1 break-all font-mono text-[10.5px] text-ink-muted">분석 ID · {summary.analysisId}</p></div>
      <button type="button" className="btn" onClick={onSelect} aria-current={selected ? "page" : undefined}>이 분석 보기</button>
    </div>
      <div className="grid gap-2 border-t border-line px-4 py-3 sm:grid-cols-2"><div><p className="mb-1 text-[12px] text-ink-muted">실행 상태</p><StateBadge label={execution.label} tone={execution.tone} /></div><div><p className="mb-1 text-[12px] text-ink-muted">적합성 상태</p><StateBadge label={suitability.label} tone={suitability.tone} /></div>{summary.executionState === "COMPLETED" && summary.suitabilityState === "REASSESSMENT_REQUIRED" && <p className="rounded-md bg-high-bg px-3 py-2 text-[12.5px] leading-5 text-high-ink sm:col-span-2">계산은 완료됐습니다. 현장 적합성은 재평가가 필요합니다.</p>}{summary.executionState === "FAILED" && <p className="rounded-md bg-crit-bg px-3 py-2 text-[12.5px] leading-5 text-crit-ink sm:col-span-2">{detail?.blockers.length ? "Core의 실패 사유와 필요한 조치를 아래에서 확인하세요. 원인을 확인하기 전에는 같은 요청을 반복하지 마세요." : canCreate ? "Core가 분석을 완료하지 못했습니다. 아래 상세의 실패 사유를 검토하고 자료 또는 운영 담당자와 해결 여부를 확인하세요. 결과를 0으로 해석하거나 같은 요청을 바로 반복하지 마세요." : "Core가 분석을 완료하지 못했습니다. 현장 분석 담당자에게 실패 사유와 근거 검토를 요청하세요."}</p>}</div>
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
  return decision === "ACKNOWLEDGED" ? "확인" : "후속 필요";
}

function reviewResponseError(status: number): string {
  if (status === 401) return "세션이 만료되었습니다. 다시 로그인하세요.";
  if (status === 403) return "검토 기록에는 현장 쓰기 권한이 필요합니다. 권한 있는 현장 담당자에게 요청하세요.";
  if (status === 404) return "이 분석 결과는 아직 검토할 수 없습니다. 분석 상세를 다시 불러오세요.";
  if (status === 409) return "분석 기록이 갱신되었습니다. 상세를 다시 불러온 뒤 검토하세요.";
  if (status === 503) return "검토 기록 저장소를 사용할 수 없습니다. 잠시 후 검토 상태를 확인하세요.";
  return "검토 기록을 저장하지 못했습니다. 입력과 현장 상태를 확인하세요.";
}

function analysisReviewLoadError(status: number): string {
  if (status === 401) return "세션이 만료되었습니다. 다시 로그인하세요.";
  if (status === 403) return "검토 상태를 조회할 권한이 없습니다.";
  if (status === 404) return "검토할 결과를 찾을 수 없습니다. 분석 상세를 다시 불러오세요.";
  if (status === 409) return "분석 기록이 갱신되었습니다. 상세를 다시 불러오세요.";
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
      <p>검토 다이제스트 · {review.receiptDigest}</p>
      <p>검토 의견 · {review.comment}</p>
      <p>검토 대상 · {target.resultId} · revision {target.resultRevision}</p>
      <p>보고서 다이제스트 · {target.reportDigest}</p>
      <p>수치 결과 ID 다이제스트 · {target.numericResultIdentityDigest}</p>
      <p>계산 identity 다이제스트 · {target.calculationIdentityDigest}</p>
      <p>admission 다이제스트 · {target.admissionDigest}</p>
      {target.evaluations.map((evaluation) => <p key={evaluation.epoch}>
        {evaluation.epoch === "BASELINE" ? "기준" : "현재"} 평가 · {evaluation.evaluationId} · revision {evaluation.revision} · {evaluation.evaluationDigest}
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
        ? { label: "후속 필요", tone: "caution" as const }
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

  return <section className="border-t border-line px-4 py-3" aria-label="분석 결과 검토">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h3 className="text-[13px] font-bold">결과 검토</h3>
      <StateBadge label={status.label} tone={status.tone} />
    </div>
    {loading && <p role="status" className="mt-2 text-[12px] text-ink-2">현재 결과 검토 상태를 불러오는 중입니다.</p>}
    {loadError && <div className="mt-2 flex flex-wrap items-center gap-2 text-[12px] text-crit-ink" role="alert">
      <span>{loadError}</span>
      <button type="button" className="btn" disabled={busy || loading} onClick={() => {
        if (loadError.includes("분석 기록이 갱신되었습니다")) void refreshAfterConflict();
        else void onRefresh(analysisId);
      }}>{loadError.includes("분석 기록이 갱신되었습니다") ? "분석 상세 다시 불러오기" : "검토 상태 다시 불러오기"}</button>
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
    {needsDetailRefresh && <button type="button" className="btn mt-3" disabled={busy} onClick={() => void refreshAfterConflict()}>{busy ? "상세 다시 불러오는 중" : "분석 상세 다시 불러오기"}</button>}
    {canReview ? <form className="mt-3 grid gap-3 border-t border-line pt-3" onSubmit={(event) => void submitReview(event)}>
      <fieldset className="grid gap-2 sm:grid-cols-2" disabled={busy || loading || Boolean(loadError) || needsDetailRefresh}>
        <legend className="mb-1 text-[12.5px] font-semibold">검토 결정 선택</legend>
        <label className="flex min-h-11 items-center gap-2 rounded-md border border-line px-3 py-2 text-[12.5px]">
          <input type="radio" name={`review-decision-${analysisId}`} value="ACKNOWLEDGED" checked={decision === "ACKNOWLEDGED"} onChange={() => { setDecision("ACKNOWLEDGED"); setActionError(null); }} />
          확인
        </label>
        <label className="flex min-h-11 items-center gap-2 rounded-md border border-line px-3 py-2 text-[12.5px]">
          <input type="radio" name={`review-decision-${analysisId}`} value="NEEDS_FOLLOW_UP" checked={decision === "NEEDS_FOLLOW_UP"} onChange={() => { setDecision("NEEDS_FOLLOW_UP"); setActionError(null); }} />
          후속 필요
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
    </form> : <p className="mt-3 border-t border-line pt-3 text-[12px] leading-5 text-ink-2">검토 기록 추가는 현장 쓰기 권한이 있는 담당자에게 요청하세요.</p>}
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
      <summary className="tap-target flex cursor-pointer items-center text-[11.5px] font-semibold text-ink-muted">Core 코드·원문 설명 보기</summary>
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
  unattributedObservationCount = 0,
  initialPage,
  initialSelectedDetail,
  canCreate,
  initialAnalysisId,
  organizationId,
  principalId,
}: {
  siteId: string;
  workAreas: readonly { workAreaId: string; name: string }[];
  observations: readonly AttributedAnalysisObservation[];
  unattributedObservationCount?: number;
  initialPage: AnalysisListPage;
  initialSelectedDetail: AnalysisView | null;
  canCreate: boolean;
  initialAnalysisId: string | null;
  organizationId?: string;
  principalId?: string;
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
  const [workAreaId, setWorkAreaId] = useState("");
  const [baselineIndex, setBaselineIndex] = useState("");
  const [currentIndex, setCurrentIndex] = useState("");
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
  const selectionReady = Boolean(workAreaId && pickedBaseline && pickedCurrent && !sameSelector(pickedBaseline.selector, pickedCurrent.selector));
  const selectedSelectors = pickedBaseline && pickedCurrent
    ? [{ label: "기준", selector: pickedBaseline.selector }, { label: "현재", selector: pickedCurrent.selector }]
    : [];
  const canSubmit = !busy && (attempt !== null || selectionReady);

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
        throw new Error(response.status === 409 ? "분석 기록이 갱신되었습니다. 상세를 다시 불러오세요." : "분석 상세를 불러오지 못했습니다.");
      }
      if (mountedRef.current && selectedIdRef.current === analysisId && detailGeneration.current === generation) {
        upsertDetail(value);
        setError((current) => current?.analysisId === analysisId ? null : current);
      }
    } catch (loadError) {
      if (!(loadError instanceof DOMException && loadError.name === "AbortError") && mountedRef.current && selectedIdRef.current === analysisId && detailGeneration.current === generation) {
        retireDetail(analysisId);
        setError({ analysisId, message: loadError instanceof Error ? loadError.message : "분석 상세를 불러오지 못했습니다." });
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
    if (!response.ok || !isListPage(payload) || payload.siteId !== siteId) throw new Error("현장 분석 목록을 불러오지 못했습니다.");
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
        setError({ analysisId: selectedIdRef.current, message: "분석 목록이 변경되었습니다. 첫 페이지부터 다시 불러오세요." });
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
      setError((current) => current?.message.includes("분석 목록") ? null : current);
      if (selectedId) await refreshDetail(selectedId, ++detailGeneration.current);
    } catch (loadError) {
      if (!(loadError instanceof DOMException && loadError.name === "AbortError") && mountedRef.current && listGeneration.current === generation) {
        setListLoadError(true);
        setError({ analysisId: selectedIdRef.current, message: loadError instanceof Error ? loadError.message : "현장 분석 목록을 불러오지 못했습니다." });
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
        setError({ analysisId: selectedIdRef.current, message: loadError instanceof Error ? loadError.message : "분석 목록을 불러오지 못했습니다." });
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
        if (!response.ok || !isAnalysisView(value) || value.analysisId !== selectedId) throw new Error("분석 상태를 새로 불러오지 못했습니다.");
        if (canApply()) {
          upsertDetail(value);
          setError((current) => current?.analysisId === selectedId ? null : current);
          if (value.executionState === "QUEUED" || value.executionState === "RUNNING") schedule();
        }
      } catch (pollError) {
        if (!(pollError instanceof DOMException && pollError.name === "AbortError") && canApply()) {
          setError({ analysisId: selectedId, message: pollError instanceof Error ? pollError.message : "분석 상태를 새로 불러오지 못했습니다." });
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
    {canCreate && <section id="new-analysis-request" className="rounded-lg border border-line bg-surface px-4 py-4">
      <h2 className="text-[16px] font-bold">새 분석 요청</h2>
      <p className="mt-1 text-[12.5px] leading-5 text-ink-2">기준 관측과 현재 관측을 선택하면 Core가 권한·자료 적합성·계산 실행을 확인합니다. 이 화면은 그 판단을 대신하지 않습니다.</p>
      <p className="mt-1 text-[11.5px] leading-5 text-ink-muted">선택지는 촬영 구간·기존 epoch ID·제출 revision으로 구분합니다. 목록에 없는 구역 연결이나 분석 적합성을 추정하지 않습니다.</p>
      {unattributedObservationCount > 0 && <p className="mt-1 text-[11.5px] leading-5 text-ink-muted">작업구역 연결을 확인할 수 없는 관측은 선택지에서 제외했습니다.</p>}
      {attempt && <p className="mt-2 text-[12px] text-ink-2">{activationBlock ? "보류된 요청은 분석 실행 활성화가 복구되기 전에는 처리되지 않습니다. 활성화 상태가 확인된 뒤 다시 시도하거나 보류 요청을 취소하세요." : "중단된 요청이 있습니다. 다시 시도하면 같은 요청 식별자로 Core에 확인합니다."}</p>}
      <form className="mt-4 grid gap-3 sm:grid-cols-3" noValidate onSubmit={(event) => { event.preventDefault(); void submit(); }}>
        <label className="text-[12.5px] font-semibold">작업구역
          <select className="input mt-1 w-full" value={workAreaId} disabled={busy} onChange={(event) => { if (discardAttempt()) { setWorkAreaId(event.target.value); setBaselineIndex(""); setCurrentIndex(""); } }}>
            <option value="">작업구역 선택</option>
            {workAreas.map((area) => <option key={area.workAreaId} value={area.workAreaId}>{area.name}</option>)}
          </select>
        </label>
        <label className="text-[12.5px] font-semibold">기준 관측
          <select className="input mt-1 w-full" value={baselineIndex} disabled={busy || !workAreaId} onChange={(event) => { if (discardAttempt()) setBaselineIndex(event.target.value); }}>
            <option value="">{workAreaId ? "기준 관측 선택" : "먼저 작업구역 선택"}</option>
            {scopedObservations.map(({ item, index }) => <option key={`${item.observationEpochId}-${index}`} value={index}>{analysisObservationLabel(item)}</option>)}
          </select>
        </label>
        <label className="text-[12.5px] font-semibold">현재 관측
          <select className="input mt-1 w-full" value={currentIndex} disabled={busy || !workAreaId} onChange={(event) => {
            if (!discardAttempt()) return;
            const value = event.target.value;
            const selected = scopedObservations.find(({ index }) => String(index) === value)?.item;
            setCurrentIndex(value);
            setBaselineIndex(selected ? latestPriorObservationIndex(scopedObservations, selected) : "");
          }}>
            <option value="">{workAreaId ? "현재 관측 선택" : "먼저 작업구역 선택"}</option>
            {scopedObservations.map(({ item, index }) => <option key={`${item.observationEpochId}-${index}`} value={index}>{analysisObservationLabel(item)}</option>)}
          </select>
        </label>
        <p className="text-[11.5px] leading-5 text-ink-muted sm:col-span-3">가능한 경우 현재 관측보다 앞서 끝난 가장 최근 관측을 기준으로 제안합니다. 기준은 수정할 수 있고, 분석 요청은 직접 눌러야 합니다.</p>
        {pickedBaseline && pickedCurrent && <div className="rounded-md border border-line bg-sunk/50 px-3 py-2 text-[11.5px] leading-5 text-ink-2 sm:col-span-3" aria-live="polite">
          <p className="font-semibold">선택 확인 · 작업구역 연결은 Core가 요청 시 확인합니다.</p>
          <p className="mt-1 break-words">기준 · {analysisObservationLabel(pickedBaseline)}</p>
          <p className="break-words">현재 · {analysisObservationLabel(pickedCurrent)}</p>
          <details className="mt-1">
            <summary className="tap-target flex cursor-pointer items-center font-semibold">요청 selector 전체 확인</summary>
            <dl className="grid gap-2 border-l-2 border-line pl-3 sm:grid-cols-2">
              {selectedSelectors.map(({ label, selector }) => (
                <div key={label} className="min-w-0">
                  <dt className="font-semibold">{label} 관측</dt>
                  <dd className="break-all">작업 지시 ID · {selector.workOrderId}</dd>
                  <dd className="break-all">제출 참조 · {selector.submissionRef}</dd>
                  <dd>revision · {selector.revision}</dd>
                </div>
              ))}
            </dl>
          </details>
        </div>}
        <div className="flex flex-wrap items-center gap-2 sm:col-span-3">
          <button type="submit" className="btn btn-primary" disabled={!canSubmit}>{busy ? "요청 중" : attempt ? "다시 시도" : "분석 요청"}</button>
          {attempt && <button type="button" className="btn" disabled={busy} onClick={discardAttempt}>보류 요청 취소</button>}
          {!busy && !attempt && !selectionReady && <p className="text-[12px] leading-5 text-ink-2">작업구역과 서로 다른 기준·현재 관측을 고르면 요청할 수 있습니다.</p>}
        </div>
      </form>
    </section>}
    {!canCreate && <p className="rounded-lg border border-line bg-surface px-4 py-3 text-[12.5px] text-ink-2">분석 기록을 조회할 수 있습니다. 새 분석 요청은 권한 있는 현장 담당자에게 맡겨 주세요.</p>}
    {showError && <div role="alert" className="rounded-lg border border-crit bg-crit-bg px-4 py-3 text-[12.5px] text-crit-ink">
      <span>{error.message}</span>
      {error.analysisId === selectedId && selectedId && <button type="button" className="btn ml-2" disabled={detailLoadingId === selectedId} onClick={() => void refreshDetail(selectedId, ++detailGeneration.current)}>{detailLoadingId === selectedId ? "상세 불러오는 중" : "분석 상세 다시 불러오기"}</button>}
      {listRestartRequired && <button type="button" className="btn ml-2" disabled={listLoading} onClick={() => void restartAnalyses()}>{listLoading ? "목록 불러오는 중" : "목록 처음부터 다시 불러오기"}</button>}
      {evidenceRestartRequired && <button type="button" className="btn ml-2" disabled={evidenceLoading} onClick={restartEvidence}>{evidenceLoading ? "근거 불러오는 중" : "근거 처음부터 다시 불러오기"}</button>}
    </div>}
    {selectedId && selectedDetail && <div className="flex justify-end"><button type="button" className="btn" onClick={evidenceLoaded ? collapseEvidence : loadEvidence} disabled={evidenceLoading} aria-expanded={evidenceLoaded}>{evidenceLoading ? "근거 불러오는 중" : evidenceLoaded ? `근거 닫기 · ${evidenceItemCount}개 항목` : "근거 확인"}</button></div>}
    {selectedId && !selectedDetail && detailLoadingId === selectedId && <p role="status" className="rounded-lg border border-line bg-surface px-4 py-3 text-[12.5px]">분석 상세를 불러오는 중입니다.</p>}
    <section className="flex flex-col gap-3" aria-label="분석 이력">
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
        canCreate={canCreate}
        reviewState={reviewData?.analysisId === summary.analysisId ? reviewData : null}
        reviewLoading={reviewLoadingId === summary.analysisId}
        reviewError={reviewLoadError?.analysisId === summary.analysisId ? reviewLoadError.message : null}
        onRefreshReview={loadReviewState}
        onRefreshAfterReviewConflict={refreshReviewAfterConflict}
      />)}
      {rows.length === 0 && listLoading && <p role="status" className="rounded-lg border border-line bg-surface px-4 py-3 text-[13px] text-ink-2">분석 목록을 불러오는 중입니다.</p>}
      {rows.length === 0 && !listLoading && !listLoadError && <p className="rounded-lg border border-line bg-surface px-4 py-3 text-[13px] leading-5 text-ink-2">{nextListCursor
        ? "현재 페이지에 분석 요청이 없습니다. 다음 페이지를 불러와 나머지 이력을 확인하세요."
        : canCreate
          ? "이 현장에는 아직 분석 요청이 없습니다. 새 분석 요청에서 실제 작업구역과 관측 후보를 확인한 뒤 진행하세요."
          : "이 현장에는 아직 분석 요청이 없습니다. 권한 있는 현장 담당자가 요청을 제출하면 상태와 근거가 여기에 표시됩니다."}</p>}
    </section>
    {lastEvidencePage?.nextCursor && <div className="flex justify-center"><button type="button" className="btn" disabled={evidenceLoading} onClick={loadNextEvidence}>{evidenceLoading ? "근거 불러오는 중" : "다음 근거 보기"}</button></div>}
    {nextListCursor && <div className="flex justify-center"><button type="button" className="btn" disabled={listLoading} onClick={() => void loadMoreAnalyses()}>{listLoading ? "분석 목록 불러오는 중" : "다음 분석 보기"}</button></div>}
  </div>;
}
