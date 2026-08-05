import type { ReactNode } from "react";

import Link from "next/link";

import { CoreApiError } from "@/lib/core-api/client";
import { humanizeApiError } from "@/lib/core-api/labels";
import { listMissions } from "@/lib/core-api/missions";
import { listSitesCached } from "@/lib/core-api/cached";
import type { MissionRecordResponse, SiteView } from "@/lib/core-api/types";
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

// 현장 이름 조회는 부가 정보다 — 실패해도 임무 목록 자체는 보여야 하므로 실패를
// 삼키고 빈 맵(=raw siteId 로 표시)으로 내려간다.
async function fetchSiteNames(): Promise<Map<string, string>> {
  try {
    const sites = await listSitesCached();
    return new Map(sites.map((site: SiteView) => [site.siteId, site.name]));
  } catch {
    return new Map();
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
  const [{ missions, error }, siteNames] = await Promise.all([
    fetchMissions(siteId),
    fetchSiteNames(),
  ]);

  if (error) {
    return (
      <div className="flex flex-col gap-4 p-4 sm:p-5">
        <ErrorState message={humanizeApiError(error.code, error.status, error.serverMessage)} detail={error.serverMessage} />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 p-4 sm:p-5">
      {siteId && (
        <Link
          href="/missions"
          className="tap-target inline-flex w-fit items-center text-[13px] break-keep text-ink-2 underline decoration-line-strong underline-offset-2 hover:text-ink-1"
        >
          현장 필터 해제 ({siteNames.get(siteId) ?? siteId})
        </Link>
      )}

      {missions.length === 0 ? (
        <EmptyState title="발급된 임무가 없습니다" />
      ) : (
        <ul className="grid grid-cols-1 gap-3 lg:grid-cols-2 xl:grid-cols-3">
          {missions.map((mission) => (
            <MissionCard key={mission.missionId} mission={mission} siteName={siteNames.get(mission.siteId)} />
          ))}
        </ul>
      )}
    </div>
  );
}

function Fact({ label, value, numeric }: { label: string; value: ReactNode; numeric?: boolean }) {
  return (
    <span className="flex flex-col gap-px">
      <span className="text-[10.5px] break-keep text-ink-muted">{label}</span>
      <span className={`text-[13px] font-semibold break-keep ${numeric ? "num" : ""}`}>{value}</span>
    </span>
  );
}

// 목록 행의 주인공은 missionId(장치스러운 ID)가 아니라 "무슨 임무가 어느 현장에
// 발급됐는가"다 — missionId 는 부제로 내린다(시안 원칙, 이벤트 목록과 동일 기준).
function MissionCard({ mission, siteName }: { mission: MissionRecordResponse; siteName: string | undefined }) {
  return (
    <li>
      <Link
        href={`/missions/${encodeURIComponent(mission.missionId)}`}
        className="flex h-full flex-col gap-2.5 rounded-lg border border-line bg-surface p-4 transition-colors hover:border-line-strong hover:bg-sunk"
      >
        <div className="flex flex-wrap items-start justify-between gap-2">
          <span className="min-w-0">
            <span className="block text-[14.5px] font-bold tracking-tight break-keep">
              {MISSION_TYPE_LABEL[mission.missionType]} · {siteName ?? mission.siteId}
            </span>
            <span className="num mt-0.5 block text-[11.5px] break-token text-ink-muted">
              {mission.missionId}
            </span>
          </span>
          {mission.routePattern && (
            <StatusBadge label={ROUTE_PATTERN_LABEL[mission.routePattern]} tone="neutral" />
          )}
        </div>

        <div className="mt-auto flex flex-wrap gap-x-4 gap-y-2 border-t border-line pt-2.5">
          <Fact label="웨이포인트" value={formatNullable(mission.waypointCount)} numeric />
          <Fact label="계획 커버리지" value={formatCoverageRatio(mission.plannedCoverageRatio)} numeric />
          <Fact label="발급 일시" value={formatDateTime(mission.issuedAt)} numeric />
          <Fact label="발급자" value={mission.issuedBy} />
        </div>
      </Link>
    </li>
  );
}
