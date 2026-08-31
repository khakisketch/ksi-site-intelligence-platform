import Link from "next/link";
import { notFound } from "next/navigation";

import { CoreApiError } from "@/lib/core-api/client";
import { getDesignConformance, getDesignProgress, listDesignSurfaces } from "@/lib/core-api/design";
import { getProcessingJobArtifacts } from "@/lib/core-api/phase34";
import {
  DESIGN_SURFACE_STATUS_LABEL,
  humanizeApiError,
  humanizeVerticalDatum,
} from "@/lib/core-api/labels";
import { getSite } from "@/lib/core-api/sites";
import { ErrorState } from "@/components/ui/ErrorState";
import { DiffHeatmapOverlay } from "@/components/map/DiffHeatmapOverlay";
import { OrthophotoOverlay } from "@/components/map/OrthophotoOverlay";
import { CoverageReportSection } from "@/components/missions/CoverageReportSection";
import { ReportExportControls } from "@/components/reports/ReportExportControls";
import { formatKoreanDateTime } from "@/lib/datetime";
import { formatNetVolumeM3, formatVolumeM3 } from "@/lib/core-api/phase34-labels";
import { getCoverageRejections, getCoverageReport } from "@/lib/core-api/missions";
import {
  collectSiteReportData,
  matchLatestConformanceReport,
  type ConformanceMatch,
} from "@/lib/reports/collect-site-report-data";
import type { ReportCoverageEvidence } from "@/lib/reports/coverage-evidence";
import type {
  DesignConformanceListView,
  DesignSurface,
  ProcessingJobArtifactsView,
  ZoneProgress,
} from "@/lib/core-api/types";

/**
 * 현장 보고서 — 인쇄 전용 화면(M4-D, 확정안 browser-print).
 *
 * 새 산출물 파이프라인을 만들지 않는다. 화면 DOM 과 CSV 를 **같은 1회 서버 렌더**
 * (`getDesignProgress` → design/coverage 근거 → `getProcessingJobArtifacts`)에서
 * 뽑아 `ReportExportControls` 에 그대로 넘긴다 — "화면과 종이가 다른 숫자"가
 * 구조적으로 생길 수 없다. 데이터 조립(id 매칭·degrade 판정)은
 * `lib/reports/collect-site-report-data.ts` 의 순수 함수가 하고, 이 파일은 그
 * 결과를 문서 레이아웃으로 옮기기만 한다.
 *
 * PDF/CSV를 시작하기 전에 ReportExportControls가 같은 서버 렌더에서 얻은 두
 * DesignConformance ID를 Core에 보낸다. Core가 그 순간의 불변 report snapshot을
 * 다시 검증·기록하며, 실제 PDF/CSV bytes는 여전히 브라우저에서만 만든다.
 */

async function fetchConformanceList(missionId: string): Promise<DesignConformanceListView | null> {
  // 404 는 "아직 계산되지 않음"이고, 그 외 실패도 이 보조 섹션만 비운다 — 주
  // 내용인 구역 진척 표를 가리지 않는다(`reports/page.tsx` 의 `fetchVolume` 과
  // 같은 규약).
  try {
    return await getDesignConformance(missionId);
  } catch {
    return null;
  }
}

async function fetchJobArtifacts(jobId: string): Promise<ProcessingJobArtifactsView | null> {
  try {
    return await getProcessingJobArtifacts(jobId);
  } catch {
    return null;
  }
}

async function fetchCoverageEvidence(missionId: string): Promise<ReportCoverageEvidence> {
  const [reportResult, rejectionResult] = await Promise.allSettled([
    getCoverageReport(missionId),
    getCoverageRejections(missionId),
  ]);
  const report = reportResult.status === "fulfilled" ? reportResult.value : null;
  const rejections = rejectionResult.status === "fulfilled" ? rejectionResult.value : null;
  const reportIsAbsent =
    reportResult.status === "rejected" &&
    reportResult.reason instanceof CoreApiError &&
    reportResult.reason.status === 404;

  if (rejections === null || (report === null && !reportIsAbsent)) {
    return {
      status: "UNAVAILABLE",
      missionId,
      report,
      rejections,
      detail:
        "커버리지 보고 또는 서버 거부 이력을 모두 확인하지 못했습니다. 문서를 새로고침한 뒤 다시 시도하세요.",
    };
  }
  if (report === null) {
    return { status: "NOT_REPORTED", missionId, report: null, rejections };
  }
  return { status: "REPORTED", missionId, report, rejections };
}

function ratioLabel(ratio: number | null): string {
  if (ratio === null) return "해당 없음";
  return `${(ratio * 100).toLocaleString("ko-KR", { maximumFractionDigits: 1 })}%`;
}

function SurfacePicker({ siteId, surfaces }: { siteId: string; surfaces: DesignSurface[] }) {
  if (surfaces.length === 0) {
    return (
      <p className="text-[12.5px] break-keep text-ink-muted">
        이 현장에는 등록된 설계 기준면이 없습니다.{" "}
        <Link
          href={`/sites/${encodeURIComponent(siteId)}/design`}
          className="tap-target inline-flex items-center font-semibold text-accent-text hover:underline"
        >
          설계 기준면 올리기
        </Link>
      </p>
    );
  }
  return (
    <ul className="flex flex-col gap-2">
      {surfaces.map((surface) => (
        <li key={surface.designSurfaceId}>
          <Link
            href={`/sites/${encodeURIComponent(siteId)}/report?designSurfaceId=${encodeURIComponent(surface.designSurfaceId)}`}
            className="tap-target flex flex-col gap-1 rounded-lg border border-line bg-surface p-3 text-[12.5px] transition-colors hover:bg-sunk"
          >
            <span className="font-semibold break-keep text-accent-text">
              {surface.name} · {surface.revision}
            </span>
            <span className="text-[11.5px] break-keep text-ink-2">
              {DESIGN_SURFACE_STATUS_LABEL[surface.status].label} · {surface.verifiedAt ? `검증 ${formatKoreanDateTime(surface.verifiedAt, { dateStyle: "medium", timeStyle: "short" })}` : `등록 ${formatKoreanDateTime(surface.registeredAt, { dateStyle: "medium", timeStyle: "short" })}`}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

function ZoneProgressTable({ zones }: { zones: ZoneProgress[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] border-collapse text-[12.5px]">
        <thead>
          <tr className="border-b border-line-strong text-left text-ink-muted">
            <th className="py-1.5 pr-3 font-semibold">구역</th>
            <th className="py-1.5 pr-3 text-right font-semibold">계획 절토</th>
            <th className="py-1.5 pr-3 text-right font-semibold">완료 절토</th>
            <th className="py-1.5 pr-3 text-right font-semibold">잔여 절토</th>
            <th className="py-1.5 pr-3 text-right font-semibold">절토 진척률</th>
            <th className="py-1.5 pr-3 text-right font-semibold">계획 성토</th>
            <th className="py-1.5 pr-3 text-right font-semibold">완료 성토</th>
            <th className="py-1.5 pr-3 text-right font-semibold">잔여 성토</th>
            <th className="py-1.5 pr-3 text-right font-semibold">성토 진척률</th>
          </tr>
        </thead>
        <tbody>
          {zones.map((zone) => (
            <tr key={zone.zoneId} className="border-b border-line align-top">
              <td className="py-1.5 pr-3">
                <span className="font-semibold break-keep">{zone.zoneName ?? zone.zoneId}</span>
                <p className="mt-0.5 text-[11px] break-keep text-ink-muted">{zone.basis}</p>
              </td>
              <td className="num py-1.5 pr-3 text-right">{formatVolumeM3(zone.plannedCutM3)}</td>
              <td className="num py-1.5 pr-3 text-right">{formatNetVolumeM3(zone.doneCutM3)}</td>
              <td className="num py-1.5 pr-3 text-right">{formatVolumeM3(zone.remainingCutM3)}</td>
              <td className="num py-1.5 pr-3 text-right">{ratioLabel(zone.cutProgressRatio)}</td>
              <td className="num py-1.5 pr-3 text-right">{formatVolumeM3(zone.plannedFillM3)}</td>
              <td className="num py-1.5 pr-3 text-right">{formatNetVolumeM3(zone.doneFillM3)}</td>
              <td className="num py-1.5 pr-3 text-right">{formatVolumeM3(zone.remainingFillM3)}</td>
              <td className="num py-1.5 pr-3 text-right">{ratioLabel(zone.fillProgressRatio)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** 구역별 남은 물량(cut/fill/net) 표를 못 낼 때의 사유 — 침묵 생략 금지. */
function ConformanceOmittedNotice({
  conformance,
  latestDesignConformanceId,
}: {
  conformance: Exclude<ConformanceMatch, { kind: "matched" }>;
  latestDesignConformanceId: string;
}) {
  const message: Record<typeof conformance.kind, string> = {
    "no-mission":
      "이 진척이 속한 임무를 알 수 없어 구역별 남은 물량(절토·성토·순잔량) 표를 생략합니다.",
    "no-reports":
      "이 임무의 설계 대비 잔량 이력을 불러오지 못했거나 아직 계산된 리포트가 없어 구역별 남은 물량 표를 생략합니다.",
    "id-not-found":
      `이 진척이 참조하는 리포트(${latestDesignConformanceId})를 설계 대비 잔량 이력에서 찾지 못해 ` +
      "구역별 남은 물량 표를 생략합니다 — 위 구역 진척 표(계획·완료·잔여)는 이 문제와 무관하게 그대로입니다.",
  };
  return (
    <section className="flex flex-col gap-1 rounded-lg border border-line bg-surface p-4">
      <h3 className="text-[13px] font-bold tracking-tight break-keep text-ink-2">
        구역별 남은 물량
      </h3>
      <p className="text-[12.5px] break-keep text-ink-muted">{message[conformance.kind]}</p>
    </section>
  );
}

function ConformanceTable({
  conformance,
}: {
  conformance: Extract<ConformanceMatch, { kind: "matched" }>;
}) {
  const { report } = conformance.entry;
  return (
    <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-[13px] font-bold tracking-tight break-keep text-ink-2">
          구역별 남은 물량
        </h3>
        {conformance.totalNetM3 !== null && (
          <span className="num text-[13px]">
            전체 순 잔량 {formatNetVolumeM3(conformance.totalNetM3)}
          </span>
        )}
      </div>
      <p className="text-[12px] break-keep text-ink-2">
        {formatKoreanDateTime(report.computedAt)} 계산 · 좌표계 {report.crs} · 높이 기준{" "}
        {humanizeVerticalDatum(report.verticalReference.datum)}
      </p>
      {/* DesignConformancePanel.tsx 의 한계 문구를 문자 그대로 복제한다(ADR-KSI-016 D6) —
          정산·기성 근거가 아니라는 경고는 화면·종이 어디서든 같은 말이어야 한다. */}
      <p className="rounded-md border border-line bg-sunk px-2.5 py-2 text-[12px] break-keep text-ink-2">
        설계 기준면과 현재 지형이 <strong className="font-bold">같은 계열의 높이 기준</strong>
        일 때만 계산합니다 — 근거: {report.verticalReference.basis}. 이 값은 촬영·재구성
        결과에서 나온 <strong className="font-bold">현황 추정치</strong>이며, 검사점 검증이
        없어 정산·기성 근거로 쓸 수 없습니다.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[560px] border-collapse text-[12.5px]">
          <thead>
            <tr className="border-b border-line-strong text-left text-ink-muted">
              <th className="py-1.5 pr-3 font-semibold">구역</th>
              <th className="py-1.5 pr-3 text-right font-semibold">면적</th>
              <th className="py-1.5 pr-3 text-right font-semibold">더 깎아야 함</th>
              <th className="py-1.5 pr-3 text-right font-semibold">더 쌓아야 함</th>
              <th className="py-1.5 pr-3 text-right font-semibold">순 잔량(쌓기−깎기)</th>
            </tr>
          </thead>
          <tbody>
            {report.zones.map((zone) => (
              <tr key={zone.zoneId} className="border-b border-line">
                <td className="py-1.5 pr-3 font-semibold break-keep">{zone.zoneId}</td>
                <td className="num py-1.5 pr-3 text-right">
                  {zone.areaM2.toLocaleString("ko-KR", { maximumFractionDigits: 0 })} m²
                </td>
                <td className="num py-1.5 pr-3 text-right">{formatVolumeM3(zone.cutM3)}</td>
                <td className="num py-1.5 pr-3 text-right">{formatVolumeM3(zone.fillM3)}</td>
                <td className="num py-1.5 pr-3 text-right">{formatNetVolumeM3(zone.netM3)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {/* DesignConformancePanel.tsx 의 식별자 노출과 같은 자리 — 종이만 남아도
          "어느 설계면·어느 리포트로 낸 잔량인지" 되짚을 수 있어야 한다(계보). */}
      <dl className="grid grid-cols-1 gap-2 border-t border-line pt-3 text-[12px] sm:grid-cols-3">
        <div>
          <dt className="break-keep text-ink-muted">집계에서 뺀 높이차</dt>
          <dd className="num">{report.policy.volumeThresholdM} m 미만</dd>
        </div>
        <div>
          <dt className="break-keep text-ink-muted">기준으로 삼은 설계면</dt>
          <dd className="num break-token">{report.designSurfaceRef.designSurfaceId}</dd>
        </div>
        <div>
          <dt className="break-keep text-ink-muted">이 리포트</dt>
          <dd className="num break-token">{report.designConformanceId}</dd>
        </div>
      </dl>
    </section>
  );
}

export default async function SiteReportPage({
  params,
  searchParams,
}: {
  params: Promise<{ siteId: string }>;
  searchParams: Promise<{ designSurfaceId?: string }>;
}) {
  const { siteId } = await params;
  const { designSurfaceId } = await searchParams;

  let site;
  try {
    site = await getSite(siteId);
  } catch (error) {
    if (error instanceof CoreApiError && error.status === 404) notFound();
    const message =
      error instanceof CoreApiError
        ? humanizeApiError(error.code, error.status, error.serverMessage)
        : "요청을 처리하지 못했습니다.";
    return (
      <div className="flex flex-col gap-4 p-4 sm:p-5">
        <ErrorState message={message} />
      </div>
    );
  }

  const header = (
    <div className="flex flex-col gap-1">
      <Link
        href={`/sites/${encodeURIComponent(site.siteId)}`}
        className="print:hidden text-[12.5px] font-semibold break-keep text-accent-text hover:underline"
      >
        ← {site.name}
      </Link>
      <h2 className="break-keep text-[19px] font-bold tracking-tight">
        현장 보고서 — {site.name}
      </h2>
      <p className="max-w-2xl text-[12.5px] break-keep text-ink-2">
        계획 대비 진척과(있으면) 설계 대비 남은 물량을 인쇄·저장할 수 있는 형태로
        묶었습니다. 화면에 그려진 것과 같은 조회 결과를 그대로 옮긴 것이라 화면의
        표·지도와 다른 숫자가 나올 수 없습니다.
      </p>
    </div>
  );

  if (!designSurfaceId) {
    let surfaces: DesignSurface[] | null = null;
    try {
      surfaces = (await listDesignSurfaces(site.siteId)).surfaces;
    } catch {
      surfaces = null;
    }
    return (
      <div className="flex flex-col gap-5 p-4 sm:p-5">
        {header}
        {surfaces === null ? (
          <ErrorState
            message="설계 기준면 목록을 불러오지 못했습니다."
            detail="등록된 기준면이 없는 것으로 처리하지 않았습니다. 잠시 후 다시 확인하세요."
            retryable
          />
        ) : (
          <section className="print:hidden flex flex-col gap-3 rounded-lg border border-line bg-surface p-4">
            <h3 className="text-[13px] font-bold tracking-tight break-keep text-ink-2">
              어느 설계 기준면 보고서를 만들까요?
            </h3>
            <SurfacePicker siteId={site.siteId} surfaces={surfaces} />
          </section>
        )}
      </div>
    );
  }

  let progressResponse;
  try {
    progressResponse = await getDesignProgress(site.siteId, designSurfaceId);
  } catch (error) {
    const message =
      error instanceof CoreApiError
        ? humanizeApiError(error.code, error.status, error.serverMessage)
        : "요청을 처리하지 못했습니다.";
    return (
      <div className="flex flex-col gap-4 p-4 sm:p-5">
        {header}
        <ErrorState message={message} />
      </div>
    );
  }

  // 이 페이지가 문서를 조립한 서버 시각 — Core 계산 시각(baselineComputedAt/
  // latestComputedAt)과 절대 같은 문구로 섞지 않는다(둘은 다른 질문에 답한다).
  const renderedAt = new Date().toISOString();

  // conformanceList → 매칭 → jobArtifacts 순서로 순차 조회한다: jobId 는 매칭된
  // 리포트 안에만 있어(entry.report.current.jobId) 매칭 전에는 무엇을 조회할지
  // 알 수 없다. 매칭 자체는 순수 함수라 두 번 불러도(여기 한 번, 아래
  // collectSiteReportData 안에서 한 번) 비용이 없고 결과도 항상 같다.
  const latestMissionId = progressResponse.latestMissionId;
  const coveragePromise = progressResponse.progress && latestMissionId
    ? fetchCoverageEvidence(latestMissionId)
    : Promise.resolve<ReportCoverageEvidence>({
        status: "UNAVAILABLE",
        missionId: "",
        report: null,
        rejections: null,
        detail: "최신 임무 식별자가 없어 커버리지 근거를 결속할 수 없습니다.",
      });
  const conformanceList =
    progressResponse.progress && latestMissionId
      ? await fetchConformanceList(latestMissionId)
      : null;
  const preMatch = progressResponse.progress
    ? matchLatestConformanceReport(
        progressResponse.latestMissionId,
        progressResponse.progress.latestDesignConformanceId,
        conformanceList,
      )
    : null;
  const [jobArtifacts, coverage] = await Promise.all([
    preMatch?.kind === "matched"
      ? fetchJobArtifacts(preMatch.entry.report.current.jobId)
      : Promise.resolve(null),
    coveragePromise,
  ]);

  const data = collectSiteReportData(progressResponse, conformanceList, jobArtifacts);

  return (
    <div className="flex flex-col gap-5 p-4 sm:p-5">
      {header}

      {data.progress === null ? (
        <section className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-4">
          <p className="text-[12.5px] break-keep text-ink-2">
            {data.detail ?? "진척을 계산할 수 없습니다."}
          </p>
          <p className="text-[12.5px] break-keep text-ink-muted">
            원지형 기준 지정은 그 임무의 설계 대비 잔량 결과 화면에서{" "}
            <span className="font-semibold">&ldquo;이 리포트를 원지형 기준으로
            지정&rdquo;</span>
            버튼으로 합니다.
          </p>
        </section>
      ) : (
        <>
          <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h3 className="text-[13px] font-bold tracking-tight break-keep text-ink-2">
                구역별 진척
              </h3>
              <span className="text-[11.5px] break-keep text-ink-muted">
                문턱 {data.progress.thresholdM} m 미만 차이는 집계에서 뺐습니다
              </span>
            </div>
            {/* progress/page.tsx 의 문구를 문자 그대로 복제한다 — 계산 시각과 그 시각의
                한계를 화면·종이가 다른 말로 하면 안 된다. */}
            <p className="rounded-md border border-line bg-sunk px-2.5 py-2 text-[12px] break-keep text-ink-2">
              기준(원지형) {formatKoreanDateTime(data.progress.baselineComputedAt)} → 최신{" "}
              {formatKoreanDateTime(data.progress.latestComputedAt)}. 기준 시점이 이미 일부
              시공된 뒤였다면 계획이 실제보다 적게 잡힙니다 — 기준을 다시 확인하세요. 이
              진척은 정산·기성 근거가 아닙니다(설계면은 측정물이 아니라 검증된 오차한계가
              없습니다).
            </p>
            {/* Core 계산 시각과는 다른 시각이다 — 이 문서를 지금 조회해 조립한 시각. */}
            <p className="text-[11px] break-keep text-ink-muted">
              이 보고서는{" "}
              {formatKoreanDateTime(renderedAt, { dateStyle: "long", timeStyle: "medium" })}에
              조회한 값으로 조립됐습니다 — 위 계산 시각과는 다른 시각입니다. 다시 열면
              최신 값으로 갱신됩니다.
            </p>
            {data.unmatchedZoneIds.length > 0 && (
              <p className="text-[12px] break-keep text-ink-muted">
                이번 표에서 뺀 구역 {data.unmatchedZoneIds.length}건(기준 또는 최신 한쪽에만
                있었습니다): {data.unmatchedZoneIds.join(", ")}
              </p>
            )}
            {data.areaMismatchZoneIds.length > 0 && (
              <p className="text-[12px] break-keep text-ink-muted">
                이번 표에서 뺀 구역 {data.areaMismatchZoneIds.length}건(zoneId는 같지만 측정
                면적이 기준 시점과 크게 달라 같은 곳을 쟀다고 볼 수 없었습니다 — 즉석으로
                그린 구역이 매번 다른 범위였거나, 이번 비행에서 일부가 안 찍혔을 수
                있습니다): {data.areaMismatchZoneIds.join(", ")}
              </p>
            )}
            {/* 종이만 남아도 "이게 어느 설계면·어느 시점의 계산인지"를 되짚을 수
                있어야 한다(계보) — URL 은 인쇄물에 남지 않는다. */}
            <dl className="grid grid-cols-1 gap-2 border-t border-line pt-3 text-[12px] sm:grid-cols-3">
              <div>
                <dt className="break-keep text-ink-muted">기준으로 삼은 설계면</dt>
                <dd className="num break-token">{data.progress.designSurfaceId}</dd>
              </div>
              <div>
                <dt className="break-keep text-ink-muted">기준(원지형) 리포트</dt>
                <dd className="num break-token">{data.progress.baselineDesignConformanceId}</dd>
              </div>
              <div>
                <dt className="break-keep text-ink-muted">최신 리포트</dt>
                <dd className="num break-token">{data.progress.latestDesignConformanceId}</dd>
              </div>
            </dl>
            <ZoneProgressTable zones={data.progress.zones} />
          </section>

          <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4">
            <div>
              <h3 className="text-[13px] font-bold tracking-tight break-keep text-ink-2">
                관측 커버리지 근거
              </h3>
              <p className="mt-1 text-[11.5px] break-keep text-ink-muted">
                아래 비율은 기체 신고값이며, 서버 수용 여부·계획 대사·거부 이력을 함께
                표시합니다. 경로 완료만으로 현장 관측 완료를 주장하지 않습니다.
              </p>
            </div>
            {coverage.status === "UNAVAILABLE" ? (
              <>
                {coverage.report && (
                  <CoverageReportSection
                    result={{ kind: "reported", report: coverage.report }}
                    rejections={coverage.rejections}
                  />
                )}
                <ErrorState
                  message="커버리지 근거를 완전히 불러오지 못했습니다."
                  detail={coverage.detail}
                  retryable
                />
              </>
            ) : (
              <CoverageReportSection
                result={
                  coverage.status === "REPORTED"
                    ? { kind: "reported", report: coverage.report }
                    : { kind: "not-reported" }
                }
                rejections={coverage.rejections}
              />
            )}
          </section>

          {data.conformance.kind === "matched" ? (
            <ConformanceTable conformance={data.conformance} />
          ) : data.conformance.kind !== "no-progress" ? (
            <ConformanceOmittedNotice
              conformance={data.conformance}
              latestDesignConformanceId={data.progress.latestDesignConformanceId}
            />
          ) : null}

          {data.latestMissionId && (
            <DiffHeatmapOverlay
              missionId={data.latestMissionId}
              designConformanceId={data.progress.latestDesignConformanceId}
              thresholdM={data.progress.thresholdM}
            />
          )}

          {data.conformance.kind === "matched" &&
            (data.orthophotoArtifactId ? (
              <OrthophotoOverlay
                jobId={data.conformance.entry.report.current.jobId}
                artifactId={data.orthophotoArtifactId}
              />
            ) : (
              <section className="rounded-lg border border-line p-4">
                <h3 className="text-sm font-semibold">정사영상</h3>
                <p className="mt-1 text-sm break-keep text-ink-muted">
                  정사영상 없음 — 이 재구성 결과에 정사영상 산출물이 등록되지 않았습니다
                  (엔진이 만들지 않았거나 지상표본거리 미지정으로 건너뛰었을 수 있습니다).
                </p>
              </section>
            ))}

          <p className="text-[11.5px] break-keep text-ink-muted">
            지도는 참고용입니다 — 정확한 수치는 위 표를 따릅니다. 이 지도는 화면(진척·
            설계 대비 잔량 화면)과 같은 컴포넌트로 그려지므로 신뢰 수준 자체는 그
            화면과 같습니다(따로 다시 계산하지 않습니다).
          </p>

          <ReportExportControls
            progress={data.progress}
            fileNameBase={`report-${site.siteId}-${designSurfaceId}`}
            siteId={site.siteId}
            coverage={coverage}
          />
        </>
      )}
    </div>
  );
}
