"use client";

import { useRef, useState } from "react";

import type {
  DesignProgress,
  ReportExportCreateInput,
  ReportExportCreateResponse,
  ReportExportSnapshot,
} from "@/lib/core-api/types";
import { formatKoreanDateTime } from "@/lib/datetime";
import { siteReportToCsv } from "@/lib/report-csv";
import {
  coverageSnapshotMatchesEvidence,
  isCompleteCoverageEvidence,
  type CompleteReportCoverageEvidence,
  type ReportCoverageEvidence,
} from "@/lib/reports/coverage-evidence";

type ExportFormat = ReportExportCreateInput["exportFormat"];
type ExportStatus = "idle" | "pending" | "error";

function newExportId(): string {
  return typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `report-export-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

/** 같은 형식에서 응답 유실 뒤 재시도하면 기존 action id를 재사용한다. */
export function exportIdForAttempt(retainedId: string | undefined): string {
  return retainedId ?? newExportId();
}

async function errorMessage(response: Response): Promise<string> {
  const body = (await response.json().catch(() => ({}))) as { message?: string; detail?: string };
  return body.detail ?? body.message ?? "감사 기록을 만들지 못했습니다. 네트워크 상태를 확인하세요.";
}

/** 브라우저의 same-origin BFF를 통해 불변 보고서 snapshot 기록만 요청한다. */
export async function requestReportExportAudit(
  siteId: string,
  input: ReportExportCreateInput,
): Promise<ReportExportCreateResponse> {
  const response = await fetch(`/api/sites/${encodeURIComponent(siteId)}/report-exports`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!response.ok) throw new Error(await errorMessage(response));
  return (await response.json()) as ReportExportCreateResponse;
}

/**
 * 감사 기록이 확정되기 전에는 브라우저 출력도 시작하지 않는다.
 *
 * 함수 자체를 작게 분리해 인쇄/Blob 구현을 시험에서 실행하지 않고도 순서를
 * 고정한다. `produce`에는 실제 PDF 생성이나 업로드 같은 서버 작업이 없다.
 */
export async function recordBeforeBrowserExport(
  requestAudit: () => Promise<ReportExportCreateResponse>,
  produce: () => void,
  expectation: {
    siteId: string;
    progress: DesignProgress;
    coverage: CompleteReportCoverageEvidence;
  },
): Promise<ReportExportCreateResponse> {
  const record = await requestAudit();
  if (
    (record.verdict !== "RECORDED" && record.verdict !== "ALREADY_RECORDED") ||
    !record.exportId ||
    !record.recordedAt ||
    !record.snapshotDigest ||
    record.contentProducedByServer !== false ||
    !record.snapshot ||
    !reportExportSnapshotMatches(expectation, record.snapshot)
  ) {
    throw new Error(record.detail ?? "감사 스냅샷을 확인하지 못해 내보내기를 시작하지 않았습니다.");
  }
  produce();
  return record;
}

/** The audit response must describe exactly the server-rendered document inputs. */
export function reportExportSnapshotMatches(
  expectation: {
    siteId: string;
    progress: DesignProgress;
    coverage: CompleteReportCoverageEvidence;
  },
  snapshot: ReportExportSnapshot,
): boolean {
  const { progress, coverage, siteId } = expectation;
  return (
    snapshot.schemaVersion === "1.1" &&
    snapshot.siteId === siteId &&
    progress.siteId === siteId &&
    snapshot.designSurfaceId === progress.designSurfaceId &&
    snapshot.designSurfaceSha256 === progress.designSurfaceSha256 &&
    snapshot.baseline.designConformanceId === progress.baselineDesignConformanceId &&
    snapshot.baseline.computedAt === progress.baselineComputedAt &&
    snapshot.latest.designConformanceId === progress.latestDesignConformanceId &&
    snapshot.latest.computedAt === progress.latestComputedAt &&
    snapshot.coverage !== null &&
    snapshot.coverage.missionId === snapshot.latest.missionId &&
    coverageSnapshotMatchesEvidence(coverage, snapshot.coverage)
  );
}

/**
 * 현장 보고서(M4-D) 내보내기 — "PDF로 저장"(브라우저 인쇄)과 "CSV로 내보내기".
 *
 * 둘 다 화면이 이미 렌더한 것과 **같은 서버 렌더 입력**(`progress` + `coverage`)에서
 * 나온다 — 인쇄는 지금 그려진 DOM 을 그대로 종이로 옮기고(`window.print()`), CSV 는
 * 그 DOM 을 만든 바로 그 입력을 `siteReportToCsv` 로 문자열화한다.
 * 그래서 "화면과 종이가 다른 숫자"가 구조적으로 생기지 않는다 — 별도 API 를
 * 다시 불러 값을 새로 계산하지 않는다.
 *
 * `print:hidden` 을 이 컨트롤 자체에도 건다 — 인쇄 결과물에 "인쇄" 버튼이 찍히면
 * 그 자체가 이 문서가 인쇄물이 아니라 화면 캡처라는 신호가 된다.
 */
export function ReportExportControls({
  progress,
  fileNameBase,
  siteId,
  coverage,
}: {
  progress: DesignProgress;
  fileNameBase: string;
  /** 서버 렌더 시 신뢰한 현장 식별자 — 브라우저 입력에서 다시 만들지 않는다. */
  siteId: string;
  coverage: ReportCoverageEvidence;
}) {
  const retainedExportIds = useRef<Partial<Record<ExportFormat, string>>>({});
  const [status, setStatus] = useState<ExportStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [record, setRecord] = useState<ReportExportCreateResponse | null>(null);

  function produceCsv(completeCoverage: CompleteReportCoverageEvidence) {
    const csv = siteReportToCsv(progress, completeCoverage);
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = `${fileNameBase}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    // click 직후 동기 해제는 일부 브라우저에서 다운로드를 취소시킨다
    // (KmzDownloadButton.tsx 와 같은 이유로 여유를 두고 해제한다).
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
  }

  async function handleExport(exportFormat: ExportFormat) {
    if (status === "pending") return;
    if (!isCompleteCoverageEvidence(coverage)) {
      setError("커버리지 근거가 불완전해 내보내지 않았습니다. 문서를 새로고침하세요.");
      setStatus("error");
      return;
    }
    const exportId = exportIdForAttempt(retainedExportIds.current[exportFormat]);
    retainedExportIds.current[exportFormat] = exportId;
    setStatus("pending");
    setError(null);

    try {
      const auditInput: ReportExportCreateInput = {
        exportId,
        exportFormat,
        // 이 두 ID는 보고서를 만들 때 Core가 반환한 `progress`에서만 온다. 클라이언트가
        // 부른 "최신" 결과를 새로 찾아 감사 대상과 현재 화면을 어긋나게 하지 않는다.
        baselineDesignConformanceId: progress.baselineDesignConformanceId,
        latestDesignConformanceId: progress.latestDesignConformanceId,
      };
      const audited = await recordBeforeBrowserExport(
        () => requestReportExportAudit(siteId, auditInput),
        exportFormat === "PDF" ? () => window.print() : () => produceCsv(coverage),
        { siteId, progress, coverage },
      );
      delete retainedExportIds.current[exportFormat];
      setRecord(audited);
      setStatus("idle");
    } catch (cause) {
      // 응답이 도중에 유실됐을 수 있다. retained exportId는 다음 같은 형식 클릭에서
      // 그대로 보내지고, Core가 이미 기록했다면 ALREADY_RECORDED로 안전하게 응답한다.
      setError(cause instanceof Error ? cause.message : "내보내기를 시작하지 못했습니다.");
      setStatus("error");
    }
  }

  return (
    <div className="print:hidden flex flex-col items-start gap-2">
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => void handleExport("PDF")}
          disabled={status === "pending" || !isCompleteCoverageEvidence(coverage)}
        >
          {status === "pending" ? "감사 기록 중…" : "PDF로 저장(인쇄)"}
        </button>
        <button
          type="button"
          className="btn"
          onClick={() => void handleExport("CSV")}
          disabled={status === "pending" || !isCompleteCoverageEvidence(coverage)}
        >
          CSV로 내보내기
        </button>
      </div>
      {error && <p className="text-[11.5px] font-semibold break-keep text-crit-ink">{error}</p>}
      {!isCompleteCoverageEvidence(coverage) && (
        <p className="text-[11.5px] font-semibold break-keep text-crit-ink">
          커버리지 보고와 서버 거부 이력을 모두 확인할 때까지 PDF·CSV 내보내기를 사용할 수
          없습니다.
        </p>
      )}
      {record?.recordedAt && record.snapshotDigest && (
        <p className="text-[11px] break-keep text-ink-muted">
          감사 스냅샷 기록 {formatKoreanDateTime(record.recordedAt, { dateStyle: "medium", timeStyle: "short" })}
          <span className="num break-token"> · {record.snapshotDigest}</span>
        </p>
      )}
      <p className="text-[11px] break-keep text-ink-muted">
        PDF·CSV 바이트는 이 브라우저에서 생성합니다. 서버에는 파일이 아니라 같은 보고서의 감사
        스냅샷만 기록됩니다.
      </p>
    </div>
  );
}
