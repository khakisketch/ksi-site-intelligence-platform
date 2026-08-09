import Link from "next/link";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { CoreApiError } from "@/lib/core-api/client";
import { humanizeApiError } from "@/lib/core-api/labels";
import { getCoverageReport, getMission } from "@/lib/core-api/missions";
import { getSite } from "@/lib/core-api/sites";
import { ErrorState } from "@/components/ui/ErrorState";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { KmzDownloadButton } from "@/components/missions/KmzDownloadButton";
import {
  CoverageReportSection,
  type CoverageReportResult,
} from "@/components/missions/CoverageReportSection";

import { formatCoverageRatio, formatDateTime, formatNullable } from "../format";
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
          <BackLink />
          <ErrorState message={humanizeApiError(error.code, error.status, error.serverMessage)} detail={error.serverMessage} />
        </div>
      );
    }
    throw error;
  }

  // 현장 이름은 부가 정보다 — 조회가 실패해도 임무 상세 자체는 보여야 하므로
  // 실패를 삼키고 raw siteId 로 내려간다.
  const [site, coverageResult] = await Promise.all([
    getSite(mission.siteId).catch(() => null),
    fetchCoverageResult(mission.missionId),
  ]);

  return (
    <div className="flex flex-col gap-4 p-4 sm:p-5">
      <BackLink />

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
            <KmzDownloadButton
              missionId={mission.missionId}
              hasKmz={mission.artifactKind === "pair"}
            />
          </div>
        </section>

        {/* 우: 사실 패널 */}
        <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4">
          <h3 className="text-[13px] font-bold tracking-tight break-keep text-ink-2">사실</h3>
          <dl className="divide-y divide-line border-t border-line">
            <FieldRow label="웨이포인트 수" value={<span className="num">{formatNullable(mission.waypointCount)}</span>} />
            <FieldRow label="계획 커버리지" value={<span className="num">{formatCoverageRatio(mission.plannedCoverageRatio)}</span>} />
            <FieldRow label="발급 일시" value={<span className="num">{formatDateTime(mission.issuedAt)}</span>} />
            <FieldRow label="발급자" value={mission.issuedBy} />
          </dl>
        </section>
      </div>

      {/* 비행 결과 — CoverageReport 의 존재와 서버 판정을 그대로 보여준다(INV-010).
          발급 메타(위)와 분리한다: 저건 "무엇을 지시했나", 이건 "실제로 무슨 일이
          있었나" — 계획 커버리지(위 "계획 커버리지" 필드)와 절대 나란히 두지 않는다. */}
      <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4">
        <h3 className="text-[13px] font-bold tracking-tight break-keep text-ink-2">비행 결과</h3>
        <CoverageReportSection result={coverageResult} />
      </section>
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

function BackLink() {
  return (
    <Link
      href="/missions"
      className="tap-target inline-flex w-fit items-center text-sm break-keep text-ink-2 underline decoration-line-strong underline-offset-2 hover:text-ink-1"
    >
      ← 임무 목록으로
    </Link>
  );
}
