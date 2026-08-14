import Link from "next/link";
import { notFound } from "next/navigation";

import { AoiPolygonMap } from "@/components/map/AoiPolygonMap";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { StateBadge, StatusBadge } from "@/components/ui/StatusBadge";
import { CoreApiError } from "@/lib/core-api/client";
import {
  EVENT_STATUS_LABEL,
  MISSION_TYPE_LABEL,
  humanizeApiError,
  SITE_STATUS_LABEL,
} from "@/lib/core-api/labels";
import { listEvents } from "@/lib/core-api/events";
import { listMissions } from "@/lib/core-api/missions";
import { hasAllPermissions } from "@/lib/core-api/permissions";
import { getSite } from "@/lib/core-api/sites";
import type { SiteView } from "@/lib/core-api/types";
import { formatKoreanDate } from "@/lib/datetime";

import { SiteAoiEditor } from "./SiteAoiEditor";
import { SiteTransitionActions } from "./SiteTransitionActions";

const MISSION_LIMIT = 5;
const EVENT_LIMIT = 5;

function nextActionFor(site: SiteView): { title: string; description: string; href?: string } {
  switch (site.status) {
    case "UNMAPPED":
      return {
        title: "현장 외곽을 확인한 뒤 초기 매핑을 계획하세요",
        description: "기준 지도가 없어 순찰을 시작할 수 없습니다. 외곽(AOI)을 저장하고 베이스라인 임무를 검토하세요.",
      };
    case "REMAP_REQUIRED":
    case "MODEL_STALE":
      return {
        title: "새 조사로 현장 모델을 최신 상태로 만드세요",
        description: "이전 모델로는 현재 현장을 단정할 수 없습니다. 재조사 임무를 계획한 뒤 결과를 검토하세요.",
      };
    case "BASELINE_MAPPING":
    case "MODEL_PROCESSING":
    case "MODEL_VALIDATION":
      return {
        title: "처리·검증 결과를 기다리는 중입니다",
        description: "자동으로 순찰 가능 상태가 되었다고 가정하지 않습니다. 완료된 임무의 CoverageReport와 현장 상태를 함께 확인하세요.",
      };
    case "SUSPENDED":
      return {
        title: "운영 중단 사유와 복귀 조건을 검토하세요",
        description: "중단 상태에서는 새 자율운영을 시작하지 않습니다. 관리자가 상태 이력과 복귀 조건을 확인해야 합니다.",
      };
    default:
      return {
        title: "현장 상태를 확인하고 필요한 조사를 계획하세요",
        description: "발급된 임무와 검토 대기 이벤트를 확인해 다음 행동을 결정하세요.",
      };
  }
}

/**
 * 섹션 조회 결과 — **권한 부재와 장애를 구분한다.**
 *
 * 둘을 "불러오지 못했습니다" 하나로 뭉개면, 권한이 없어서 안 보이는 것뿐인 운영자가
 * 시스템 장애로 오해해 신고하거나 새로고침을 반복한다(2026-08-04 렌더 확인에서 당시
 * 이벤트 읽기 권한이 없던 역할 계정으로 실제 재현 — ADR-KSI-015 로 역할이 3개로
 * 합쳐지며 이제 전 역할이 EVENTS_READ 를 갖는다. 패턴 자체는 다른 권한 조합에도
 * 여전히 유효하다).
 */
type SectionOutcome<T> = { kind: "ok"; value: T } | { kind: "forbidden" } | { kind: "error" };

function sectionOutcome<T>(result: PromiseSettledResult<T>): SectionOutcome<T> {
  if (result.status === "fulfilled") return { kind: "ok", value: result.value };
  if (result.reason instanceof CoreApiError && result.reason.status === 403) {
    return { kind: "forbidden" };
  }
  return { kind: "error" };
}

function SectionFallback({ what, outcome }: { what: string; outcome: "forbidden" | "error" }) {
  return (
    <p className="text-[13px] break-keep text-ink-muted">
      {outcome === "forbidden"
        ? `이 계정은 ${what}를 볼 권한이 없습니다.`
        : `${what} 정보를 불러오지 못했습니다.`}
    </p>
  );
}

/** 시안 `.facts`/`.fact` — 고정폭 라벨열 + 행마다 하단 보더. 식별자 값은 break-token. */
function Fact({ label, value, isToken = false }: { label: string; value: string; isToken?: boolean }) {
  return (
    <div className="grid grid-cols-[92px_minmax(0,1fr)] items-baseline gap-2.5 border-b border-line py-2 last:border-b-0">
      <dt className="text-[12px] break-keep text-ink-muted">{label}</dt>
      <dd className={`min-w-0 text-[13px] ${isToken ? "num break-token" : "break-keep"}`}>{value}</dd>
    </div>
  );
}

function SectionCard({
  title,
  action,
  children,
}: {
  title: string;
  action?: { label: string; href: string };
  children: React.ReactNode;
}) {
  return (
    <section className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-[15px] font-bold tracking-tight break-keep">{title}</h2>
        {action && (
          <Link
            href={action.href}
            className="tap-target flex items-center text-[12.5px] font-semibold break-keep text-accent-text hover:underline"
          >
            {action.label}
          </Link>
        )}
      </div>
      {children}
    </section>
  );
}

export default async function SiteDetailPage({
  params,
}: {
  params: Promise<{ siteId: string }>;
}) {
  const { siteId } = await params;

  // 데이터 조회는 JSX 생성과 분리한다 — try/catch 안에서 JSX 를 만들면
  // eslint react-hooks/error-boundaries 가 걸린다(렌더는 즉시 실행되지 않아 실제로 못 잡는 에러다).
  let site: SiteView | null = null;
  let errorMessage: string | null = null;
  try {
    site = await getSite(siteId);
  } catch (error) {
    if (error instanceof CoreApiError && error.status === 404) {
      notFound();
    }
    errorMessage =
      error instanceof CoreApiError
        ? humanizeApiError(error.code, error.status, error.serverMessage)
        : "요청을 처리하지 못했습니다.";
  }

  if (errorMessage !== null || site === null) {
    return (
      <div className="flex flex-col gap-4 p-4 sm:p-5">
        <ErrorState message={errorMessage ?? "요청을 처리하지 못했습니다."} />
      </div>
    );
  }

  // 임무·이벤트·권한 조회는 현장 조회와 독립 — 하나가 실패해도 다른 섹션은 계속 보여준다.
  const [missionsResult, eventsResult, canIssueMission, canTransitionSite, canApproveAutonomySite] =
    await Promise.allSettled([
      listMissions(site.siteId),
      listEvents({ siteId: site.siteId }),
      hasAllPermissions("MISSIONS_ISSUE"),
      hasAllPermissions("SITES_WRITE"),
      hasAllPermissions("SITES_AUTONOMY_APPROVE"),
    ]);
  const missions = sectionOutcome(missionsResult);
  const events = sectionOutcome(
    eventsResult.status === "fulfilled"
      ? { status: "fulfilled", value: eventsResult.value.events }
      : eventsResult,
  );
  const canStartSurvey = canIssueMission.status === "fulfilled" && canIssueMission.value;
  const canTransition = canTransitionSite.status === "fulfilled" && canTransitionSite.value;
  const canApproveAutonomy =
    canApproveAutonomySite.status === "fulfilled" && canApproveAutonomySite.value;
  // UNMAPPED 현장은 아직 baseline 임무가 없다 — 같은 "새 조사" 화면(SurveyWizard)으로
  // 보내되(risk dashboard-wizard-rbac-mismatch 해소 경로), 라벨은 실제 목적에 맞춘다.
  const surveyActionLabel = site.status === "UNMAPPED" ? "베이스라인 임무 발급" : "새 조사";

  const statusLabel = SITE_STATUS_LABEL[site.status];
  const nextAction = nextActionFor(site);

  return (
    <div className="flex flex-col gap-5 p-4 sm:p-5 lg:grid lg:grid-cols-[minmax(0,1fr)_340px] lg:items-start lg:gap-5 xl:grid-cols-[minmax(0,1fr)_396px]">
      <div className="flex flex-col gap-5">
        <div className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="flex min-w-0 flex-col gap-1">
              <p className="num break-token text-[10.5px] font-bold tracking-wide text-ink-muted uppercase">
                {site.siteId}
              </p>
              {/* topbar 가 '현장 상세' 를 이미 찍는다 — 여기 h1 은 대상 이름이라 중복이 아니다. */}
              <h2 className="break-keep text-[19px] font-bold tracking-tight">{site.name}</h2>
            </div>
            {canStartSurvey ? (
              <Link href={`/sites/${encodeURIComponent(site.siteId)}/surveys/new`} className="btn btn-primary">
                {surveyActionLabel}
              </Link>
            ) : (
              <div className="flex flex-col items-end gap-1">
                <span className="btn cursor-not-allowed text-ink-muted" aria-disabled="true">
                  {surveyActionLabel}
                </span>
                {/* 라벨을 문장에 넣지 않는다 — "베이스라인 임무 발급"(종성 있음)과
                    "새 조사"(종성 없음)가 서로 다른 조사를 요구해 "발급를" 같은
                    비문이 나온다(독립 재검토 2026-08-04 적발). */}
                <span className="text-[12px] break-keep text-ink-muted">
                  임무 발급 권한이 있어야 시작할 수 있습니다
                </span>
              </div>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <StateBadge label={statusLabel.label} tone={statusLabel.tone} />
            {site.resumeTarget && (
              <span className="text-[12.5px] break-keep text-ink-2">
                복귀 예정 상태: {SITE_STATUS_LABEL[site.resumeTarget].label}
              </span>
            )}
          </div>
        </div>

        <section className="rounded-lg border border-line bg-surface p-4">
          <h2 className="text-[13.5px] font-bold break-keep">다음 행동</h2>
          <p className="mt-1 break-keep text-[13px] font-semibold">{nextAction.title}</p>
          <p className="mt-1 break-keep text-[12.5px] text-ink-2">{nextAction.description}</p>
        </section>

        <SectionCard title="현장 외곽(AOI)">
          {site.aoi ? (
            <AoiPolygonMap value={site.aoi.vertices} readOnly />
          ) : site.status === "UNMAPPED" && canTransition ? (
            // AOI 는 UNMAPPED 상태에서만 설정할 수 있다(서버 게이트, SiteStore.set_aoi
            // 와 동일 조건) — 편집 권한도 그 게이트를 요구하는 SITES_WRITE 로 같다
            // (canTransition 이 이미 그 권한을 대변한다, 새 permission 조회 불필요).
            <SiteAoiEditor siteId={site.siteId} siteFrame={site.siteFrame} />
          ) : (
            <EmptyState
              title="아직 외곽이 등록되지 않았습니다"
              description={
                site.status === "UNMAPPED"
                  ? "이 현장의 AOI를 설정하려면 현장 등록 권한이 필요합니다."
                  : "이 현장의 AOI는 UNMAPPED 상태에서만 설정할 수 있습니다 — 매핑이 이미 시작돼 더는 이 화면에서 설정할 수 없습니다."
              }
            />
          )}
        </SectionCard>

        {/* 설계 기준면은 현장 자산이지 임무 산출물이 아니다 — 한 번 올려 검증되면
            이후 모든 임무가 같은 기준으로 잔량을 낸다. 그래서 임무가 아니라 현장
            화면에 자리를 둔다. */}
        <SectionCard
          title="설계 기준면"
          action={{ label: "관리", href: `/sites/${encodeURIComponent(site.siteId)}/design` }}
        >
          <p className="text-[13px] break-keep text-ink-muted">
            완성된 지형의 계획고를 올려두면, 이후 촬영한 현재 지형과 견줘 구역별로 얼마나
            더 깎고 더 쌓아야 하는지 계산할 수 있습니다.
          </p>
        </SectionCard>

        {/* 작업구역도 설계 기준면과 같은 이유로 현장 화면에 산다 — 비교할 때마다
            새로 그리지 않고 한 번 등록해두는 자산이라서다(M4-C). */}
        <SectionCard
          title="작업구역"
          action={{
            label: "관리",
            href: `/sites/${encodeURIComponent(site.siteId)}/work-areas`,
          }}
        >
          <p className="text-[13px] break-keep text-ink-muted">
            이름을 붙여 등록해두면 이후 잔량·진척을 낼 때마다 지도에 새로 그리는 대신 이
            구역을 고르기만 하면 됩니다 — 지난번과 이번이 같은 범위라야 계획 대비 진척을
            계산할 수 있습니다.{" "}
            <Link
              href={`/sites/${encodeURIComponent(site.siteId)}/progress`}
              className="tap-target inline-flex items-center font-semibold text-accent-text hover:underline"
            >
              계획 대비 진척 보기
            </Link>{" "}
            <Link
              href={`/sites/${encodeURIComponent(site.siteId)}/report`}
              className="tap-target inline-flex items-center font-semibold text-accent-text hover:underline"
            >
              현장 보고서 내보내기
            </Link>
          </p>
        </SectionCard>

        <SectionCard
          title="이 현장의 임무"
          action={{ label: "전체보기", href: `/missions?siteId=${encodeURIComponent(site.siteId)}` }}
        >
          {missions.kind !== "ok" ? (
            <SectionFallback what="임무" outcome={missions.kind} />
          ) : missions.value.length === 0 ? (
            <p className="text-[13px] break-keep text-ink-muted">아직 없습니다.</p>
          ) : (
            <ul className="flex flex-col divide-y divide-line">
              {missions.value.slice(0, MISSION_LIMIT).map((mission) => (
                <li key={mission.missionId}>
                  <Link
                    href={`/missions/${encodeURIComponent(mission.missionId)}`}
                    className="tap-target -mx-2 flex flex-wrap items-center justify-between gap-2 rounded-md px-2 py-2 text-[13.5px] hover:bg-sunk"
                  >
                    <span className="break-keep font-medium">{MISSION_TYPE_LABEL[mission.missionType]}</span>
                    <span className="num text-[12px] whitespace-nowrap text-ink-muted">
                      {formatKoreanDate(mission.issuedAt)}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </SectionCard>

        <SectionCard
          title="이 현장의 이벤트"
          action={{ label: "전체보기", href: `/events?siteId=${encodeURIComponent(site.siteId)}` }}
        >
          {events.kind !== "ok" ? (
            <SectionFallback what="이벤트" outcome={events.kind} />
          ) : events.value.length === 0 ? (
            <p className="text-[13px] break-keep text-ink-muted">아직 없습니다.</p>
          ) : (
            <ul className="flex flex-col divide-y divide-line">
              {events.value.slice(0, EVENT_LIMIT).map((event) => {
                const eventStatusLabel = EVENT_STATUS_LABEL[event.status];
                return (
                  <li key={event.eventKey}>
                    <Link
                      href={`/events/${encodeURIComponent(event.eventKey)}`}
                      className="tap-target -mx-2 flex flex-wrap items-center justify-between gap-2 rounded-md px-2 py-2 text-[13.5px] hover:bg-sunk"
                    >
                      <StatusBadge label={eventStatusLabel.label} tone={eventStatusLabel.tone} />
                      <span className="num text-[12px] whitespace-nowrap text-ink-muted">
                      {formatKoreanDate(event.occurredAt)}
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          )}
        </SectionCard>
      </div>

      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-1 rounded-lg border border-line bg-surface p-4">
          <h2 className="mb-1 text-[13.5px] font-bold break-keep">현장 좌표계</h2>
          <dl className="border-t border-line">
            <Fact label="좌표계(CRS)" value={site.siteFrame.crs} isToken />
            <Fact label="수직 기준면" value={site.siteFrame.verticalDatum} isToken />
            <Fact label="단위" value={site.siteFrame.unit} />
            <Fact label="변환 버전" value={site.siteFrame.transformVersion} isToken />
            <Fact label="등록" value={formatKoreanDate(site.registeredAt)} isToken />
            <Fact label="최근 갱신" value={formatKoreanDate(site.updatedAt)} isToken />
          </dl>
        </div>

        {canTransition ? (
          <details className="rounded-lg border border-line bg-surface p-4">
            <summary className="tap-target flex cursor-pointer items-center font-semibold break-keep">
              관리자 상태 전이
            </summary>
            <p className="mt-2 text-[12px] break-keep text-ink-muted">
              현장 상태 전이는 운용 가능 여부를 바꿉니다. 현재 상태와 전이 사유를 확인한 뒤 진행하세요.
            </p>
            <div className="mt-3">
              <SiteTransitionActions
                siteId={site.siteId}
                status={site.status}
                resumeTarget={site.resumeTarget}
                canApproveAutonomy={canApproveAutonomy}
              />
            </div>
          </details>
        ) : (
          <p className="text-[12px] break-keep text-ink-muted">
            현장 상태를 전이하려면 현장 등록 권한이 필요합니다.
          </p>
        )}
      </div>
    </div>
  );
}
