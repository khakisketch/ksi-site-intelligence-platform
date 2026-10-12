"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { StateBadge } from "@/components/ui/StatusBadge";
import type {
  AnalysisEvidenceItem,
  AnalysisEvidencePage,
  AnalysisListItem,
  AnalysisListPage,
  AnalysisObservationOption,
  AnalysisResult,
  AnalysisSelector,
  AnalysisView,
} from "@/lib/core-api/analysis";
import { formatKoreanDateTime } from "@/lib/datetime";

type Attempt = {
  key: string;
  workAreaId: string;
  body: { baseline: AnalysisSelector; current: AnalysisSelector };
};

type AttemptScope = { organizationId: string; principalId: string; siteId: string };
type AnalysisListRow = Omit<AnalysisListItem, "analysisHref">;
type AnalysisPageState = Omit<AnalysisListPage, "items"> & { items: AnalysisListRow[] };
type LoadedEvidence = { analysisId: string; pages: AnalysisEvidencePage[] };

const pendingAttemptPrefix = "ksi.analysis.pending.v1";
const maxStoredAttemptLength = 4_096;
const submissionRefPattern = /^ers-v1-[0-9a-f]{64}$/;

function pendingAttemptKey(scope: AttemptScope) {
  return `${pendingAttemptPrefix}:${encodeURIComponent(scope.organizationId)}:${encodeURIComponent(scope.principalId)}:${encodeURIComponent(scope.siteId)}`;
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

function parseStoredAttempt(value: unknown, scope: AttemptScope): Attempt | null {
  if (!isRecord(value) || !hasExactKeys(value, ["version", "organizationId", "principalId", "siteId", "attempt"]) || value.version !== 1 || value.organizationId !== scope.organizationId || value.principalId !== scope.principalId || value.siteId !== scope.siteId || !isRecord(value.attempt) || !hasExactKeys(value.attempt, ["key", "workAreaId", "body"])) return null;
  const { key, workAreaId, body } = value.attempt;
  if (!isBoundedString(key, 255) || key.trim().length === 0 || !isBoundedString(workAreaId, 255) || !isRecord(body) || !hasExactKeys(body, ["baseline", "current"])) return null;
  const baseline = parseSelector(body.baseline);
  const current = parseSelector(body.current);
  if (!baseline || !current || sameSelector(baseline, current)) return null;
  return { key, workAreaId, body: { baseline, current } };
}

function readPendingAttempt(scope: AttemptScope): Attempt | null {
  const key = pendingAttemptKey(scope);
  try {
    const raw = window.sessionStorage.getItem(key);
    if (!raw) return null;
    if (raw.length > maxStoredAttemptLength) {
      window.sessionStorage.removeItem(key);
      return null;
    }
    try {
      const parsed: unknown = JSON.parse(raw);
      const attempt = parseStoredAttempt(parsed, scope);
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

function writePendingAttempt(scope: AttemptScope, attempt: Attempt): boolean {
  const encoded = JSON.stringify({ version: 1, ...scope, attempt });
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
    const key = pendingAttemptKey(scope);
    window.sessionStorage.removeItem(key);
    return window.sessionStorage.getItem(key) === null;
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
  if (code === "REASSESSMENT_REQUIRED") return "현장 적합성 재평가 필요";
  return code;
}

function formatNumber(value: number, suffix: string) {
  const options = Math.abs(value) > 0 && Math.abs(value) < 0.1
    ? { maximumSignificantDigits: 3 }
    : { maximumFractionDigits: 1 };
  return `${value.toLocaleString("ko-KR", options)} ${suffix}`;
}

function selectionLabel(option: AnalysisObservationOption) {
  return `${option.observationEpochId} · ${formatKoreanDateTime(option.captureStartedAt, { dateStyle: "short", timeStyle: "short" })}–${formatKoreanDateTime(option.captureEndedAt, { timeStyle: "short" })}`;
}

function ResultIdentity({ result }: { result: AnalysisResult }) {
  return <dl className="mt-3 grid gap-1 text-[11.5px] text-ink-2 sm:grid-cols-2">
    <div><dt className="text-ink-muted">결과 ID</dt><dd className="break-all">{result.resultId}</dd></div>
    <div><dt className="text-ink-muted">계산 시각</dt><dd>{formatKoreanDateTime(result.computedAt, { dateStyle: "short", timeStyle: "short" })}</dd></div>
    <div><dt className="text-ink-muted">보고서 digest</dt><dd className="break-all">{result.reportDigest}</dd></div>
    <div><dt className="text-ink-muted">수치 결과 ID digest</dt><dd className="break-all">{result.numericResultIdentityDigest}</dd></div>
  </dl>;
}

function MetricSummary({ summary, detail }: { summary: AnalysisListRow; detail: AnalysisView | null }) {
  const result = detail?.result;
  const metrics = result?.metrics ?? summary.metrics;
  if (!metrics) return null;
  return <section className="border-t border-line px-4 py-3" aria-label="계산 결과">
    <h3 className="text-[13px] font-bold">계산 결과{summary.resultId ? ` · ${summary.resultId}` : ""}</h3>
    <div className="mt-2 overflow-x-auto"><table className="w-full min-w-[24rem] text-left text-[12.5px]"><thead className="text-ink-muted"><tr><th className="pb-2 pr-3 font-semibold">절토</th><th className="pb-2 pr-3 font-semibold">성토</th><th className="pb-2 font-semibold">순변화</th></tr></thead><tbody><tr className="border-t border-line"><td className="num py-2 pr-3 text-[16px] font-bold">{formatNumber(metrics.cutM3, "m³")}</td><td className="num py-2 pr-3 text-[16px] font-bold">{formatNumber(metrics.fillM3, "m³")}</td><td className="num py-2 text-[16px] font-bold">{formatNumber(metrics.netM3, "m³")}</td></tr></tbody></table></div>
    {result && <>
      <dl className="mt-3 grid gap-2 text-[12px] text-ink-2 sm:grid-cols-2">
        <div><dt className="text-ink-muted">선택 면적</dt><dd>{formatNumber(result.coverage.selectedAreaM2, "m²")}</dd></div>
        <div><dt className="text-ink-muted">공통 유효 면적</dt><dd>{formatNumber(result.coverage.commonValidAreaM2, "m²")}</dd></div>
        <div><dt className="text-ink-muted">선택 셀</dt><dd>{result.coverage.selectedCellCount.toLocaleString("ko-KR")}</dd></div>
        <div><dt className="text-ink-muted">공통 유효 셀</dt><dd>{result.coverage.commonValidCellCount.toLocaleString("ko-KR")}</dd></div>
      </dl>
      <p className="mt-2 text-[12px] leading-5 text-ink-muted">임계값 {formatNumber(metrics.thresholdM, "m")}: 높이 차이 기준으로 제외되는 셀이 없습니다. 공통 유효 영역은 두 관측에서 유효한 셀로 별도 제한됩니다.</p>
      <ResultIdentity result={result} />
      <p className="mt-2 text-[12px] leading-5 text-ink-muted">{detail.suitabilityState === "EVALUATED" ? "독립 평가 근거가 있습니다. 이 기록은 물량 정확도 보증, 측량 승인 또는 정산 사용 승인을 뜻하지 않습니다." : "독립 정확도 평가는 아직 확인되지 않았습니다. 이 기록은 물량 정확도 보증, 측량 승인 또는 정산 사용 승인을 뜻하지 않습니다."}</p>
      {result.limitationCodes.length > 0 && <p className="mt-1 break-words text-[12px] leading-5 text-ink-2">제한: {result.limitationCodes.map(analysisCodeLabel).join(", ")}</p>}
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
        `DSM: ${item.observedSha256} · ${item.observedSizeBytes.toLocaleString("ko-KR")} bytes`,
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
        `사유: ${item.reasonCodes.map(analysisCodeLabel).join(", ")}`,
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
      return [`제한 (${item.source}): ${analysisCodeLabel(item.code)}`, ...(item.detail ? [item.detail] : []), ...(item.evidenceRef ? [`근거 참조: ${item.evidenceRef}`] : [])];
  }
}

function EvidenceSummary({ pages }: { pages: AnalysisEvidencePage[] }) {
  const items = pages.flatMap((page) => page.items);
  const first = pages[0];
  return <section className="border-t border-line px-4 py-3" aria-label="근거">
    <h3 className="text-[13px] font-bold">근거 · {items.length}개 항목</h3>
    {first && <p className="mt-1 break-all text-[11.5px] text-ink-muted">개정 {first.evidenceRevision} · evidence digest {first.evidenceDigest}</p>}
    <ul className="mt-3 space-y-2">{items.map((item) => <li key={`${item.recordId}:${item.digest}`} className="rounded-md border border-line p-2 text-[12px] text-ink-2">
      <p className="break-all font-semibold">{item.kind} · {item.recordId}</p>
      <p className="mt-1 break-all text-ink-muted">digest: {item.digest}</p>
      <ul className="mt-1 space-y-1 break-all">{evidenceLines(item).map((line) => <li key={line}>{line}</li>)}</ul>
      {item.limitationCodes.length > 0 && <p className="mt-1 break-all text-crit-ink">제한: {item.limitationCodes.map(analysisCodeLabel).join(", ")}</p>}
    </li>)}</ul>
  </section>;
}

function AnalysisCard({ summary, detail, selected, onSelect, evidencePages }: {
  summary: AnalysisListRow;
  detail: AnalysisView | null;
  selected: boolean;
  onSelect: () => void;
  evidencePages: AnalysisEvidencePage[];
}) {
  const execution = executionLabel(summary.executionState);
  const suitability = suitabilityLabel(summary.suitabilityState);
  return <article className={`rounded-lg border bg-surface ${selected ? "border-accent" : "border-line"}`}>
    <div className="flex flex-wrap items-start justify-between gap-3 px-4 py-3">
      <div><p className="text-[14px] font-bold">분석 {summary.analysisId}</p><p className="mt-1 text-[12px] text-ink-muted">작업구역 {summary.workAreaId} · 생성 {formatKoreanDateTime(summary.createdAt, { dateStyle: "short", timeStyle: "short" })}</p></div>
      <button type="button" className="btn" onClick={onSelect} aria-current={selected ? "page" : undefined}>이 분석 보기</button>
    </div>
    <div className="grid gap-2 border-t border-line px-4 py-3 sm:grid-cols-2"><div><p className="mb-1 text-[12px] text-ink-muted">실행 상태</p><StateBadge label={execution.label} tone={execution.tone} /></div><div><p className="mb-1 text-[12px] text-ink-muted">적합성 상태</p><StateBadge label={suitability.label} tone={suitability.tone} /></div>{summary.executionState === "COMPLETED" && summary.suitabilityState === "REASSESSMENT_REQUIRED" && <p className="rounded-md bg-high-bg px-3 py-2 text-[12.5px] leading-5 text-high-ink sm:col-span-2">계산은 완료됐습니다. 현장 적합성은 재평가가 필요합니다.</p>}</div>
    {detail?.blockers.length ? <section className="border-t border-line px-4 py-3" aria-label="차단 사유"><h3 className="text-[13px] font-bold">확인 필요</h3><ul className="mt-2 space-y-2">{detail.blockers.map((blocker, index) => <li key={`${blocker.code}-${index}`} className="text-[12.5px] leading-5 text-ink-2"><strong className="font-semibold">{analysisCodeLabel(blocker.code)}</strong>{blocker.epoch ? ` · ${blocker.epoch === "BASELINE" ? "기준 관측" : "현재 관측"}` : ""}{blocker.detail ? <span className="block">{blocker.detail}</span> : null}{blocker.evidenceRef ? <span className="block break-all text-ink-muted">근거 참조: {blocker.evidenceRef}</span> : null}</li>)}</ul></section> : null}
    {detail ? <MetricSummary summary={summary} detail={detail} /> : !selected && summary.metrics ? <MetricSummary summary={summary} detail={null} /> : null}
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
  initialPage,
  initialSelectedDetail,
  canCreate,
  initialAnalysisId,
  organizationId,
  principalId,
}: {
  siteId: string;
  workAreas: readonly { workAreaId: string; name: string }[];
  observations: readonly AnalysisObservationOption[];
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
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ analysisId: string | null; message: string } | null>(null);
  const [detailLoadingId, setDetailLoadingId] = useState<string | null>(null);
  const [listLoading, setListLoading] = useState(false);
  const [listRestartRequired, setListRestartRequired] = useState(false);
  const [evidence, setEvidence] = useState<LoadedEvidence | null>(null);
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [evidenceRestartRequired, setEvidenceRestartRequired] = useState(false);
  const selectedIdRef = useRef<string | null>(selectedId);
  const mountedRef = useRef(true);
  const createController = useRef<AbortController | null>(null);
  const detailController = useRef<AbortController | null>(null);
  const evidenceController = useRef<AbortController | null>(null);
  const listController = useRef<AbortController | null>(null);
  const createGeneration = useRef(0);
  const detailGeneration = useRef(0);
  const evidenceGeneration = useRef(0);
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
  const hasTerminalItems = rows.some((item) => item.executionState === "COMPLETED" || item.executionState === "FAILED");
  const evidencePages = evidence?.analysisId === selectedId ? evidence.pages : [];
  const lastEvidencePage = evidencePages.at(-1);
  const nextListCursor = pages.at(-1)?.nextCursor ?? null;

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
    }
  }, [setDetailsAndRef]);

  const upsertDetail = useCallback((detail: AnalysisView) => {
    const previous = detailsRef.current.get(detail.analysisId);
    setDetailsAndRef((current) => new Map(current).set(detail.analysisId, detail));
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
      setWorkAreaId(restored.workAreaId);
      const baseline = observations.findIndex((option) => sameSelector(option.selector, restored.body.baseline));
      const current = observations.findIndex((option) => sameSelector(option.selector, restored.body.current));
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
    selectedIdRef.current = analysisId;
    setSelectedId(analysisId);
    setEvidence(null);
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
      pollGeneration.current += 1;
      createController.current?.abort();
      detailController.current?.abort();
      evidenceController.current?.abort();
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
    setListLoading(true);
    try {
      const loaded = await fetchListPage(null, controller.signal);
      if (loaded.stale) {
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
      setListRestartRequired(false);
      setError((current) => current?.message.includes("분석 목록") ? null : current);
      if (selectedId) await refreshDetail(selectedId, ++detailGeneration.current);
    } catch (loadError) {
      if (!(loadError instanceof DOMException && loadError.name === "AbortError") && mountedRef.current && listGeneration.current === generation) {
        setError({ analysisId: selectedIdRef.current, message: loadError instanceof Error ? loadError.message : "현장 분석 목록을 불러오지 못했습니다." });
      }
    } finally {
      if (mountedRef.current && listGeneration.current === generation) setListLoading(false);
    }
  }, [fetchListPage, refreshDetail, retireDetail, setPagesAndRef, setPinnedAndRef]);

  const loadMoreAnalyses = async () => {
    const cursor = pagesRef.current.at(-1)?.nextCursor ?? null;
    if (!cursor || listLoading) return;
    listController.current?.abort();
    const controller = new AbortController();
    listController.current = controller;
    const generation = ++listGeneration.current;
    setListLoading(true);
    try {
      const loaded = await fetchListPage(cursor, controller.signal);
      if (loaded.stale) {
        setListRestartRequired(true);
        setError({ analysisId: selectedIdRef.current, message: "목록 페이지가 바뀌었습니다. 첫 페이지부터 다시 불러오세요." });
        return;
      }
      if (!mountedRef.current || listGeneration.current !== generation) return;
      setPagesAndRef((current) => [...current, loaded.page]);
    } catch (loadError) {
      if (!(loadError instanceof DOMException && loadError.name === "AbortError") && mountedRef.current && listGeneration.current === generation) {
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
    if (!hasTerminalItems) return;
    const refreshWhenVisible = () => { if (document.visibilityState === "visible") void refreshAnalyses(); };
    const timer = setInterval(refreshWhenVisible, 15_000);
    const refreshOnFocus = () => void refreshAnalyses();
    window.addEventListener("focus", refreshOnFocus);
    document.addEventListener("visibilitychange", refreshWhenVisible);
    return () => {
      clearInterval(timer);
      window.removeEventListener("focus", refreshOnFocus);
      document.removeEventListener("visibilitychange", refreshWhenVisible);
    };
  }, [hasTerminalItems, refreshAnalyses]);

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
    const nextAttempt = attempt ?? (() => {
      if (!workAreaId || baselineIndex === "" || currentIndex === "") {
        setError({ analysisId: null, message: "작업구역과 서로 다른 기준·현재 관측을 선택하세요." });
        return null;
      }
      const baseline = observations[Number(baselineIndex)];
      const current = observations[Number(currentIndex)];
      if (!baseline || !current || sameSelector(baseline.selector, current.selector)) {
        setError({ analysisId: null, message: "작업구역과 서로 다른 기준·현재 관측을 선택하세요." });
        return null;
      }
      const created = { key: createIdempotencyKey(), workAreaId, body: { baseline: baseline.selector, current: current.selector } };
      if (!attemptScope || !writePendingAttempt(attemptScope, created)) {
        setError({ analysisId: null, message: "이 브라우저에서는 요청 재시도 정보를 저장할 수 없습니다. 다시 시도하세요." });
        return null;
      }
      setAttempt(created);
      return created;
    })();
    if (!nextAttempt) return;
    setBusy(true);
    setError(null);
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

  const selectedEvidencePages = evidence?.analysisId === selectedId ? evidence.pages : [];
  const showError = error && (error.analysisId === null || error.analysisId === selectedId);

  return <div className="flex flex-col gap-4">
    {canCreate && <section className="rounded-lg border border-line bg-surface px-4 py-4"><h2 className="text-[16px] font-bold">새 분석 요청</h2><p className="mt-1 text-[12.5px] leading-5 text-ink-2">기준 관측과 현재 관측을 고르면 Core가 적합성·계산 실행을 기록합니다. 화면은 그 판단을 바꾸지 않습니다.</p>{attempt && <p className="mt-2 text-[12px] text-ink-2">중단된 요청이 있습니다. 다시 시도하면 같은 요청 식별자로 Core에 확인합니다.</p>}<form className="mt-4 grid gap-3 sm:grid-cols-3" noValidate onSubmit={(event) => { event.preventDefault(); void submit(); }}><label className="text-[12.5px] font-semibold">작업구역<select className="input mt-1 w-full" value={workAreaId} disabled={busy} onChange={(event) => { if (discardAttempt()) setWorkAreaId(event.target.value); }}><option value="">작업구역 선택</option>{workAreas.map((area) => <option key={area.workAreaId} value={area.workAreaId}>{area.name}</option>)}</select></label><label className="text-[12.5px] font-semibold">기준 관측<select className="input mt-1 w-full" value={baselineIndex} disabled={busy} onChange={(event) => { if (discardAttempt()) setBaselineIndex(event.target.value); }}><option value="">기준 관측 선택</option>{observations.map((item, index) => <option key={`${item.observationEpochId}-${index}`} value={index}>{selectionLabel(item)}</option>)}</select></label><label className="text-[12.5px] font-semibold">현재 관측<select className="input mt-1 w-full" value={currentIndex} disabled={busy} onChange={(event) => { if (discardAttempt()) setCurrentIndex(event.target.value); }}><option value="">현재 관측 선택</option>{observations.map((item, index) => <option key={`${item.observationEpochId}-${index}`} value={index}>{selectionLabel(item)}</option>)}</select></label><div className="flex flex-wrap gap-2 sm:col-span-3"><button type="submit" className="btn btn-primary" disabled={busy}>{busy ? "요청 중" : attempt ? "다시 시도" : "분석 요청"}</button>{attempt && <button type="button" className="btn" disabled={busy} onClick={discardAttempt}>보류 요청 취소</button>}</div></form></section>}
    {!canCreate && <p className="rounded-lg border border-line bg-surface px-4 py-3 text-[12.5px] text-ink-2">분석 기록을 볼 수 있습니다. 새 요청에는 현장 등록 권한(SITES_WRITE)이 필요합니다.</p>}
    {showError && <div role="alert" className="rounded-lg border border-crit bg-crit-bg px-4 py-3 text-[12.5px] text-crit-ink"><span>{error.message}</span>{error.analysisId === selectedId && selectedId && <button type="button" className="btn ml-2" disabled={detailLoadingId === selectedId} onClick={() => void refreshDetail(selectedId, ++detailGeneration.current)}>{detailLoadingId === selectedId ? "상세 불러오는 중" : "분석 상세 다시 불러오기"}</button>}{listRestartRequired && <button type="button" className="btn ml-2" disabled={listLoading} onClick={() => void restartAnalyses()}>{listLoading ? "목록 불러오는 중" : "목록 처음부터 다시 불러오기"}</button>}{evidenceRestartRequired && <button type="button" className="btn ml-2" disabled={evidenceLoading} onClick={restartEvidence}>{evidenceLoading ? "근거 불러오는 중" : "근거 처음부터 다시 불러오기"}</button>}</div>}
    {selectedId && selectedDetail && <div className="flex justify-end"><button type="button" className="btn" onClick={loadEvidence} disabled={selectedEvidencePages.length > 0 || evidenceLoading}>{evidenceLoading ? "근거 불러오는 중" : "근거 확인"}</button></div>}
    {selectedId && !selectedDetail && detailLoadingId === selectedId && <p role="status" className="rounded-lg border border-line bg-surface px-4 py-3 text-[12.5px]">분석 상세를 불러오는 중입니다.</p>}
    <section className="flex flex-col gap-3" aria-label="분석 이력">{rows.map((summary) => <AnalysisCard key={summary.analysisId} summary={summary} detail={details.get(summary.analysisId) ?? null} selected={summary.analysisId === selectedId} onSelect={() => choose(summary.analysisId)} evidencePages={summary.analysisId === selectedId ? selectedEvidencePages : []} />)}{rows.length === 0 && <p className="rounded-lg border border-line bg-surface px-4 py-3 text-[13px] text-ink-2">이 현장에는 아직 분석 요청이 없습니다.</p>}</section>
    {lastEvidencePage?.nextCursor && <div className="flex justify-center"><button type="button" className="btn" disabled={evidenceLoading} onClick={loadNextEvidence}>{evidenceLoading ? "근거 불러오는 중" : "다음 근거 보기"}</button></div>}
    {nextListCursor && <div className="flex justify-center"><button type="button" className="btn" disabled={listLoading} onClick={() => void loadMoreAnalyses()}>{listLoading ? "분석 목록 불러오는 중" : "다음 분석 보기"}</button></div>}
  </div>;
}
