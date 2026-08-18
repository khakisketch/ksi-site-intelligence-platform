import Link from "next/link";

import { CoreApiError } from "@/lib/core-api/client";
import { humanizeApiError } from "@/lib/core-api/labels";
import { listMissions } from "@/lib/core-api/missions";
import { hasAllPermissions } from "@/lib/core-api/permissions";
import { listSitesCached } from "@/lib/core-api/cached";
import type { MissionRecordResponse, SiteView } from "@/lib/core-api/types";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { TableRow, TableShell } from "@/components/ui/TableShell";
import { formatKoreanDateTime } from "@/lib/datetime";

import { formatCoverageRatio, formatNullable } from "./format";
import {
  ARTIFACT_KIND_LABEL,
  COMPLETION_STATE_LABEL,
  COVERAGE_NOT_REPORTED_LABEL,
  MISSION_TYPE_LABEL,
} from "./mission-labels";

type MissionsResult =
  | { missions: MissionRecordResponse[]; error: null }
  | { missions: null; error: CoreApiError };

// 고정폭 합(754) + 간격(60) + 좌우 여백(32) + 현장 열 최소폭(160) = 1006.
const COLUMNS = "146px minmax(160px,1fr) 116px 124px 132px 108px 128px";
const MIN_WIDTH = 1006;

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

/**
 * 임무(계약) 이력 — 카드 격자에서 표로(Console v2 §9).
 *
 * 이 화면은 "어느 임무가 어떻게 됐나"를 훑는 자리다. 카드는 한 건을 설명하기엔
 * 좋지만 여러 건을 견주기엔 값이 매번 다른 자리에 있어 나쁘다(현장 목록과 같은 이유).
 *
 * **'계획 커버리지'와 '비행 보고'를 절대 한 칸에 섞지 않는다.** 앞은 발급 시점의
 * 기하 추정치고 뒤는 비행 후 기체가 올린 실측 판정이다 — 둘을 같은 열에 두면 아직
 * 날지도 않은 임무가 "80% 완료"처럼 읽힌다(format.ts 의 같은 규율).
 *
 * UX 목표 §2 "임무 이력 조회" 예산=2클릭: 사이드 "임무" → 목록에서 항목 클릭.
 * siteId 쿼리 필터는 현장 상세가 `/missions?siteId=...` 로 걸 수 있어 실제로 반영한다.
 */
export default async function MissionsPage({
  searchParams,
}: {
  searchParams: Promise<{ siteId?: string }>;
}) {
  const { siteId } = await searchParams;
  const [{ missions, error }, siteNames, canPlanSurvey] = await Promise.all([
    fetchMissions(siteId),
    fetchSiteNames(),
    hasAllPermissions("MISSIONS_ISSUE"),
  ]);

  if (error) {
    return (
      <div className="flex flex-col gap-4 p-4 sm:p-5">
        <ErrorState
          message={humanizeApiError(error.code, error.status, error.serverMessage)}
          detail={error.serverMessage}
          retryAfterSeconds={error.retryAfterSeconds}
          retryable
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 p-4 sm:p-5">
      <div className="flex flex-wrap items-center gap-2">
        {/* 이 한 줄은 장식이 아니라 이 화면의 전제다 — 서버가 끊겨도 이미 발급된 계약은
            기체에서 그대로 유효하다(제품 제약: "Server loss must not invalidate a
            locally valid Mission Contract"). 목록을 못 불러온 날 운영자가 "임무가
            사라졌나"로 읽지 않게 항상 보인다. */}
        <p className="text-[12.5px] break-keep text-ink-2">
          발급된 계약은 서버 연결이 끊겨도 무효가 되지 않습니다.
        </p>

        {siteId && (
          <Link
            href="/missions"
            className="tap-target inline-flex items-center gap-1.5 rounded-md border border-line-strong bg-sunk px-2.5 text-[12.5px] break-keep"
          >
            현장 · {siteNames.get(siteId) ?? siteId}
            <span aria-hidden="true" className="text-ink-muted">
              ✕
            </span>
            <span className="sr-only">현장 필터 해제</span>
          </Link>
        )}

        {canPlanSurvey && siteId && (
          <Link
            href={`/sites/${encodeURIComponent(siteId)}/surveys/new`}
            className="btn btn-primary tap-target ml-auto"
          >
            새 조사 계획
          </Link>
        )}
      </div>

      {missions.length === 0 ? (
        <EmptyState
          title="발급된 임무가 없습니다"
          description={
            siteId
              ? "이 현장에는 아직 발급된 임무가 없습니다."
              : "현장에서 조사를 계획하면 발급된 계약이 여기에 쌓입니다."
          }
        />
      ) : (
        <TableShell title="임무 이력" meta={`${missions.length}건`}>
          <TableRow columns={COLUMNS} minWidth={MIN_WIDTH} head>
            <span>계약 ID</span>
            <span>현장</span>
            <span>유형</span>
            <span>비행 보고</span>
            <span>발급</span>
            <span className="text-right">계획 커버리지</span>
            <span>산출물</span>
          </TableRow>

          {missions.map((mission) => {
            // 서버가 이미 판정한 값이다(coverageCompletionState, CoverageReportStore 조회) —
            // 여기서 다시 계산하지 않는다.
            const coverage = mission.coverageCompletionState
              ? COMPLETION_STATE_LABEL[mission.coverageCompletionState]
              : COVERAGE_NOT_REPORTED_LABEL;

            return (
              <TableRow key={mission.missionId} columns={COLUMNS} minWidth={MIN_WIDTH}>
                <Link
                  href={`/missions/${encodeURIComponent(mission.missionId)}`}
                  className="num truncate text-[12px] font-semibold hover:underline"
                >
                  {mission.missionId}
                </Link>

                <Link
                  href={`/sites/${encodeURIComponent(mission.siteId)}`}
                  className="truncate text-[12.5px] hover:underline"
                >
                  {siteNames.get(mission.siteId) ?? mission.siteId}
                </Link>

                <span className="truncate text-[12.5px] break-keep">
                  {MISSION_TYPE_LABEL[mission.missionType]}
                </span>

                <span>
                  <StatusBadge label={coverage.label} tone={coverage.tone} />
                </span>

                <span className="num text-[11.5px] whitespace-nowrap text-ink-2">
                  {formatKoreanDateTime(mission.issuedAt, {
                    dateStyle: "medium",
                    timeStyle: "short",
                  })}
                </span>

                {/* 계획 추정치다 — 실측이 아니다. 열 이름에 '계획'을 박아 두는 이유. */}
                <span className="num text-right text-[12px] text-ink-2">
                  {formatCoverageRatio(mission.plannedCoverageRatio)}
                </span>

                <span className="truncate text-[11.5px] break-keep text-ink-2">
                  {ARTIFACT_KIND_LABEL[mission.artifactKind]}
                  {mission.waypointCount !== null && (
                    <span className="num"> · 웨이포인트 {formatNullable(mission.waypointCount)}</span>
                  )}
                </span>
              </TableRow>
            );
          })}
        </TableShell>
      )}
    </div>
  );
}
