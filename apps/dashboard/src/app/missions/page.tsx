import Link from "next/link";

import { CoreApiError } from "@/lib/core-api/client";
import { humanizeApiError } from "@/lib/core-api/labels";
import { listMissions } from "@/lib/core-api/missions";
import type { MissionRecordResponse } from "@/lib/core-api/types";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { StatusBadge } from "@/components/ui/StatusBadge";

import { formatCoverageRatio, formatDateTime, formatNullable } from "./format";
import { MISSION_TYPE_LABEL, ROUTE_PATTERN_LABEL } from "./mission-labels";

type MissionsResult =
  | { missions: MissionRecordResponse[]; error: null }
  | { missions: null; error: CoreApiError };

// JSX 를 try/catch 안에서 만들지 않는다(react-hooks/error-boundaries) — fetch 만 try/catch 로
// 감싸고, 렌더링은 그 결과를 받아 이 함수 밖에서 분기한다.
async function fetchMissions(siteId: string | undefined): Promise<MissionsResult> {
  try {
    return { missions: await listMissions(siteId), error: null };
  } catch (error) {
    if (error instanceof CoreApiError) {
      return { missions: null, error };
    }
    throw error;
  }
}

// UX 목표 §2 "임무 이력 조회" 예산=2클릭: 사이드 "임무" → 목록에서 항목 클릭.
// siteId 쿼리 필터는 현장 상세 화면이 `/missions?siteId=...` 로 걸 수 있어 실제로 반영한다.
export default async function MissionsPage({
  searchParams,
}: {
  searchParams: Promise<{ siteId?: string }>;
}) {
  const { siteId } = await searchParams;
  const { missions, error } = await fetchMissions(siteId);

  if (error) {
    return (
      <div className="flex flex-col gap-4 p-4 sm:p-6 lg:p-8">
        <h1 className="text-lg font-semibold break-keep">임무</h1>
        <ErrorState message={humanizeApiError(error.code, error.status, error.serverMessage)} detail={error.serverMessage} />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 p-4 sm:p-6 lg:p-8">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-lg font-semibold break-keep">임무</h1>
        {siteId && (
          <Link
            href="/missions"
            className="text-foreground/60 hover:text-foreground min-h-11 text-sm break-keep underline decoration-foreground/30 underline-offset-2"
          >
            현장 필터 해제 ({siteId})
          </Link>
        )}
      </div>

      {missions.length === 0 ? (
        <EmptyState title="발급된 임무가 없습니다" />
      ) : (
        <ul className="flex flex-col gap-2">
          {missions.map((mission) => (
            <li
              key={mission.missionId}
              className="relative flex flex-col gap-3 rounded-lg border border-black/10 p-4 transition-colors hover:bg-foreground/5 dark:border-white/10"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-mono text-sm font-medium break-keep">
                  {mission.missionId}
                </span>
                <StatusBadge label={MISSION_TYPE_LABEL[mission.missionType]} tone="neutral" />
              </div>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-4">
                <div>
                  <dt className="text-foreground/60 break-keep">현장</dt>
                  <dd className="break-keep">
                    <Link
                      href={`/sites/${encodeURIComponent(mission.siteId)}`}
                      className="relative z-10 underline decoration-foreground/30 underline-offset-2 hover:decoration-foreground"
                    >
                      {mission.siteId}
                    </Link>
                  </dd>
                </div>
                <div>
                  <dt className="text-foreground/60 break-keep">경로 패턴</dt>
                  <dd className="break-keep">
                    {mission.routePattern ? ROUTE_PATTERN_LABEL[mission.routePattern] : "—"}
                  </dd>
                </div>
                <div>
                  <dt className="text-foreground/60 break-keep">웨이포인트</dt>
                  <dd>{formatNullable(mission.waypointCount)}</dd>
                </div>
                <div>
                  <dt className="text-foreground/60 break-keep">커버리지</dt>
                  <dd>{formatCoverageRatio(mission.coverageRatio)}</dd>
                </div>
                <div>
                  <dt className="text-foreground/60 break-keep">발급 일시</dt>
                  <dd className="break-keep">{formatDateTime(mission.issuedAt)}</dd>
                </div>
                <div>
                  <dt className="text-foreground/60 break-keep">발급자</dt>
                  <dd className="break-keep">{mission.issuedBy}</dd>
                </div>
              </dl>
              <Link
                href={`/missions/${encodeURIComponent(mission.missionId)}`}
                className="absolute inset-0 z-0 min-h-11 rounded-lg"
                aria-label={`임무 ${mission.missionId} 상세 보기`}
              />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
