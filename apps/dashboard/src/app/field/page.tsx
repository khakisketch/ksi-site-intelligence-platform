import Link from "next/link";

import { CoreApiError } from "@/lib/core-api/client";
import { humanizeApiError, MISSION_TYPE_LABEL } from "@/lib/core-api/labels";
import { listMissions } from "@/lib/core-api/missions";
import { listSitesCached } from "@/lib/core-api/cached";
import type { MissionRecordResponse, SiteView } from "@/lib/core-api/types";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { formatKoreanDateTime } from "@/lib/datetime";

import { COMPLETION_STATE_LABEL, COVERAGE_NOT_REPORTED_LABEL } from "../missions/mission-labels";
import { FieldBlocked, FieldHeader, FieldInlineLogin } from "./FieldShell";
import { PilotBridgeProbe } from "./PilotBridgeProbe";
import { groupFieldMissions } from "./field-stages";
import { resolveFieldSession } from "./resolve-session";

// 현장 진입점 — 조종기에서 여는 첫 화면.
//
// **신규 서버 API 0건**(ADR-KSI-017 결과 조항). 여기 쓰이는 조회는 전부 임무 목록
// 화면이 이미 쓰던 것이다. 현장 화면이 필요로 한 것은 새 데이터가 아니라 **다른
// 배치와 다른 터치 치수**였다.
//
// 앱 셸을 벗는다(isChromelessPath) — 사유는 chromeless-path.ts 주석.

export const metadata = { title: "현장 · KSI" };

type MissionsResult =
  | { missions: MissionRecordResponse[]; error: null }
  | { missions: null; error: CoreApiError };

// JSX 를 try/catch 안에서 만들지 않는다 — 조회만 감싸고 렌더는 밖에서 분기한다
// (missions/page.tsx 와 같은 관습).
async function fetchMissions(): Promise<MissionsResult> {
  try {
    return { missions: await listMissions(), error: null };
  } catch (error) {
    if (error instanceof CoreApiError) return { missions: null, error };
    throw error;
  }
}

// 현장 이름은 부가 정보다 — 실패해도 목록 자체는 보여야 한다(raw siteId 로 떨어진다).
async function fetchSiteNames(): Promise<Map<string, string>> {
  try {
    const sites = await listSitesCached();
    return new Map(sites.map((site: SiteView) => [site.siteId, site.name]));
  } catch {
    return new Map();
  }
}

export default async function FieldMissionListPage() {
  const session = await resolveFieldSession();
  if (session.kind === "blocked") {
    return session.verdict.kind === "login" ? (
      <FieldInlineLogin next="/field" notice={session.verdict.notice} />
    ) : (
      <FieldBlocked message={session.verdict.message} retryHref="/field" />
    );
  }

  const [{ missions, error }, siteNames] = await Promise.all([fetchMissions(), fetchSiteNames()]);

  return (
    // field-controls — 재사용 컴포넌트(ErrorState 의 재시도 버튼 등)의 치수를 현장
    // 기준으로 올린다(globals.css 의 같은 이름 규칙 주석).
    <div className="field-controls flex flex-col">
      <FieldHeader principal={session.principal}>
        <h1 className="text-[17px] font-bold tracking-tight break-keep">오늘 임무</h1>
      </FieldHeader>

      <div className="flex flex-col gap-4 p-4">
        {error ? (
          <ErrorState
            message={humanizeApiError(error.code, error.status, error.serverMessage)}
            detail={error.serverMessage}
            retryable
          />
        ) : (
          <MissionGroups missions={missions} siteNames={siteNames} />
        )}

        <PilotBridgeProbe />
      </div>
    </div>
  );
}

function MissionGroups({
  missions,
  siteNames,
}: {
  missions: MissionRecordResponse[];
  siteNames: Map<string, string>;
}) {
  // "오늘"의 기준 시각은 서버가 이 요청을 처리하는 순간이다. 서울 달력 날짜로
  // 환산하는 것은 groupFieldMissions 가 한다(현장은 한국, 서버는 어디든).
  const { today, earlier, hiddenCount } = groupFieldMissions(missions, new Date().toISOString());

  if (today.length === 0 && earlier.length === 0) {
    return (
      <EmptyState
        title="발급된 임무가 없습니다"
        description="임무는 사무실에서 발급합니다 — 이 화면은 발급된 임무를 현장에서 수행하기 위한 화면입니다."
      />
    );
  }

  return (
    <div className="flex flex-col gap-5">
      <section className="flex flex-col gap-2">
        <h2 className="text-[13px] font-bold tracking-tight break-keep text-ink-2">
          오늘 발급됨 <span className="num">{today.length}</span>건
        </h2>
        {today.length === 0 ? (
          // 빈 목록을 조용히 숨기지 않는다 — "오늘 발급이 없다"는 것 자체가 현장에서
          // 확인해야 할 사실이다(전날 발급분으로 비행하는 날이 흔하다).
          <p className="rounded-lg border border-dashed border-line-strong bg-surface px-4 py-3 text-[13px] break-keep text-ink-2">
            오늘 발급된 임무가 없습니다. 아래에서 최근 발급분을 확인하세요.
          </p>
        ) : (
          <ul className="flex flex-col gap-2">
            {today.map((mission) => (
              <li key={mission.missionId}>
                <FieldMissionCard mission={mission} siteName={siteNames.get(mission.siteId)} />
              </li>
            ))}
          </ul>
        )}
      </section>

      {earlier.length > 0 && (
        <section className="flex flex-col gap-2">
          <h2 className="text-[13px] font-bold tracking-tight break-keep text-ink-2">최근 발급분</h2>
          <ul className="flex flex-col gap-2">
            {earlier.map((mission) => (
              <li key={mission.missionId}>
                <FieldMissionCard mission={mission} siteName={siteNames.get(mission.siteId)} />
              </li>
            ))}
          </ul>
          {hiddenCount > 0 && (
            <p className="text-[12.5px] break-keep text-ink-muted">
              오래된 임무 <span className="num">{hiddenCount}</span>건은 여기 표시하지
              않았습니다 — 전체 목록은 임무 화면에서 볼 수 있습니다.
            </p>
          )}
        </section>
      )}
    </div>
  );
}

/**
 * 목록 행 — 장갑 낀 손이 목표다.
 *
 * 행 전체가 링크이고 세로 여백을 크게 준다(`min-h-[72px]`). 임무 화면의 카드는
 * 한 행에 사실 6개를 담지만 여기는 셋만 담는다 — 현장에서 임무를 고를 때 쓰는 것은
 * 종류·현장·발급시각이고, 나머지는 들어가서 본다.
 */
function FieldMissionCard({
  mission,
  siteName,
}: {
  mission: MissionRecordResponse;
  siteName: string | undefined;
}) {
  const coverage = mission.coverageCompletionState
    ? COMPLETION_STATE_LABEL[mission.coverageCompletionState]
    : COVERAGE_NOT_REPORTED_LABEL;

  return (
    <Link
      href={`/field/${encodeURIComponent(mission.missionId)}`}
      className="flex min-h-[72px] flex-col justify-center gap-1.5 rounded-lg border border-line bg-surface px-4 py-3 hover:border-line-strong hover:bg-sunk"
    >
      <span className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-[15px] font-bold tracking-tight break-keep">
          {MISSION_TYPE_LABEL[mission.missionType]} · {siteName ?? mission.siteId}
        </span>
        <StatusBadge label={coverage.label} tone={coverage.tone} />
      </span>
      <span className="num text-[12px] break-token text-ink-muted">
        {formatKoreanDateTime(mission.issuedAt, { dateStyle: "medium", timeStyle: "short" })} 발급 ·{" "}
        {mission.missionId}
      </span>
    </Link>
  );
}
