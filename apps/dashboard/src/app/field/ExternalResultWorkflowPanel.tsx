"use client";

import { ExternalResultReviewActions } from "@/components/external-results/ExternalResultReviewActions";
import { ExternalUseBlockerCard } from "@/components/external-results/ExternalUseBlockerCard";
import { SingleVolumeResult } from "@/components/external-results/SingleVolumeResult";
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { ResponsiveActionBoundary } from "@/components/responsive/ResponsiveActionBoundary";
import { formatKoreanDateTime } from "@/lib/datetime";
import { formatNumberKo } from "@/lib/number-format";
import type {
  ExternalReobservationProposalView,
  ExternalRelativeVolumeReportView,
  ExternalRelativeVolumeRequestView,
  ExternalResultReview,
  ExternalSingleVolumeReportView,
  ExternalSingleVolumeResultReview,
} from "@/lib/core-api/external-result-workflow";
import {
  isExternalRelativeVolumeReportReference,
  isExternalRelativeVolumeRequestReference,
} from "@/lib/external-relative-volume-references";
import {
  isExternalSingleVolumeReportReference,
  isExternalSingleVolumeRequestReference,
} from "@/lib/external-single-volume-references";

export type ExternalRelativeVolumeDecision = {
  decisionId: string;
  decisionDigest: string;
  verdict: "ELIGIBLE" | "RESTRICTED" | "BLOCKED";
  reasons: string[];
  remediations: string[];
};

type Phase = "idle" | "loading" | "ready" | "error";
type BusyOperation = "issue";
type FrozenIssue = { decisionId: string; decisionDigest: string; idempotencyKey: string };

const AUTO_REQUEST_REFRESH_DELAY_MS = 5_000;
const AUTO_REQUEST_REFRESH_BUDGET = 6;
const KNOWN_REQUEST_STATUSES = ["QUEUED", "RUNNING", "SUCCEEDED", "FAILED"] as const;
const UNKNOWN_REQUEST_STATUS = "UNKNOWN_EXTERNAL_RELATIVE_VOLUME_REQUEST_STATUS";

class WorkflowResponseError extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
    this.name = "WorkflowResponseError";
  }
}

/** A server-validated Site summary binds an exact deep link to one retained report. */
export type TrustedExternalResultLink = {
  reportRef: string;
  reportDigest: string;
  view: ExternalRelativeVolumeReportView;
  /** An optional, server-resolved Site WorkArea label; the report still binds by id. */
  workAreaName?: string | null;
};

function makeKey(): string {
  return `console-${crypto.randomUUID()}`;
}

async function responseJson<T>(response: Response): Promise<T> {
  if (response.ok) return response.json() as Promise<T>;
  const body = await response.json().catch(() => null) as { code?: unknown; message?: unknown } | null;
  const code = typeof body?.code === "string" ? body.code : undefined;
  const message = typeof body?.message === "string" ? body.message : undefined;
  throw new WorkflowResponseError(response.status, code ?? message ?? `HTTP_${response.status}`);
}

function requestListReadError(error: unknown, family: "비교" | "체적 측정"): string {
  if (error instanceof WorkflowResponseError && error.status === 403) {
    return `${family} 요청 목록 조회 권한이 없습니다. 관리자에게 이 작업의 결과 조회 권한을 요청한 뒤 화면을 다시 열어 확인하세요.`;
  }
  if (error instanceof WorkflowResponseError && error.status === 401) {
    return `${family} 요청 목록을 확인하려면 다시 로그인한 뒤 화면을 다시 여세요.`;
  }
  if (error instanceof Error && error.message === UNKNOWN_REQUEST_STATUS) {
    return "요청 상태 형식을 확인하지 못했습니다. 목록을 다시 확인하세요.";
  }
  return `${family} 요청 목록을 읽지 못했습니다. 새로고침으로 다시 시도하세요.`;
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function subjectLabel(subject: { workOrderId: string; submissionId: string; revision: number }): string {
  return `${subject.workOrderId} · ${subject.submissionId} · rev ${subject.revision}`;
}

function isKnownRequestStatus(status: unknown): status is ExternalRelativeVolumeRequestView["status"] {
  return typeof status === "string" && (KNOWN_REQUEST_STATUSES as readonly string[]).includes(status);
}

function isKnownRequestView(value: unknown): value is ExternalRelativeVolumeRequestView {
  return value !== null && typeof value === "object" && isKnownRequestStatus((value as { status?: unknown }).status);
}

function statusLabel(status: unknown): string {
  return {
    QUEUED: "대기",
    RUNNING: "처리 중",
    SUCCEEDED: "보고 완료",
    FAILED: "실패",
  }[status as ExternalRelativeVolumeRequestView["status"]] ?? "상태 확인 필요";
}

function formatNumber(value: number, maximumFractionDigits = 2): string {
  return formatNumberKo(value, maximumFractionDigits);
}

function formatSignedNumber(value: number, maximumFractionDigits = 2): string {
  const rendered = formatNumber(value, maximumFractionDigits);
  return value > 0 ? `+${rendered}` : rendered;
}

function observationRange(from: string, to: string): string {
  const start = formatKoreanDateTime(from, { dateStyle: "medium", timeStyle: "short" });
  const end = formatKoreanDateTime(to, { dateStyle: "medium", timeStyle: "short" });
  return start === end ? start : `${start} ~ ${end}`;
}

function recordedDeadlineElapsed(deadlineAt: string): boolean {
  const timestamp = Date.parse(deadlineAt);
  return Number.isFinite(timestamp) && timestamp <= Date.now();
}

/** 요청 목록/선택 줄의 발급·마감 시각 — 원문 ISO 를 화면에 내보내지 않는다. */
function requestMoment(iso: string): string {
  return formatKoreanDateTime(iso, { dateStyle: "short", timeStyle: "short" });
}

function isUnfinishedRequest(status: unknown): boolean {
  return status === "QUEUED" || status === "RUNNING";
}

function issueFailureMessage(error: unknown): string {
  const code = error instanceof Error ? error.message : "";
  if (code === "AUTHORITY_UNAVAILABLE") {
    return "비교에 필요한 기준이나 증거를 지금 사용할 수 없습니다. 현재 선택을 다시 확인한 뒤 재시도하세요.";
  }
  if (code === "DEADLINE_EXPIRED") {
    return "이 요청의 마감 시간이 지났습니다. 현재 선택을 다시 확인해 새 요청을 만드세요.";
  }
  if (code === "RETRY_EXHAUSTED") {
    return "이 요청의 재시도 한도에 도달했습니다. 요청 상태를 새로고침하고 원인을 확인하세요.";
  }
  if (code === "QUEUE_FULL" || code === "STORE_UNAVAILABLE") {
    return "요청 처리를 지금 시작할 수 없습니다. 같은 선택으로 다시 시도합니다.";
  }
  if (code === UNKNOWN_REQUEST_STATUS) {
    return "요청 상태 형식을 확인하지 못했습니다. 같은 선택으로 다시 시도합니다.";
  }
  return "외부 상대 물량 요청 상태를 확인하지 못했습니다. 같은 선택으로 다시 시도합니다.";
}

const SHARED_ISSUE_FAILURE_CODES = new Set([
  "DEADLINE_EXPIRED",
  "RETRY_EXHAUSTED",
  "QUEUE_FULL",
  "STORE_UNAVAILABLE",
  UNKNOWN_REQUEST_STATUS,
]);

/** Single-volume counterpart of `issueFailureMessage`, without comparison wording. */
function singleIssueFailureMessage(error: unknown): string {
  const code = error instanceof Error ? error.message : "";
  if (code === "AUTHORITY_UNAVAILABLE") {
    return "측정에 필요한 대상이나 증거를 지금 사용할 수 없습니다. 현재 선택을 다시 확인한 뒤 재시도하세요.";
  }
  // These relative messages contain no comparison wording, so both families share them.
  if (SHARED_ISSUE_FAILURE_CODES.has(code)) return issueFailureMessage(error);
  return "단일 시점 체적 요청 상태를 확인하지 못했습니다. 같은 선택으로 다시 시도합니다.";
}

const AUTO_REFRESH_STOPPED_NOTICE = "자동 상태 확인을 멈췄습니다. 마지막으로 확인한 요청 상태를 표시합니다. 수동 새로고침으로 다시 확인하세요.";

function CoreBindings({ view }: { view: ExternalRelativeVolumeReportView }) {
  const { request, report, executionPolicy } = view;
  return (
    <details className="mt-2 rounded border border-line px-3 py-2 text-[12px] text-ink-2">
      <summary className="cursor-pointer font-semibold">전문가용 기록 및 검증 정보</summary>
      <div className="mt-2 flex flex-col gap-1 break-all">
        <p>기준 대상: {subjectLabel(request.baseline.subject)}</p>
        <p>현재 대상: {subjectLabel(request.current.subject)}</p>
        <p>구역 ID {request.zoneSnapshot.workAreaId} · rev {request.zoneSnapshot.revision} · 정의 {request.zoneSnapshot.definitionDigest ?? "기록 없음"}</p>
        <p>정책: 검증 {request.validationPolicyDigest} · 실행 {executionPolicy.policyDigest ?? request.executionPolicyDigest}</p>
        <p>증거 기록: {request.evidenceRecordDigests.join(", ")}</p>
        <p>보고서: {report.reportDigest ?? "기록 없음"} · 요청 {request.requestDigest ?? "기록 없음"}</p>
        <p>독립 검사점 증거 기록: {request.evidenceRecordDigests.join(", ")}</p>
      </div>
    </details>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="border-l border-line px-3 first:border-l-0 first:pl-0">
      <dt className="text-[12px] font-semibold text-ink-muted">{label}</dt>
      <dd className="num mt-1 text-[20px] font-bold tracking-tight text-ink-1">{value}</dd>
    </div>
  );
}

function ReportDetail({
  view,
  workAreaName,
}: {
  view: ExternalRelativeVolumeReportView;
  workAreaName: string | null;
}) {
  const metrics = view.report.payload.metrics;
  const coveragePassed = metrics.commonValidFraction >= view.executionPolicy.minimumCommonValidFraction;

  return (
    <section id="external-result" tabIndex={-1} className="mt-3 scroll-mt-5 rounded-lg border border-line bg-surface text-[13px]">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="px-4 py-3">
          <h3 className="text-[16px] font-bold tracking-tight">외부 상대 물량 비교 결과</h3>
          <p className="mt-1 leading-5 text-ink-2">작업구역 {workAreaName ?? "이름을 확인할 수 없는 구역"}</p>
          <p className="mt-1 break-all font-mono text-[10.5px] text-ink-muted">기술 참조 · 구역 {view.request.zoneSnapshot.workAreaId} · rev {view.request.zoneSnapshot.revision}</p>
        </div>
        <span className="px-4 text-[12px] text-ink-muted">보고 {formatKoreanDateTime(view.report.reportedAt, { dateStyle: "medium", timeStyle: "short" })}</span>
      </div>
      <div className="border-t border-line bg-sunk px-4 py-3 leading-5 text-ink-2">
        <p>기준 촬영 {observationRange(view.request.baseline.capturedFrom, view.request.baseline.capturedTo)}</p>
        <p>현재 촬영 {observationRange(view.request.current.capturedFrom, view.request.current.capturedTo)}</p>
        <p className="mt-1 text-[12px] text-ink-muted">측정 영역 {formatNumber(metrics.measuredAreaM2, 1)} m² / 작업구역 {formatNumber(metrics.zoneAreaM2, 1)} m² · 공통 유효 영역 {formatNumber(metrics.commonValidFraction * 100, 1)}%</p>
      </div>
      {coveragePassed ? (
        <>
          <dl className="grid grid-cols-3 divide-x divide-line px-4 py-4">
            <Metric label="절토" value={`${formatNumber(metrics.cutM3)} m³`} />
            <Metric label="성토" value={`${formatNumber(metrics.fillM3)} m³`} />
            <Metric label="순변화" value={`${formatSignedNumber(metrics.netM3)} m³`} />
          </dl>
          <div className="border-t border-line bg-sunk px-4 py-3 leading-5 text-ink-2">
            <p className="text-[12px] text-ink-muted">절토는 깎아낸 양, 성토는 채워 넣은 양입니다.</p>
            <p className="mt-1">
            {metrics.uncertaintyM3 === null
              ? `불확실성은 아직 산정되지 않았습니다. ${metrics.uncertaintyNote}`
              : `불확실성 ±${formatNumber(metrics.uncertaintyM3)} m³ · ${metrics.uncertaintyNote}`}
            </p>
          </div>
        </>
      ) : (
        <p role="alert" className="border-t border-line px-4 py-3 text-high-ink">적용 범위가 측정 기준을 충족하지 않아 수량 카드를 표시하지 않습니다.</p>
      )}
      <div className="px-4 pb-4"><CoreBindings view={view} /></div>
    </section>
  );
}

function reviewRmseLabel(value: number | null): string {
  return value === null ? "기록 없음" : `${value}m`;
}

function ReviewAuditDetail({ review }: { review: ExternalResultReview }) {
  const { authority, decision, report, request } = review;
  return (
    <details className="mt-2 rounded border border-line px-3 py-2 text-[12px] text-ink-2">
      <summary className="cursor-pointer font-semibold">전문가용 검토 기록</summary>
      <div className="mt-2 flex flex-col gap-1 break-all">
        <p>검토 다이제스트: {review.reviewDigest ?? "기록 없음"}</p>
        <p>검토 원본: 조직 {review.organizationId} · 현장 {review.siteId} · 작업 {review.sourceWorkOrderId}</p>
        <p>검토 보고서: {review.reportRef} · 요청 {request.requestId}</p>
        <p>검토 보고 다이제스트: {report.reportDigest ?? "기록 없음"} · 요청 다이제스트 {request.requestDigest ?? "기록 없음"}</p>
        <p>검토 결정: {decision.decisionId} · {decision.decisionDigest ?? "기록 없음"}</p>
        <p>기준 독립 검사점 RMSE: {reviewRmseLabel(authority.baselineRmseM)}</p>
        <p>현재 독립 검사점 RMSE: {reviewRmseLabel(authority.currentRmseM)}</p>
        <p>기준 대상: {subjectLabel(authority.baseline.subject)} · 검사 {authority.baseline.inspectionReportDigest}</p>
        <p>현재 대상: {subjectLabel(authority.current.subject)} · 검사 {authority.current.inspectionReportDigest}</p>
        <p>구역 ID: {authority.zoneSnapshot.workAreaId} · rev {authority.zoneSnapshot.revision} · 정의 {authority.zoneSnapshot.definitionDigest ?? "기록 없음"}</p>
        <p>검증 정책: {authority.validationPolicyDigest} · 실행 정책: {authority.executionPolicy.policyDigest ?? "기록 없음"}</p>
        <p>호환 매핑: {authority.compatibilityMappingDigest} · 권한 기록: {authority.authorityDigest ?? "기록 없음"}</p>
        <p>증거 기록: {authority.evidenceRecordDigests.join(", ")}</p>
        {review.factualLimitations.map((limitation) => <p key={limitation}>검토 한계: {limitation}</p>)}
      </div>
    </details>
  );
}

/**
 * A single-volume review binds one capture window and one target RMSE. It has no
 * baseline epoch, so no baseline field is ever shown here.
 */
function SingleVolumeReviewAuditDetail({ review }: { review: ExternalSingleVolumeResultReview }) {
  const { authority, decision, report, request } = review;
  return (
    <details className="mt-2 rounded border border-line px-3 py-2 text-[12px] text-ink-2">
      <summary className="cursor-pointer font-semibold">전문가용 검토 기록</summary>
      <div className="mt-2 flex flex-col gap-1 break-all">
        <p>검토 다이제스트: {review.reviewDigest ?? "기록 없음"}</p>
        <p>검토 원본: 조직 {review.organizationId} · 현장 {review.siteId} · 작업 {review.sourceWorkOrderId}</p>
        <p>검토 보고서: {review.reportRef} · 요청 {request.requestId}</p>
        <p>검토 보고 다이제스트: {report.reportDigest ?? "기록 없음"} · 요청 다이제스트 {request.requestDigest ?? "기록 없음"}</p>
        <p>검토 결정: {decision.decisionId} · {decision.decisionDigest ?? "기록 없음"}</p>
        <p>대상 촬영 {observationRange(request.target.capturedFrom, request.target.capturedTo)}</p>
        <p>대상 독립 검사점 RMSE: {authority.targetRmseM === null ? "기록 없음" : `${authority.targetRmseM}m`}</p>
        <p>대상: {subjectLabel(authority.target.subject)} · 검사 {authority.target.inspectionReportDigest}</p>
        <p>구역 ID: {authority.zoneSnapshot.workAreaId} · rev {authority.zoneSnapshot.revision} · 정의 {authority.zoneSnapshot.definitionDigest ?? "기록 없음"}</p>
        <p>검증 정책: {authority.validationPolicyDigest} · 실행 정책: {authority.executionPolicy.policyDigest ?? "기록 없음"}</p>
        <p>호환 매핑: {authority.compatibilityMappingDigest} · 권한 기록: {authority.authorityDigest ?? "기록 없음"}</p>
        <p>증거 기록: {authority.evidenceRecordDigests.join(", ")}</p>
        {review.factualLimitations.map((limitation) => <p key={limitation}>검토 한계: {limitation}</p>)}
      </div>
    </details>
  );
}

function SingleVolumeReportDetail({ view }: { view: ExternalSingleVolumeReportView }) {
  const metrics = view.report.payload.metrics;
  const coveragePassed = metrics.commonValidFraction >= view.executionPolicy.minimumCommonValidFraction
    && metrics.boundaryValidFraction >= view.executionPolicy.minimumBoundaryValidFraction;
  return (
    <section className="mt-2 rounded-lg border border-line bg-surface text-[13px]">
      <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
        <div>
          <h4 className="text-[16px] font-bold tracking-tight">단일 시점 체적 결과</h4>
          <p className="mt-1 leading-5 text-ink-2">작업구역 {view.request.zoneSnapshot.workAreaId}</p>
        </div>
        <span className="text-[12px] text-ink-muted">보고 {formatKoreanDateTime(view.report.reportedAt, { dateStyle: "medium", timeStyle: "short" })}</span>
      </div>
      {coveragePassed ? (
        <div className="border-t border-line px-4 py-3">
          <SingleVolumeResult
            fillM3={metrics.fillM3}
            uncertaintyM3={metrics.uncertaintyM3}
            uncertaintyNote={metrics.uncertaintyNote}
            baseRoughnessM={metrics.baseRoughnessM}
            boundaryValidFraction={metrics.boundaryValidFraction}
            capturedFrom={view.request.target.capturedFrom}
            capturedTo={view.request.target.capturedTo}
          />
        </div>
      ) : (
        <p role="alert" className="border-t border-line px-4 py-3 text-high-ink">적용 범위가 측정 기준을 충족하지 않아 체적을 표시하지 않습니다.</p>
      )}
      <details className="mx-4 mb-3 rounded border border-line px-3 py-2 text-[12px] text-ink-2">
        <summary className="cursor-pointer font-semibold">전문가용 기록 및 검증 정보</summary>
        <div className="mt-2 flex flex-col gap-1 break-all">
          <p>대상: {subjectLabel(view.request.target.subject)}</p>
          <p>구역 ID {view.request.zoneSnapshot.workAreaId} · rev {view.request.zoneSnapshot.revision} · 정의 {view.request.zoneSnapshot.definitionDigest ?? "기록 없음"}</p>
          <p>정책: 검증 {view.request.validationPolicyDigest} · 실행 {view.executionPolicy.policyDigest ?? view.request.executionPolicyDigest}</p>
          <p>경계 셀 {metrics.boundaryCellCount}개 · 경계 표본 {metrics.boundarySampleCount}개</p>
          <p>보고서: {view.report.reportDigest ?? "기록 없음"} · 요청 {view.request.requestDigest ?? "기록 없음"}</p>
        </div>
      </details>
    </section>
  );
}

/**
 * SINGLE_VOLUME issue, request status, result, review, proposal, approval and the
 * shared successor navigation. Review, proposal and approval reuse the family's own
 * review path through `ExternalResultReviewActions`.
 */
function SingleVolumeWorkflow({
  workOrderId,
  decision,
  canIssuePermission,
  newIntentAllowed,
  hasReviewPermission,
  canApprovePermission,
  onApproved,
}: {
  workOrderId: string;
  decision: ExternalRelativeVolumeDecision | null;
  canIssuePermission: boolean;
  newIntentAllowed: boolean;
  hasReviewPermission: boolean;
  canApprovePermission: boolean;
  /**
   * Core approved the proposal and bound a successor. The parent finishes the approval
   * (work list refresh, navigation) and must stop as soon as `signal` is aborted, which
   * happens when this attempt is retired.
   */
  onApproved: (view: ExternalReobservationProposalView, signal: AbortSignal) => void | Promise<void>;
}) {
  const scope = useRef(0);
  const activeMutation = useRef<AbortController | null>(null);
  const listAbort = useRef<AbortController | null>(null);
  const singleReloadAbort = useRef<AbortController | null>(null);
  const [listPhase, setListPhase] = useState<Phase>("loading");
  const [listError, setListError] = useState<string | null>(null);
  const [listReadBlocked, setListReadBlocked] = useState(false);
  // Core mounts the single-volume router only when a single-volume execution template is
  // configured, so a 404 list read means this environment does not offer the family.
  const [notConfigured, setNotConfigured] = useState(false);
  const [list, setList] = useState<ExternalRelativeVolumeRequestView[]>([]);
  const [selectedRef, setSelectedRef] = useState<string | null>(null);
  const [selectionGeneration, setSelectionGeneration] = useState(0);
  const selectedRefRef = useRef<string | null>(null);
  const selectionGenerationRef = useRef(0);
  useEffect(() => {
    selectedRefRef.current = selectedRef;
  }, [selectedRef]);
  useEffect(() => {
    selectionGenerationRef.current = selectionGeneration;
  }, [selectionGeneration]);
  const [selected, setSelected] = useState<ExternalRelativeVolumeRequestView | null>(null);
  const [selectedError, setSelectedError] = useState<string | null>(null);
  const [pollStopped, setPollStopped] = useState(false);
  const [report, setReport] = useState<ExternalSingleVolumeReportView | null>(null);
  const [reportPhase, setReportPhase] = useState<Phase>("idle");
  const [busy, setBusy] = useState(false);
  const [issueAttempt, setIssueAttempt] = useState<FrozenIssue | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const requestsPath = `/api/observation-work-orders/${encodeURIComponent(workOrderId)}/single-volume-requests`;
  const canIssue = canIssuePermission && (newIntentAllowed || issueAttempt !== null);
  const decisionIdentity = decision ? `${decision.decisionId}|${decision.decisionDigest}` : "";

  const loadList = useCallback(async () => {
    listAbort.current?.abort();
    const controller = new AbortController();
    listAbort.current = controller;
    setListPhase("loading");
    setListError(null);
    setListReadBlocked(false);
    try {
      const listResponse = await fetch(requestsPath, { cache: "no-store", signal: controller.signal });
      if (listResponse.status === 404) {
        if (listAbort.current !== controller) return;
        setNotConfigured(true);
        setListPhase("idle");
        setListError(null);
        setListReadBlocked(false);
        return;
      }
      const value = await responseJson<{ items: unknown }>(listResponse);
      if (!Array.isArray(value.items) || !value.items.every(isKnownRequestView)) throw new Error(UNKNOWN_REQUEST_STATUS);
      if (listAbort.current !== controller) return;
      setNotConfigured(false);
      setList(value.items);
      setListPhase("ready");
      setListError(null);
      setListReadBlocked(false);
    } catch (error) {
      if (isAbort(error) || listAbort.current !== controller) return;
      setNotConfigured(false);
      setListPhase("error");
      setListError(requestListReadError(error, "체적 측정"));
      setListReadBlocked(error instanceof WorkflowResponseError && (error.status === 401 || error.status === 403));
    } finally {
      if (listAbort.current === controller) listAbort.current = null;
    }
  }, [requestsPath]);

  useEffect(() => {
    let active = true;
    void Promise.resolve().then(() => {
      if (active) void loadList();
    });
    return () => {
      active = false;
      listAbort.current?.abort();
    };
  }, [loadList]);

  // Reads the selected request and, while it is unfinished, re-reads it on a bounded
  // GET-only schedule that pauses while the tab is hidden and resumes when it is shown
  // again. A SUCCEEDED request loads its exact retained report.
  useEffect(() => {
    if (!selectedRef || !isExternalSingleVolumeRequestReference(selectedRef)) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | null = null;
    let budget = 0;
    let resumeWhenVisible = false;
    const scheduleRead = () => {
      if (budget >= AUTO_REQUEST_REFRESH_BUDGET) {
        setPollStopped(true);
        return;
      }
      budget += 1;
      timer = setTimeout(() => {
        timer = null;
        if (document.visibilityState === "hidden") {
          resumeWhenVisible = true;
          return;
        }
        void read();
      }, AUTO_REQUEST_REFRESH_DELAY_MS);
    };
    const resume = () => {
      if (document.visibilityState === "hidden" || !resumeWhenVisible || controller.signal.aborted) return;
      resumeWhenVisible = false;
      void read();
    };
    const loadReport = async (reportRef: string) => {
      if (!isExternalSingleVolumeReportReference(reportRef)) throw new Error("INVALID_REPORT_REFERENCE");
      setReportPhase("loading");
      const value = await responseJson<ExternalSingleVolumeReportView>(await fetch(
        `/api/external-single-volume-reports/${encodeURIComponent(reportRef)}`,
        { cache: "no-store", signal: controller.signal },
      ));
      if (controller.signal.aborted) return;
      if (value.report.reportId !== reportRef || value.request.requestId !== selectedRef) throw new Error("REPORT_BINDING_CHANGED");
      setReport(value);
      setReportPhase("ready");
    };
    const read = async () => {
      let requestRead = false;
      try {
        const value = await responseJson<unknown>(await fetch(
          `${requestsPath}/${encodeURIComponent(selectedRef)}`,
          { cache: "no-store", signal: controller.signal },
        ));
        if (!isKnownRequestView(value)) throw new Error(UNKNOWN_REQUEST_STATUS);
        if (controller.signal.aborted) return;
        requestRead = true;
        setSelected(value);
        setSelectedError(null);
        if (value.status === "SUCCEEDED" && value.reportRef) {
          await loadReport(value.reportRef);
          return;
        }
        setReport(null);
        setReportPhase("idle");
        if (isUnfinishedRequest(value.status)) scheduleRead();
      } catch (error) {
        if (isAbort(error) || controller.signal.aborted) return;
        if (requestRead) {
          setReport(null);
          setReportPhase("error");
        } else {
          setSelectedError("요청 상태를 확인하지 못했습니다. 마지막으로 확인한 요청과 목록을 유지합니다. 다시 시도하세요.");
        }
      }
    };
    document.addEventListener("visibilitychange", resume);
    void Promise.resolve().then(read);
    return () => {
      controller.abort();
      document.removeEventListener("visibilitychange", resume);
      if (timer !== null) clearTimeout(timer);
    };
  }, [requestsPath, selectedRef, selectionGeneration]);

  useEffect(() => {
    scope.current += 1;
    const decisionScope = scope.current;
    activeMutation.current?.abort();
    activeMutation.current = null;
    void Promise.resolve().then(() => {
      if (scope.current !== decisionScope) return;
      setBusy(false);
      setIssueAttempt(null);
      setMessage(null);
    });
  }, [decisionIdentity]);

  useEffect(() => () => {
    activeMutation.current?.abort();
    listAbort.current?.abort();
    singleReloadAbort.current?.abort();
    singleReloadAbort.current = null;
  }, []);

  const selectRequest = (requestRef: string) => {
    setSelectedError(null);
    setPollStopped(false);
    singleReloadAbort.current?.abort();
    singleReloadAbort.current = null;
    // Never leave another request's volume on screen while this selection is read.
    setReport(null);
    setReportPhase("idle");
    if (selectedRef === requestRef) setSelectionGeneration((current) => current + 1);
    setSelectedRef(requestRef);
  };

  const issue = async () => {
    if (!decision || decision.verdict !== "ELIGIBLE" || !canIssue || busy) return;
    let attempt = issueAttempt;
    const matchesDecision = attempt?.decisionId === decision.decisionId
      && attempt.decisionDigest === decision.decisionDigest;
    if (!newIntentAllowed && !matchesDecision) {
      setMessage("업무 종료 상태에서는 새 단일 시점 체적 측정을 요청할 수 없습니다.");
      return;
    }
    if (!matchesDecision) {
      attempt = { decisionId: decision.decisionId, decisionDigest: decision.decisionDigest, idempotencyKey: makeKey() };
      setIssueAttempt(attempt);
    }
    if (!attempt) return;
    activeMutation.current?.abort();
    const controller = new AbortController();
    activeMutation.current = controller;
    const requestScope = scope.current;
    const owns = () => activeMutation.current === controller && scope.current === requestScope;
    setBusy(true);
    setMessage(null);
    try {
      const value = await responseJson<{ verdict: string; request: unknown; detail: string | null }>(await fetch(requestsPath, {
        method: "POST",
        headers: { "content-type": "application/json", "idempotency-key": attempt.idempotencyKey },
        body: JSON.stringify({ decisionRef: attempt.decisionId }),
        signal: controller.signal,
      }));
      if (!owns()) return;
      if (!isKnownRequestView(value.request)) throw new Error(value.request === null ? (value.detail ?? value.verdict) : UNKNOWN_REQUEST_STATUS);
      selectRequest(value.request.requestRef);
      setMessage("단일 시점 체적 측정을 요청했습니다.");
      void loadList();
    } catch (error) {
      if (!isAbort(error) && owns()) setMessage(singleIssueFailureMessage(error));
    } finally {
      if (activeMutation.current === controller) {
        activeMutation.current = null;
        if (scope.current === requestScope) setBusy(false);
      }
    }
  };

  // Re-reads the exact retained single report after Core records a review or a
  // proposal, so the UI shows Core truth. The binding check matches the selection
  // read above: a report bound to another request is never shown. The reload is
  // bound to the selection generation at invocation: a stale response cannot
  // overwrite a newer selection or an unmounted state.
  const reloadSingleReport = useCallback(async (reportRef: string, requestRef: string) => {
    singleReloadAbort.current?.abort();
    const controller = new AbortController();
    singleReloadAbort.current = controller;
    const expectedGeneration = selectionGenerationRef.current;
    if (selectedRefRef.current !== requestRef) {
      if (singleReloadAbort.current === controller) singleReloadAbort.current = null;
      return;
    }
    try {
      const value = await responseJson<ExternalSingleVolumeReportView>(await fetch(
        `/api/external-single-volume-reports/${encodeURIComponent(reportRef)}`,
        { cache: "no-store", signal: controller.signal },
      ));
      if (controller.signal.aborted || singleReloadAbort.current !== controller) return;
      if (selectedRefRef.current !== requestRef || selectionGenerationRef.current !== expectedGeneration) return;
      if (value.report.reportId !== reportRef || value.request.requestId !== requestRef) throw new Error("REPORT_BINDING_CHANGED");
      setReport(value);
      setReportPhase("ready");
    } catch (error) {
      if (isAbort(error) || controller.signal.aborted || singleReloadAbort.current !== controller) return;
      if (selectedRefRef.current !== requestRef || selectionGenerationRef.current !== expectedGeneration) return;
      setReport(null);
      setReportPhase("error");
    } finally {
      if (singleReloadAbort.current === controller) singleReloadAbort.current = null;
    }
  }, []);

  const singleReportId = report?.report.reportId ?? null;
  const handleSingleReviewed = useCallback(() => {
    if (selectedRef && singleReportId) void reloadSingleReport(singleReportId, selectedRef);
  }, [reloadSingleReport, selectedRef, singleReportId]);
  const handleSingleProposal = useCallback(() => {
    if (selectedRef && singleReportId) void reloadSingleReport(singleReportId, selectedRef);
  }, [reloadSingleReport, selectedRef, singleReportId]);

  if (notConfigured) {
    return (
      <div className="flex flex-col gap-2 rounded-lg border border-line p-3">
        <h3 className="font-semibold">단일 시점 체적 측정</h3>
        <p className="text-ink-2">이 환경에는 단일 시점 체적 측정이 구성되지 않았습니다.</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-line p-3">
      <h3 className="font-semibold">단일 시점 체적 측정</h3>
      {!decision ? (
        <p className="text-ink-2">{newIntentAllowed ? "현재 선택에서 단일 시점 체적 결정을 요청하세요." : "업무 종료된 작업입니다. 기존 체적 측정 기록만 확인할 수 있습니다."}</p>
      ) : decision.verdict !== "ELIGIBLE" ? (
        <ExternalUseBlockerCard
          reasons={decision.reasons}
          remediations={decision.remediations}
          intro="현재 선택으로는 단일 시점 체적 측정을 요청할 수 없습니다."
        />
      ) : canIssue ? (
        <ResponsiveActionBoundary action="EXTERNAL_RECONSTRUCTION_MUTATION" reason="단일 시점 체적 측정 요청은 노트북 이상의 화면에서 진행합니다.">
          <button className="btn w-fit" disabled={busy} onClick={() => void issue()}>
            {busy ? "체적 측정 요청 중" : "단일 시점 체적 측정 요청"}
          </button>
        </ResponsiveActionBoundary>
      ) : (
        <p className="text-ink-2">{newIntentAllowed ? "단일 시점 체적 요청에는 SITES_WRITE 권한이 필요합니다." : "업무 종료 상태에서는 새 단일 시점 체적 측정을 요청할 수 없습니다."}</p>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="font-semibold">체적 측정 요청 목록</h4>
        {!listReadBlocked && <button className="btn" disabled={listPhase === "loading"} onClick={() => void loadList()}>체적 목록 새로고침</button>}
      </div>
      {listPhase === "loading" && <p role="status" className="text-ink-2">체적 측정 요청 목록을 읽는 중입니다.</p>}
      {listPhase === "error" && <p role="alert" className="text-high-ink">{listError ?? "체적 측정 요청 목록을 읽지 못했습니다. 새로고침으로 다시 시도하세요."}</p>}
      {listPhase === "ready" && (list.length === 0
        ? <p className="text-ink-2">기록된 단일 시점 체적 측정 요청이 없습니다. 요청이 생성되면 상태와 결과를 이 목록에서 확인할 수 있습니다.</p>
        : <ul className="flex flex-col gap-2">{list.map((item) => <li key={item.requestRef} className="flex flex-wrap items-center justify-between gap-2"><span>{statusLabel(item.status)} · {requestMoment(item.issuedAt)}{isUnfinishedRequest(item.status) && recordedDeadlineElapsed(item.deadlineAt) && " · 마감 시각 경과"}</span><button className="btn" onClick={() => selectRequest(item.requestRef)}>체적 요청 상태</button></li>)}</ul>)}

      {selected && <p className="text-ink-2">선택한 체적 요청: {statusLabel(selected.status)}{isUnfinishedRequest(selected.status) ? ` · 마감 ${requestMoment(selected.deadlineAt)}${recordedDeadlineElapsed(selected.deadlineAt) ? " · 마감 시각 경과" : ""}` : ""}</p>}
      {pollStopped && isUnfinishedRequest(selected?.status) && <p role="status" className="text-ink-2">{AUTO_REFRESH_STOPPED_NOTICE}</p>}
      {selectedError && <p role="alert" className="text-high-ink">{selectedError}</p>}
      {selected?.status === "FAILED" && <p role="alert" className="text-high-ink">이 단일 시점 체적 측정을 완료하지 못했습니다. 결과 수치는 표시하지 않습니다.</p>}
      {reportPhase === "loading" && <p role="status">체적 결과를 읽는 중입니다.</p>}
      {reportPhase === "error" && <p role="alert">체적 결과를 읽지 못했습니다. 완료로 추정하지 않습니다.</p>}
      {report && reportPhase === "ready" && <>
        <SingleVolumeReportDetail view={report} />
        <ExternalResultReviewActions
          key={selectedRef ?? report.report.reportId}
          reportRef={report.report.reportId}
          reviewPath={`/api/external-single-volume-reports/${encodeURIComponent(report.report.reportId)}/reviews`}
          review={report.review ?? null}
          proposals={report.proposals ?? []}
          targetWorkAreaId={report.request.zoneSnapshot.workAreaId}
          targetLabel="대상: 이 측정에 사용한 작업구역"
          reviewReason="단일 시점 결과 검토 기록은 노트북 이상의 화면에서 진행합니다."
          newIntentAllowed={newIntentAllowed}
          hasReviewPermission={hasReviewPermission}
          canApprovePermission={canApprovePermission}
          onReviewed={handleSingleReviewed}
          onProposal={handleSingleProposal}
          onApproved={onApproved}
          renderReviewDetail={(item) => <SingleVolumeReviewAuditDetail review={item} />}
        />
      </>}
      {message && <p role="status">{message}</p>}
    </div>
  );
}

export function ExternalResultWorkflowPanel({
  workOrderId,
  siteId,
  decision,
  singleVolumeDecision,
  permissions,
  initialReport,
  newIntentAllowed = true,
}: {
  workOrderId: string;
  siteId: string;
  decision: ExternalRelativeVolumeDecision | null;
  /**
   * The current SINGLE_VOLUME decision. `undefined` means the single-volume family is not
   * wired into this view, so its request list is not read.
   */
  singleVolumeDecision?: ExternalRelativeVolumeDecision | null;
  permissions: readonly string[];
  initialReport?: TrustedExternalResultLink;
  newIntentAllowed?: boolean;
}) {
  const router = useRouter();
  const scope = useRef(0);
  const activeMutation = useRef<AbortController | null>(null);
  const listAbort = useRef<AbortController | null>(null);
  const requestAbort = useRef<AbortController | null>(null);
  const reportAbort = useRef<AbortController | null>(null);
  const worklistVerified = useRef(false);
  const worklistAutoRefreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const worklistAutoRefreshBudget = useRef(0);
  const worklistAutoRefreshInFlight = useRef(false);
  const [worklistPhase, setWorklistPhase] = useState<Phase>("loading");
  const [worklistRefreshing, setWorklistRefreshing] = useState(false);
  const [worklistAutoRefreshStopped, setWorklistAutoRefreshStopped] = useState(false);
  const [worklistNotConfigured, setWorklistNotConfigured] = useState(false);
  const [worklistError, setWorklistError] = useState<string | null>(null);
  const [worklistReadBlocked, setWorklistReadBlocked] = useState(false);
  const [documentVisible, setDocumentVisible] = useState(true);
  const [worklist, setWorklist] = useState<ExternalRelativeVolumeRequestView[]>([]);
  const [selectedRequestRef, setSelectedRequestRef] = useState<string | null>(null);
  const [selectionGeneration, setSelectionGeneration] = useState(0);
  const [selectedRequest, setSelectedRequest] = useState<ExternalRelativeVolumeRequestView | null>(null);
  const [selectedRequestRefreshing, setSelectedRequestRefreshing] = useState(false);
  const [selectedRequestError, setSelectedRequestError] = useState<string | null>(null);
  const [report, setReport] = useState<ExternalRelativeVolumeReportView | null>(initialReport?.view ?? null);
  const [reportPhase, setReportPhase] = useState<Phase>(initialReport ? "ready" : "idle");
  const [busy, setBusy] = useState<BusyOperation | null>(null);
  const [issueAttempt, setIssueAttempt] = useState<FrozenIssue | null>(null);
  const [reportWorkAreaName, setReportWorkAreaName] = useState<string | null>(initialReport?.workAreaName ?? null);
  const [message, setMessage] = useState<string | null>(null);
  const [worklistNotice, setWorklistNotice] = useState<string | null>(null);
  const [worklistRefreshNotice, setWorklistRefreshNotice] = useState<string | null>(null);

  const hasIssuePermission = permissions.includes("SITES_WRITE");
  const hasReviewPermission = permissions.includes("WORK_ORDERS_WRITE");
  const hasApprovalPermission = permissions.includes("REOBSERVATION_APPROVE");
  // Issuing, proposing, and approving have retained idempotency attempts. A
  // closed task may reconcile that exact durable request, but cannot begin a
  // replacement intent.
  const canIssue = hasIssuePermission && (newIntentAllowed || issueAttempt !== null);
  const decisionIdentity = decision ? `${decision.decisionId}|${decision.decisionDigest}` : "";

  useEffect(() => {
    let active = true;
    worklistVerified.current = false;
    worklistAutoRefreshBudget.current = 0;
    worklistAutoRefreshInFlight.current = false;
    void Promise.resolve().then(() => {
      if (!active) return;
      setWorklist([]);
      setWorklistRefreshing(false);
      setWorklistAutoRefreshStopped(false);
      setWorklistError(null);
      setWorklistReadBlocked(false);
      setWorklistRefreshNotice(null);
    });
    return () => { active = false; };
  }, [workOrderId]);

  const loadWorklist = useCallback(async ({
    preserveVerified = false,
    automatic = false,
  }: {
    preserveVerified?: boolean;
    automatic?: boolean;
  } = {}) => {
    listAbort.current?.abort();
    const controller = new AbortController();
    listAbort.current = controller;
    const retainLastVerified = preserveVerified && worklistVerified.current;
    setWorklistNotConfigured(false);
    setWorklistRefreshNotice(null);
    if (retainLastVerified) setWorklistRefreshing(true);
    else {
      setWorklistPhase("loading");
      setWorklistError(null);
    }
    try {
      const response = await fetch(
        `/api/observation-work-orders/${encodeURIComponent(workOrderId)}/relative-volume-requests`,
        { cache: "no-store", signal: controller.signal },
      );
      if (response.status === 404) {
        if (listAbort.current !== controller) return;
        if (retainLastVerified) {
          setWorklistRefreshNotice("현재 환경에서 비교 요청 목록을 읽을 수 없습니다. 마지막으로 확인한 요청 상태를 유지합니다.");
        } else {
          setWorklistNotConfigured(true);
          setWorklistPhase("idle");
          setWorklistError(null);
          setWorklistReadBlocked(false);
        }
        return;
      }
      const value = await responseJson<{ items: unknown }>(response);
      if (!Array.isArray(value.items) || !value.items.every(isKnownRequestView)) throw new Error(UNKNOWN_REQUEST_STATUS);
      if (listAbort.current !== controller) return;
      setWorklist(value.items);
      worklistVerified.current = true;
      setWorklistPhase("ready");
      setWorklistError(null);
      setWorklistReadBlocked(false);
    } catch (error) {
      if (isAbort(error) || listAbort.current !== controller) return;
      const readBlocked = error instanceof WorkflowResponseError && (error.status === 401 || error.status === 403);
      setWorklistReadBlocked(readBlocked);
      if (retainLastVerified) {
        if (automatic) {
          setWorklistAutoRefreshStopped(true);
          setWorklistRefreshNotice(error instanceof WorkflowResponseError && (error.status === 401 || error.status === 403)
            ? `마지막으로 확인한 목록을 유지합니다. ${requestListReadError(error, "비교")}`
            : error instanceof Error && error.message === UNKNOWN_REQUEST_STATUS
            ? "요청 상태 형식을 확인하지 못해 자동 상태 확인을 멈췄습니다. 마지막으로 확인한 요청 상태를 표시합니다. 수동 새로고침으로 다시 확인하세요."
            : AUTO_REFRESH_STOPPED_NOTICE);
        } else {
          setWorklistRefreshNotice(error instanceof WorkflowResponseError && (error.status === 401 || error.status === 403)
            ? `마지막으로 확인한 목록을 유지합니다. ${requestListReadError(error, "비교")}`
            : error instanceof Error && error.message === UNKNOWN_REQUEST_STATUS
            ? "요청 상태 형식을 확인하지 못했습니다. 마지막으로 확인한 상태를 표시합니다. 새로고침으로 다시 시도하세요."
            : "요청 목록을 새로고치지 못했습니다. 마지막으로 확인한 상태를 표시합니다. 다시 시도하세요.");
        }
      } else {
        setWorklistPhase("error");
        setWorklistError(requestListReadError(error, "비교"));
      }
    } finally {
      if (listAbort.current === controller) {
        listAbort.current = null;
        if (retainLastVerified) setWorklistRefreshing(false);
      }
    }
  }, [workOrderId]);

  const loadReport = useCallback(async (reportRef: string) => {
    if (!isExternalRelativeVolumeReportReference(reportRef)) {
      setReport(null);
      setReportPhase("error");
      return;
    }
    reportAbort.current?.abort();
    const controller = new AbortController();
    reportAbort.current = controller;
    setReportPhase("loading");
    try {
      const response = await fetch(`/api/external-relative-volume-reports/${encodeURIComponent(reportRef)}`, {
        cache: "no-store",
        signal: controller.signal,
      });
      const value = await responseJson<ExternalRelativeVolumeReportView>(response);
      if (reportAbort.current !== controller) return;
      setReport(value);
      setReportWorkAreaName(null);
      setReportPhase("ready");
    } catch (error) {
      if (isAbort(error) || reportAbort.current !== controller) return;
      setReport(null);
      setReportPhase("error");
    } finally {
      if (reportAbort.current === controller) reportAbort.current = null;
    }
  }, []);

  useEffect(() => {
    let active = true;
    void Promise.resolve().then(() => {
      if (active) void loadWorklist();
    });
    return () => {
      active = false;
      listAbort.current?.abort();
    };
  }, [loadWorklist]);

  useEffect(() => {
    const updateVisibility = () => setDocumentVisible(document.visibilityState !== "hidden");
    updateVisibility();
    document.addEventListener("visibilitychange", updateVisibility);
    return () => document.removeEventListener("visibilitychange", updateVisibility);
  }, []);

  useEffect(() => {
    if (worklistAutoRefreshTimer.current !== null) {
      clearTimeout(worklistAutoRefreshTimer.current);
      worklistAutoRefreshTimer.current = null;
    }
    if (
      !documentVisible || worklistAutoRefreshStopped || !worklistVerified.current
      || !worklist.some((item) => isUnfinishedRequest(item.status))
      || worklistAutoRefreshBudget.current >= AUTO_REQUEST_REFRESH_BUDGET
    ) return;
    worklistAutoRefreshTimer.current = setTimeout(() => {
      worklistAutoRefreshTimer.current = null;
      if (document.visibilityState === "hidden" || worklistAutoRefreshInFlight.current) return;
      worklistAutoRefreshInFlight.current = true;
      worklistAutoRefreshBudget.current += 1;
      void loadWorklist({ preserveVerified: true, automatic: true }).finally(() => {
        worklistAutoRefreshInFlight.current = false;
      });
    }, AUTO_REQUEST_REFRESH_DELAY_MS);
    return () => {
      if (worklistAutoRefreshTimer.current !== null) {
        clearTimeout(worklistAutoRefreshTimer.current);
        worklistAutoRefreshTimer.current = null;
      }
    };
  }, [documentVisible, loadWorklist, worklist, worklistAutoRefreshStopped]);

  useEffect(() => {
    if (!selectedRequestRef || !isExternalRelativeVolumeRequestReference(selectedRequestRef)) return;
    requestAbort.current?.abort();
    const controller = new AbortController();
    requestAbort.current = controller;
    void Promise.resolve().then(async () => {
      try {
        const response = await fetch(
          `/api/observation-work-orders/${encodeURIComponent(workOrderId)}/relative-volume-requests/${encodeURIComponent(selectedRequestRef)}`,
          { cache: "no-store", signal: controller.signal },
        );
        const value = await responseJson<unknown>(response);
        if (!isKnownRequestView(value)) throw new Error(UNKNOWN_REQUEST_STATUS);
        if (requestAbort.current !== controller) return;
        setSelectedRequest(value);
        setSelectedRequestRefreshing(false);
        setSelectedRequestError(null);
        if (value.reportRef) void loadReport(value.reportRef);
        else {
          setReport(null);
          setReportPhase("idle");
          setReportWorkAreaName(null);
        }
      } catch (error) {
        if (isAbort(error) || requestAbort.current !== controller) return;
        setSelectedRequestRefreshing(false);
        setSelectedRequestError(error instanceof Error && error.message === UNKNOWN_REQUEST_STATUS
          ? "요청 상태 형식을 확인하지 못했습니다. 마지막으로 확인한 요청과 목록을 유지합니다. 다시 시도하세요."
          : "요청 상태를 확인하지 못했습니다. 마지막으로 확인한 요청과 목록을 유지합니다. 다시 시도하세요.");
      } finally {
        if (requestAbort.current === controller) requestAbort.current = null;
      }
    });
    return () => controller.abort();
  }, [loadReport, selectedRequestRef, selectionGeneration, workOrderId]);

  useEffect(() => {
    scope.current += 1;
    const decisionScope = scope.current;
    const controller = activeMutation.current;
    activeMutation.current = null;
    controller?.abort();
    void Promise.resolve().then(() => {
      if (scope.current !== decisionScope) return;
      setBusy(null);
      setIssueAttempt(null);
      setMessage(null);
    });
  }, [decisionIdentity]);

  useEffect(() => () => {
    activeMutation.current?.abort();
    requestAbort.current?.abort();
    reportAbort.current?.abort();
    listAbort.current?.abort();
    if (worklistAutoRefreshTimer.current !== null) clearTimeout(worklistAutoRefreshTimer.current);
  }, []);

  const beginMutation = (operation: BusyOperation) => {
    activeMutation.current?.abort();
    const controller = new AbortController();
    activeMutation.current = controller;
    setBusy(operation);
    return { controller, requestScope: scope.current };
  };

  const ownsMutation = (controller: AbortController, requestScope: number) =>
    activeMutation.current === controller && scope.current === requestScope;

  const finishMutation = (controller: AbortController, requestScope: number) => {
    if (activeMutation.current === controller) {
      activeMutation.current = null;
      if (scope.current === requestScope) setBusy(null);
    }
  };

  const selectRequest = (requestRef: string) => {
    scope.current += 1;
    const controller = activeMutation.current;
    activeMutation.current = null;
    controller?.abort();
    requestAbort.current?.abort();
    requestAbort.current = null;
    reportAbort.current?.abort();
    reportAbort.current = null;
    setBusy(null);
    setSelectedRequestRefreshing(true);
    setSelectedRequestError(null);
    setMessage(null);
    setWorklistNotice(null);
    setWorklistRefreshNotice(null);
    if (selectedRequestRef === requestRef) setSelectionGeneration((current) => current + 1);
    setSelectedRequestRef(requestRef);
  };

  const issue = async () => {
    if (!decision || decision.verdict !== "ELIGIBLE" || !canIssue || busy) return;
    let attempt = issueAttempt;
    const matchesDecision = attempt?.decisionId === decision.decisionId
      && attempt.decisionDigest === decision.decisionDigest;
    if (!newIntentAllowed && !matchesDecision) {
      setMessage("업무 종료 상태에서는 새 상대 물량 비교를 요청할 수 없습니다.");
      return;
    }
    if (!matchesDecision) {
      attempt = { decisionId: decision.decisionId, decisionDigest: decision.decisionDigest, idempotencyKey: makeKey() };
      setIssueAttempt(attempt);
    }
    if (!attempt) return;
    const { controller, requestScope } = beginMutation("issue");
    setMessage(null);
    try {
      const response = await fetch(
        `/api/observation-work-orders/${encodeURIComponent(workOrderId)}/relative-volume-requests`,
        {
          method: "POST",
          headers: { "content-type": "application/json", "idempotency-key": attempt.idempotencyKey },
          body: JSON.stringify({ decisionRef: attempt.decisionId }),
          signal: controller.signal,
        },
      );
      const value = await responseJson<{ verdict: string; request: unknown; detail: string | null }>(response);
      if (!ownsMutation(controller, requestScope)) return;
      if (!isKnownRequestView(value.request)) throw new Error(value.request === null ? (value.detail ?? value.verdict) : UNKNOWN_REQUEST_STATUS);
      selectRequest(value.request.requestRef);
      setMessage("외부 상대 물량 비교를 요청했습니다.");
      void loadWorklist();
    } catch (error) {
      if (!isAbort(error) && ownsMutation(controller, requestScope)) setMessage(issueFailureMessage(error));
    } finally {
      finishMutation(controller, requestScope);
    }
  };

  const refreshActualWorklist = async (
    successorWorkOrderId: string,
    signal: AbortSignal,
  ) => {
    try {
      const response = await fetch(`/api/sites/${encodeURIComponent(siteId)}/observation-work-orders`, {
        cache: "no-store",
        signal,
      });
      const value = await responseJson<{ workOrders: Array<{ workOrderId: string }> }>(response);
      if (signal.aborted) return;
      setWorklistNotice(
        value.workOrders.some((item) => item.workOrderId === successorWorkOrderId)
          ? "작업 목록에서 후속 작업을 새로 고쳤습니다."
          : "작업 목록을 새로 고쳤지만 후속 작업 반영을 아직 확인하지 못했습니다.",
      );
    } catch (error) {
      if (!isAbort(error) && !signal.aborted) {
        setWorklistNotice("작업 목록을 새로 고치지 못했습니다. 후속 작업 페이지에서 다시 확인하세요.");
      }
    }
  };

  const handleApproved = async (view: ExternalReobservationProposalView, signal: AbortSignal) => {
    const receipt = view.approvalReceipt;
    if (!receipt || signal.aborted) return;
    await refreshActualWorklist(receipt.successorWorkOrderId, signal);
    if (signal.aborted) return;
    router.refresh();
    router.push(`/field/work-orders/${encodeURIComponent(receipt.successorWorkOrderId)}`);
  };

  return (
    <section id="external-volume" className="flex flex-col gap-3 rounded-xl border border-line bg-surface p-4 text-[13px]">
      <div>
        <h2 className="text-[16px] font-bold">외부 상대 물량과 재관측 검토</h2>
        <p className="text-ink-2">등록된 상대 물량 요청·결과·검토·재관측 제안만 표시합니다. 이 화면만으로 현장 실행 여부를 판단할 수 없습니다.</p>
      </div>
      {!newIntentAllowed && <p className="rounded-lg border border-line bg-sunk px-3 py-2 leading-5 text-ink-2">업무 종료 상태입니다. 새 비교·검토·재관측 요청은 시작할 수 없지만, 기존 요청과 결과는 계속 확인할 수 있습니다.</p>}

      {!decision ? (
        <p>{newIntentAllowed ? "현재 선택에서 상대 물량 비교를 요청하세요." : "업무 종료된 작업입니다. 기존 비교 결과와 요청 기록만 확인할 수 있습니다."}</p>
      ) : decision.verdict !== "ELIGIBLE" ? (
        <ExternalUseBlockerCard
          reasons={decision.reasons}
          remediations={decision.remediations}
          intro="현재 선택으로는 상대 물량 비교를 요청할 수 없습니다."
        />
      ) : canIssue ? (
        <ResponsiveActionBoundary action="EXTERNAL_RECONSTRUCTION_MUTATION" reason="외부 상대 물량 비교 요청은 노트북 이상의 화면에서 진행합니다.">
          <button className="btn w-fit" disabled={busy !== null} onClick={() => void issue()}>
            {busy === "issue" ? "비교 요청 중" : "상대 물량 비교 요청"}
          </button>
        </ResponsiveActionBoundary>
      ) : (
        <p className="text-ink-2">{newIntentAllowed ? "상대 물량 요청에는 SITES_WRITE 권한이 필요합니다." : "업무 종료 상태에서는 새 상대 물량 비교를 요청할 수 없습니다."}</p>
      )}

      <div className="rounded-lg border border-line p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="font-semibold">비교 요청 목록</h3>
          {!worklistReadBlocked && !worklistNotConfigured && <button className="btn" disabled={worklistPhase === "loading" || worklistRefreshing} onClick={() => { worklistAutoRefreshBudget.current = 0; setWorklistAutoRefreshStopped(false); void loadWorklist({ preserveVerified: true }); }}>목록 새로고침</button>}
        </div>
        {worklistPhase === "loading" && <p role="status" className="mt-2 text-ink-2">비교 요청 목록을 읽는 중입니다.</p>}
        {worklistRefreshing && <p role="status" className="mt-2 text-ink-2">마지막으로 확인한 요청 상태를 유지한 채 업데이트를 확인하고 있습니다.</p>}
        {worklistNotConfigured && <p role="status" className="mt-2 text-ink-2">비교 요청 목록을 확인할 수 없습니다. 마지막으로 확인한 요청 상태와 연결된 결과는 계속 확인할 수 있습니다.</p>}
        {worklistPhase === "error" && <p role="alert" className="mt-2 text-high-ink">{worklistError ?? "비교 요청 목록을 읽지 못했습니다. 새로고침으로 다시 시도하세요."}</p>}
        {worklistPhase === "ready" && (worklist.length === 0 ? <p className="mt-2 text-ink-2">기록된 상대 물량 비교 요청이 없습니다. 요청이 생성되면 상태와 보고서가 이 목록에 표시됩니다.</p> : <ul className="mt-2 flex flex-col gap-2">{worklist.map((item) => <li key={item.requestRef} className="flex flex-wrap items-center justify-between gap-2"><span>{statusLabel(item.status)} · {requestMoment(item.issuedAt)}{isUnfinishedRequest(item.status) && recordedDeadlineElapsed(item.deadlineAt) && " · 마감 시각 경과"}</span><button className="btn" onClick={() => selectRequest(item.requestRef)}>비교 요청 상태</button></li>)}</ul>)}
      </div>

      {selectedRequest && <p className="text-ink-2">선택한 요청: {statusLabel(selectedRequest.status)}{isUnfinishedRequest(selectedRequest.status) ? ` · 마감 ${requestMoment(selectedRequest.deadlineAt)}${recordedDeadlineElapsed(selectedRequest.deadlineAt) ? " · 마감 시각 경과" : ""}` : ""}</p>}
      {selectedRequestRefreshing && <p role="status" className="text-ink-2">마지막으로 확인한 요청을 유지한 채 상태를 확인하고 있습니다.</p>}
      {selectedRequestError && <p role="alert" className="text-high-ink">{selectedRequestError}</p>}
      {selectedRequest?.status === "FAILED" && <p role="alert" className="text-high-ink">이 상대 물량 비교를 완료하지 못했습니다. 결과 수치는 표시하지 않습니다.</p>}
      {reportPhase === "loading" && <p role="status">비교 결과를 읽는 중입니다.</p>}
      {reportPhase === "error" && <div role="alert" className="flex flex-wrap gap-2"><p>비교 결과를 읽지 못했습니다. 완료로 추정하지 않습니다.</p>{selectedRequest?.reportRef && <button className="btn" onClick={() => void loadReport(selectedRequest.reportRef!)}>보고서 다시 시도</button>}</div>}
      {report && <>
        <ReportDetail view={report} workAreaName={reportWorkAreaName} />
        <ExternalResultReviewActions
          key={selectedRequestRef ?? report.report.reportId}
          reportRef={report.report.reportId}
          reviewPath={`/api/external-relative-volume-reports/${encodeURIComponent(report.report.reportId)}/reviews`}
          review={report.review ?? null}
          proposals={report.proposals}
          targetWorkAreaId={report.request.zoneSnapshot.workAreaId}
          targetLabel="대상: 이 비교에 사용한 작업구역"
          reviewReason="비교 결과 검토 기록은 노트북 이상의 화면에서 진행합니다."
          newIntentAllowed={newIntentAllowed}
          hasReviewPermission={hasReviewPermission}
          canApprovePermission={hasApprovalPermission}
          onReviewed={() => loadReport(report.report.reportId)}
          onProposal={() => loadReport(report.report.reportId)}
          onApproved={handleApproved}
          renderReviewDetail={(item) => <ReviewAuditDetail review={item} />}
        />
      </>}

      {singleVolumeDecision !== undefined && <SingleVolumeWorkflow
        key={workOrderId}
        workOrderId={workOrderId}
        decision={singleVolumeDecision}
        canIssuePermission={hasIssuePermission}
        newIntentAllowed={newIntentAllowed}
        hasReviewPermission={hasReviewPermission}
        canApprovePermission={hasApprovalPermission}
        onApproved={handleApproved}
      />}

      {message && <p role="status">{message}</p>}
      {worklistNotice && <p role="status">{worklistNotice}</p>}
      {worklistRefreshNotice && <p role="status">{worklistRefreshNotice}</p>}
    </section>
  );
}
