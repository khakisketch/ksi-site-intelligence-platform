import Link from "next/link";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { whoAmI } from "@/lib/core-api/auth";
import { CoreApiError } from "@/lib/core-api/client";
import { humanizeApiError } from "@/lib/core-api/labels";
import {
  getComparisonPolicy,
  listComparisonRequests,
  listSiteProcessingJobs,
} from "@/lib/core-api/comparison";
import {
  getDesignConformance,
  listDesignConformanceRequests,
  listDesignSurfaces,
} from "@/lib/core-api/design";
import {
  getCoverageReport,
  getCoverageRejections,
  getMission,
  getMissionExecution,
} from "@/lib/core-api/missions";
import type { CoverageRejectionListView } from "@/lib/core-api/types";
import { getChangeDetection, getVolumeChanges } from "@/lib/core-api/phase34";
import { listProcessingJobs } from "@/lib/core-api/processing-jobs";
import { getSourceMediaBundle } from "@/lib/core-api/source-media";
import { getSite } from "@/lib/core-api/sites";
import { listWorkAreas } from "@/lib/core-api/workAreas";
import { ErrorState } from "@/components/ui/ErrorState";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { ComparisonSubmitPanel } from "@/components/missions/ComparisonSubmitPanel";
import { DesignConformancePanel } from "@/components/design/DesignConformancePanel";
import { KmzDownloadButton } from "@/components/missions/KmzDownloadButton";
import { SourceUploadPanel } from "@/components/missions/SourceUploadPanel";
import { MissionLifecycle } from "@/components/missions/MissionLifecycle";
import { ResponsiveActionBoundary } from "@/components/responsive/ResponsiveActionBoundary";
import {
  CoverageReportSection,
  type CoverageReportResult,
} from "@/components/missions/CoverageReportSection";
import { formatKoreanDateTime } from "@/lib/datetime";

import { formatCoverageRatio, formatNullable } from "../format";
import { ARTIFACT_KIND_LABEL, MISSION_TYPE_LABEL, ROUTE_PATTERN_LABEL } from "../mission-labels";

// 커버리지 보고 조회 실패를 상세 화면 전체가 아니라 이 섹션 하나로 국소화한다 —
// 임무 발급 메타(좌 패널)는 커버리지 서브시스템이 죽어도 보여야 한다(getSite 와
// 같은 원칙, "부가 정보 실패가 본문을 끌고 내려가지 않는다").
async function fetchCoverageResult(missionId: string): Promise<CoverageReportResult> {
  try {
    return { kind: "reported", report: await getCoverageReport(missionId) };
  } catch (error) {
    if (error instanceof CoreApiError) {
      if (error.status === 404) return { kind: "not-reported" };
      return { kind: "error", error };
    }
    throw error;
  }
}

/**
 * 거부 이력은 항상 부가 정보다 — 조회 실패해도 "비행 결과" 섹션 자체는 보여야
 * 한다(fetchCoverageResult 와 같은 원칙). rejectionCount=0 도 유효한 성공 응답이라
 * catch 블록이 아니라 null 로만 실패를 표시한다.
 */
async function fetchCoverageRejections(missionId: string): Promise<CoverageRejectionListView | null> {
  try {
    return await getCoverageRejections(missionId);
  } catch {
    return null;
  }
}

/**
 * /reports 가 실제로 내용을 보여줄지 — change-detection·volume-change 둘 다
 * 두 시점 비교 제출(별도 스텝, M2 영역)이 있어야 채워진다. 404 는 "아직 없음"
 * 이지 오류가 아니다(reports/page.tsx 의 fetchChange/fetchVolume 과 같은 규약).
 * 이 판정을 다시 계산하지 않고 그대로 재사용한다 — 규칙이 두 곳에 생기면 갈린다.
 */
async function hasComparisonReport(missionId: string): Promise<boolean> {
  const [change, volume] = await Promise.all([
    getChangeDetection(missionId)
      .then(() => true)
      .catch(() => false),
    getVolumeChanges(missionId)
      .then((v) => v.reports.length > 0)
      .catch(() => false),
  ]);
  return change || volume;
}

export default async function MissionDetailPage({
  params,
}: {
  params: Promise<{ missionId: string }>;
}) {
  const { missionId } = await params;

  let mission;
  try {
    mission = await getMission(missionId);
  } catch (error) {
    if (error instanceof CoreApiError) {
      if (error.status === 404) notFound();
      return (
        <div className="flex flex-col gap-4 p-4 sm:p-5">
          <ErrorState message={humanizeApiError(error.code, error.status, error.serverMessage)} detail={error.serverMessage} />
        </div>
      );
    }
    throw error;
  }

  // 현장 이름·업로드 패널 초기 상태는 전부 부가 정보다 — 하나가 실패해도
  // 임무 상세 자체(좌 패널)는 보여야 한다(getSite 와 같은 원칙).
  const [
    site,
    execution,
    coverageResult,
    rejectionsResult,
    canIssue,
    sourceBundle,
    jobs,
    hasComparison,
    siteJobs,
    comparisonPolicy,
    latestComparison,
    designSurfaces,
    latestDesignRequest,
    designConformance,
    workAreas,
  ] = await Promise.all([
    getSite(mission.siteId).catch(() => null),
    // 실행 상태 표면이 없는 조립이거나 조회에 실패하면 null 로 둔다 — 화면은 그때
    // 아무것도 단정하지 않는다(MissionLifecycle 의 execution === null 경로).
    getMissionExecution(mission.missionId).catch(() => null),
    fetchCoverageResult(mission.missionId),
    fetchCoverageRejections(mission.missionId),
    whoAmI()
      .then((who) => who.permissions.includes("MISSIONS_ISSUE"))
      .catch(() => false),
    // 404(등록된 적 없음)와 그 외 조회 실패를 동일하게 "아직 없음"으로 다룬다 —
    // 이 패널의 시작 상태는 어차피 업로드 UI를 그대로 보여주므로 구분할 필요가 없다.
    getSourceMediaBundle(mission.missionId).catch(() => null),
    listProcessingJobs(mission.missionId)
      .then((r) => r.jobs)
      .catch(() => []),
    hasComparisonReport(mission.missionId),
    // 비교 후보는 **임무가 아니라 현장** 단위다 — 다른 시점(다른 임무)의 재구성과
    // 비교하는 것이 이 기능의 전부다. 실패해도 이 패널만 비운다(다른 섹션과 동일 원칙).
    listSiteProcessingJobs(mission.siteId)
      .then((r) => r.jobs)
      .catch(() => []),
    // 기준값은 화면이 지어내지 않는다 — 못 받으면 null 로 두고 그 사실을 화면이 밝힌다.
    getComparisonPolicy().catch(() => null),
    listComparisonRequests(mission.missionId)
      .then((r) => r.requests[0] ?? null)
      .catch(() => null),
    // 설계 대비 잔량(M4-A) — 셋 다 부가 정보다. 조회가 실패하거나 아직 없으면
    // (리포트는 404 가 "아직 계산 안 됨"이다) 그 패널만 비운다.
    listDesignSurfaces(mission.siteId)
      .then((r) => r.surfaces)
      .catch(() => []),
    listDesignConformanceRequests(mission.missionId)
      .then((r) => r.requests[0] ?? null)
      .catch(() => null),
    getDesignConformance(mission.missionId).catch(() => null),
    // 작업구역(M4-C) — 현장 단위 자산이라 comparison siteJobs 와 같은 사유로
    // missionId 가 아니라 siteId 로 조회한다. 실패해도 이 패널은 즉석 그리기로
    // 대체된다(work-area 목록이 부가 정보라는 원칙 그대로).
    listWorkAreas(mission.siteId)
      .then((r) => r.workAreas)
      .catch(() => []),
  ]);
  // 최신 발급분 — 발급 순서가 곧 배열 순서라는 서버 계약은 없으므로 issuedAt 로 정렬한다.
  const latestJob = [...jobs].sort((a, b) => b.issuedAt.localeCompare(a.issuedAt))[0] ?? null;

  return (
    <div className="flex flex-col gap-4 p-4 sm:p-5">
      <div className="flex flex-col gap-4 lg:grid lg:grid-cols-2 lg:items-start lg:gap-5">
        {/* 좌: 요약 + 계약 정보 */}
        <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4">
          <div>
            <p className="num text-[11px] font-bold break-token tracking-wide text-ink-muted uppercase">
              {mission.missionId}
            </p>
            <h2 className="text-[17px] font-bold tracking-tight break-keep">
              {MISSION_TYPE_LABEL[mission.missionType]}
            </h2>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <StatusBadge label={ARTIFACT_KIND_LABEL[mission.artifactKind]} tone="neutral" />
            {mission.routePattern && (
              <StatusBadge label={ROUTE_PATTERN_LABEL[mission.routePattern]} tone="neutral" />
            )}
          </div>
          <dl className="divide-y divide-line border-t border-line">
            <FieldRow
              label="현장"
              value={
                <Link
                  href={`/sites/${encodeURIComponent(mission.siteId)}`}
                  className="break-keep underline decoration-line-strong underline-offset-2 hover:text-ink-1"
                >
                  {site ? site.name : mission.siteId}
                </Link>
              }
            />
            <FieldRow
              label="KMZ SHA-256"
              value={
                mission.kmzSha256 ? (
                  <span className="num text-xs break-token">{mission.kmzSha256}</span>
                ) : (
                  "—"
                )
              }
            />
          </dl>
          <div className="pt-1">
            <ResponsiveActionBoundary
              action="RECOVERY_ACTION"
              reason="KMZ 다운로드는 노트북의 전문가 복구 작업에서 수행합니다."
            >
              <KmzDownloadButton
                missionId={mission.missionId}
                hasKmz={mission.artifactKind === "pair"}
              />
            </ResponsiveActionBoundary>
          </div>
        </section>

        {/* 우: 사실 패널 */}
        <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4">
          <h3 className="text-[13px] font-bold tracking-tight break-keep text-ink-2">사실</h3>
          <dl className="divide-y divide-line border-t border-line">
            <FieldRow label="웨이포인트 수" value={<span className="num">{formatNullable(mission.waypointCount)}</span>} />
            <FieldRow label="계획 커버리지" value={<span className="num">{formatCoverageRatio(mission.plannedCoverageRatio)}</span>} />
            <FieldRow
              label="발급 일시"
              value={
                <span className="num">
                  {formatKoreanDateTime(mission.issuedAt, { dateStyle: "medium", timeStyle: "short" })}
                </span>
              }
            />
            <FieldRow label="발급자" value={mission.issuedBy} />
          </dl>
        </section>
      </div>

      <MissionLifecycle
        execution={execution}
        coverage={coverageResult}
        bundle={sourceBundle}
        latestJob={latestJob}
        hasComparisonReport={hasComparison}
      />

      {/* 비행 결과 — CoverageReport 의 존재와 서버 판정을 그대로 보여준다(INV-010).
          발급 메타(위)와 분리한다: 저건 "무엇을 지시했나", 이건 "실제로 무슨 일이
          있었나" — 계획 커버리지(위 "계획 커버리지" 필드)와 절대 나란히 두지 않는다. */}
      <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4">
        <h3 className="text-[13px] font-bold tracking-tight break-keep text-ink-2">비행 결과</h3>
        <CoverageReportSection result={coverageResult} rejections={rejectionsResult} />
      </section>

      <ResponsiveActionBoundary
        action="SOURCE_MEDIA_MUTATION"
        reason="원본 업로드·봉인과 처리 시작은 노트북의 전체 Operations Console에서 수행합니다."
      >
        <SourceUploadPanel
          missionId={mission.missionId}
          canIssue={canIssue}
          initialBundle={sourceBundle}
          initialJob={latestJob ? { jobId: latestJob.jobId, status: latestJob.status } : null}
          hasComparisonReport={hasComparison}
        />
      </ResponsiveActionBoundary>

      <ComparisonSubmitPanel
        missionId={mission.missionId}
        canIssue={canIssue}
        siteJobs={siteJobs}
        siteAoi={site?.aoi?.vertices ?? null}
        policy={comparisonPolicy}
        initialRequest={latestComparison}
      />

      <DesignConformancePanel
        missionId={mission.missionId}
        siteId={mission.siteId}
        canIssue={canIssue}
        surfaces={designSurfaces}
        siteJobs={siteJobs}
        siteAoi={site?.aoi?.vertices ?? null}
        workAreas={workAreas}
        initialRequest={latestDesignRequest}
        initialReport={designConformance?.reports[0] ?? null}
        initialTotalNetM3={designConformance?.latestTotalNetM3 ?? null}
      />
    </div>
  );
}

function FieldRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex flex-col gap-1 py-3 sm:flex-row sm:items-baseline sm:gap-4">
      <dt className="shrink-0 text-sm break-keep text-ink-muted sm:w-32">{label}</dt>
      <dd className="min-w-0 text-sm break-keep">{value}</dd>
    </div>
  );
}
