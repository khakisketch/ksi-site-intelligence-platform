import Link from "next/link";
import { notFound } from "next/navigation";

import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { StateBadge } from "@/components/ui/StatusBadge";
import { CoreApiError } from "@/lib/core-api/client";
import { formatKoreanDateTime } from "@/lib/datetime";
import { MISSION_TYPE_LABEL, humanizeApiError } from "@/lib/core-api/labels";
import { listMissions } from "@/lib/core-api/missions";
import { listRegionExtraction } from "@/lib/core-api/region-extraction";
import { getSite } from "@/lib/core-api/sites";
import type { MissionRecordResponse } from "@/lib/core-api/types";

import { ChangeRegionExplorer } from "./ChangeRegionExplorer";

/**
 * 변화 영역 · 재확인 필요 (M4-E 화면화) — "지난 현장 → 현재 현장 → 변화 영역 →
 * 재확인 필요 → 다음 비행" 흐름 중 마지막 세 단계를 한 화면에서 잇는다.
 *
 * 계산은 임무 단위다(설계 대비 잔량 리포트 하나에서 뽑은 값) — 그래서 이 화면도
 * 임무를 먼저 고른다(`/reports` 의 임무 선택 패턴과 동일). Core 쪽에는 새로 만든
 * 것이 없다 — 이미 있는 조회 3개(변화 영역 목록·상세, 재관찰 초안)를 그대로
 * 옮긴다.
 */
export default async function SiteChangesPage({
  params,
  searchParams,
}: {
  params: Promise<{ siteId: string }>;
  searchParams: Promise<{ missionId?: string }>;
}) {
  const { siteId } = await params;
  const { missionId } = await searchParams;

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
        className="text-[12.5px] font-semibold break-keep text-accent-text hover:underline"
      >
        ← {site.name}
      </Link>
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="break-keep text-[19px] font-bold tracking-tight">변화 영역 · 재확인 필요</h2>
        {/* region-extraction-scope-clarity(2026-08-15): 설계 대비 잔량 화면에서
            구역을 나눠 계산했더라도 이 화면은 그 구역과 무관하게 항상 현장
            전체를 훑는다 — 배지 하나로 짧게 대비되게 밝힌다. */}
        <StateBadge label="현장 전체 기준" tone="neutral" />
      </div>
      <p className="max-w-2xl text-[12.5px] break-keep text-ink-2">
        설계 대비 잔량이 크게 달라진 곳을 자동으로 묶어 보여줍니다. 영역을 골라 다음 비행의
        촬영 범위로 바로 넘길 수 있습니다.
      </p>
    </div>
  );

  if (!missionId) {
    const missions = await listMissions(site.siteId).catch(() => [] as MissionRecordResponse[]);
    return (
      <div className="flex flex-col gap-5 p-4 sm:p-5">
        {header}
        <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4">
          <h3 className="text-[13px] font-bold tracking-tight break-keep text-ink-2">
            어느 임무의 변화 영역을 볼까요?
          </h3>
          {missions.length === 0 ? (
            <EmptyState
              title="발급된 임무가 없습니다"
              description="변화 영역은 설계 대비 잔량이 계산된 임무에서만 볼 수 있습니다."
            />
          ) : (
            <ul className="flex flex-col gap-2">
              {missions.map((mission) => (
                <li key={mission.missionId}>
                  <Link
                    href={`/sites/${encodeURIComponent(site.siteId)}/changes?missionId=${encodeURIComponent(mission.missionId)}`}
                    className="tap-target flex flex-col gap-1 rounded-lg border border-line bg-surface p-3 text-[12.5px] transition-colors hover:bg-sunk"
                  >
                    <span className="font-semibold break-keep text-accent-text">
                      {MISSION_TYPE_LABEL[mission.missionType]}
                    </span>
                    <span className="text-[11.5px] break-keep text-ink-2">
                      발급{" "}
                      {formatKoreanDateTime(mission.issuedAt, {
                        dateStyle: "medium",
                        timeStyle: "short",
                      })}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    );
  }

  let regionExtraction;
  try {
    regionExtraction = await listRegionExtraction(missionId);
  } catch (error) {
    if (error instanceof CoreApiError && error.status === 404) {
      return (
        <div className="flex flex-col gap-5 p-4 sm:p-5">
          {header}
          <EmptyState
            title="이 임무는 아직 계산된 변화 영역이 없습니다"
            description="설계 대비 잔량이 기록된 뒤에 변화 영역 추출을 요청해야 이 화면에 나타납니다."
            action={{
              label: "다른 임무 고르기",
              href: `/sites/${encodeURIComponent(site.siteId)}/changes`,
            }}
          />
        </div>
      );
    }
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

  const latest = regionExtraction.reports[0];
  const siteAoiVertices = site.aoi ? site.aoi.vertices : [];

  return (
    <div className="flex flex-col gap-5 p-4 sm:p-5">
      {header}
      <Link
        href={`/missions/${encodeURIComponent(missionId)}`}
        className="w-fit text-[12.5px] font-semibold break-keep text-accent-text hover:underline"
      >
        ← 이 계산의 근거가 된 설계 대비 잔량 보기
      </Link>
      {latest.report.regions.length === 0 ? (
        <EmptyState
          title="이번 계산에서는 변화 영역이 없었습니다"
          description={`기준 문턱 ${latest.report.thresholdM} m 이상 달라진 곳이 없어 재확인이 필요한 영역이 없습니다.`}
        />
      ) : (
        <ChangeRegionExplorer
          siteId={site.siteId}
          missionId={missionId}
          siteAoi={siteAoiVertices}
          report={latest.report}
        />
      )}
    </div>
  );
}
