import Link from "next/link";

import { StateBadge } from "@/components/ui/StatusBadge";
import { SITE_STATUS_LABEL } from "@/lib/core-api/labels";
import { formatKoreanDate } from "@/lib/datetime";
import {
  SITE_TABS,
  type SiteTabKey,
} from "@/lib/site-epochs";
import type { SiteView } from "@/lib/core-api/types";
import { resolveSiteOperatorNextAction } from "@/lib/operator-next-action";
import { siteTabHref, type SiteHeaderScope } from "@/lib/operator-journey";

/** 탭을 옮겨도 고른 시점·구역을 잃지 않는다 — 검증된 범위만 싣는다. */
function hrefWith(
  siteId: string,
  current: { section?: string; epoch?: string },
  patch: { section?: string; epoch?: string },
  scope: SiteHeaderScope,
): string {
  const merged = { ...current, ...patch };
  return siteTabHref(siteId, merged.section ?? "workspace", { epoch: merged.epoch }, scope);
}

/**
 * 현장 상세 머리 — 제품 전체에서 같은 셸과 같은 문법을 쓴다.
 *
 * 위층은 전역 셸(사이드바·상단바)이고, 이 머리는 그 안의 현장 문맥이다.
 * 사이트명·상태·설정·1차 행동을 한 줄에 두고, 작업공간·자료·결과는
 * 밑줄 탭으로 분리한다. 예전의 pill 탭과 화면별 compact 변형은 제거했다 —
 * 같은 제품이 화면마다 다른 앱처럼 보이던 원인 중 하나였다.
 *
 * 현장 안의 화면들(작업공간·자료·결과·관측 작업·관리)이 같은 머리를 쓴다.
 * 시안의 "조사 주기" 선택과 "내 현장 고정"은 넣지 않았다 — 이 시스템에
 * 조사 주기라는 값은 없고, 고정은 저장할 곳이 없어 새로고침하면 사라진다.
 */
export function SiteHeader({
  site,
  selectedEpochId,
  tab,
  latestExternalReportAt,
  latestExternalReportKnown,
  canCreateWorkOrder,
  canEditAoi,
  scopedWorkAreaId = null,
  scopedAssetRef = null,
  visualContext = null,
}: {
  site: SiteView;
  selectedEpochId: string | null;
  tab: SiteTabKey;
  /** 이 화면이 외부 비교 이력을 실제로 읽었을 때만 넘긴다 — 안 읽은 화면은 줄 자체를 만들지 않는다. */
  latestExternalReportAt?: string | null;
  latestExternalReportKnown?: boolean;
  canCreateWorkOrder: boolean;
  canEditAoi: boolean;
  /** 루트가 검증한 현행 승인 구역 — 원문 쿼리를 그대로 두지 않는다. 없으면 범위 없이 간다. */
  scopedWorkAreaId?: string | null;
  /** 같은 등록 자료 목록에서 확인한 자산 참조 — 구역과 함께일 때만 싣는다. */
  scopedAssetRef?: string | null;
  /** 탐색 중이던 시각 쌍 맥락 — 현황·분석 이동에 그대로 싣고 받는 화면이 재대조한다.
   *  결과 이동에는 요청 힌트·앵커를 싣지 않는다 — 둘러보기는 새 요청 의도가 아니다. */
  visualContext?: {
    workAreaId: string;
    visualAAssetRef: string;
    visualBAssetRef: string;
  } | null;
}) {
  const status = SITE_STATUS_LABEL[site.status];
  const current = { section: tab, epoch: selectedEpochId ?? undefined };
  const scope: SiteHeaderScope = {
    workAreaId: scopedWorkAreaId ?? null,
    assetRef: scopedAssetRef ?? null,
  };
  // 시각 쌍 맥락은 같은 구역의 정식 사실일 때만 싣는다. 원문 쿼리를 그대로
  // 두지 않으며, 받는 화면이 서버 목록과 재대조한다. 구역이 바뀌면 쌍을 싣지 않는다.
  // 머리 이동은 둘러보기 맥락(검증된 A/B 참조)만 싣는다 — 요청 힌트 6건과
  // #new-analysis-request 앵커는 명시적 요청 진입(이 쌍으로 분석 조건 확인 등)의
  // 전유물이며, 최상위 결과 이동이 둘러보기를 새 요청으로 바꾸지 않는다.
  const visualScope = visualContext && scope.workAreaId && visualContext.workAreaId === scope.workAreaId
    ? visualContext
    : null;
  const withVisual = (href: string): string => {
    if (!visualScope) return href;
    const separator = href.includes("?") ? "&" : "?";
    return `${href}${separator}visualAAssetRef=${encodeURIComponent(visualScope.visualAAssetRef)}&visualBAssetRef=${encodeURIComponent(visualScope.visualBAssetRef)}`;
  };
  const preparationAction = resolveSiteOperatorNextAction(site, {
    canEditSite: canEditAoi,
    canCreateWorkOrder,
  }, { includeRoutineSurvey: true });
  // 관측 자료 등록은 검증된 구역이 있을 때 범위를 함께 싣는다. 전체 경계·작업구역
  // 설정(AOI) 링크에는 붙이지 않는다. 관측 탭의 중복 진입점은 그대로 둔다.
  const scopedPreparationAction = preparationAction
    && preparationAction.kind === "CREATE_OBSERVATION"
    && scope.workAreaId
    ? { ...preparationAction, href: `${preparationAction.href}?workAreaId=${encodeURIComponent(scope.workAreaId)}` }
    : preparationAction;
  // The workspace panel and the 자료 catalog own this action on their own
  // surfaces; keep one entry point there. Other tabs keep the header action.
  const primaryAction = tab === "workspace" || tab === "materials" ? null : scopedPreparationAction;
  // 최상위 메뉴는 세 영역만 바로 보인다. 관측 작업 기록(work-orders) 키와
  // 현장 설정(manage) 키는 옛 URL(?section=...) 호환을 위해 SITE_TABS·
  // normalizeSiteTab에 남기되, 최상위 nav가 아니라 각각 자료 맥락의 하위 길과
  // 머리 설정 메뉴로 둔다.
  const headerTabs = SITE_TABS.filter((option) => option.key !== "work-orders" && option.key !== "manage");
  const activeTab = tab === "work-orders" ? "materials" : tab;
  const statusBadge = <StateBadge label={status.label} tone={status.tone} />;
  const settingsMenu = (
    <details className="relative text-[12px] text-ink-2">
      <summary className="tap-target flex min-h-10 cursor-pointer list-none items-center rounded-md border border-line bg-surface px-3 font-semibold transition-colors hover:bg-sunk [&::-webkit-details-marker]:hidden">
        설정·정보
      </summary>
      <div className="absolute right-0 z-30 mt-1 flex w-[min(280px,calc(100vw-2rem))] flex-col gap-1 rounded-lg border border-line bg-surface p-2 shadow-xl">
        <div className="flex flex-col gap-0.5 rounded-md bg-sunk/60 px-2.5 py-2">
          <p className="text-[11.5px] font-semibold text-ink-1">현장 관리 상태 · {status.label}</p>
          <p className="break-all font-mono text-[11px] text-ink-muted">{site.siteId}</p>
        </div>
        <Link href={`/sites/${encodeURIComponent(site.siteId)}/work-areas`} className="tap-target rounded-md px-2.5 py-2 font-medium hover:bg-sunk">작업구역 관리</Link>
        <Link href={`/sites/${encodeURIComponent(site.siteId)}?section=manage#site-aoi`} className="tap-target rounded-md px-2.5 py-2 font-medium hover:bg-sunk">현장 전체 범위</Link>
        <Link href={hrefWith(site.siteId, current, { section: "manage" }, scope)} className="tap-target rounded-md px-2.5 py-2 font-medium hover:bg-sunk">현장 상태</Link>
        {latestExternalReportKnown !== undefined && (
          <p className="px-2.5 py-1.5 text-[11.5px] leading-5 text-ink-2">
            최근 외부 비교 보고{" "}
            {!latestExternalReportKnown ? "알 수 없음" : latestExternalReportAt ? formatKoreanDate(latestExternalReportAt) : "아직 없음"}
          </p>
        )}
        {site.resumeTarget && (
          <p className="px-2.5 py-1.5 text-[11.5px] leading-5 text-ink-2">
            복귀 예정 상태 {SITE_STATUS_LABEL[site.resumeTarget].label}
          </p>
        )}
      </div>
    </details>
  );

  return (
    <header
      className="border-b border-line bg-surface"
      // 서버 확인 범위의 읽기 전용 브리지 — 팔레트가 열릴 때 같은 목적지를
      // 가리키게 한다. URL 쿼리에는 없는 bare deep link(분석 기록 직접 연결 등)의
      // 실제 구역을 헤더가 이미 알고 있을 때만 싣는다. 판정이 아니라 힌트이며,
      // 받는 화면이 서버 목록과 재대조한다. 빈 값은 없음으로 읽는다.
      data-site-nav="true"
      data-site-id={site.siteId}
      data-work-area-id={scopedWorkAreaId ?? ""}
      data-asset-ref={scopedAssetRef ?? ""}
    >
      <div className="mx-auto flex w-full max-w-[1440px] flex-wrap items-center gap-x-2 gap-y-1.5 px-4 pt-3 pb-2 sm:flex-nowrap sm:gap-3 sm:px-6">
        <Link
          href="/sites"
          className="tap-target inline-flex shrink-0 items-center gap-1 text-[12px] font-semibold text-ink-muted transition-colors hover:text-ink-1"
        >
          <svg aria-hidden="true" width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" className="flex-none">
            <path d="m10 3-4 5 4 5" />
          </svg>
          현장
        </Link>

        {/* 앱 셸의 sr-only h1이 현재 위치를 유일하게 소유한다. 여기 대상명은
            그 하위 맥락이므로 h2다 — 같은 상세 화면에서 h1이 두 번 읽히지 않게 한다.
            모바일에서는 order-3 + w-full로 이름이 자기 줄을 통째로 써서 중간에
            잘리지 않고, 상태·설정은 첫 줄 오른쪽에 남는다. */}
        <h2 className="order-3 w-full min-w-0 text-[18px] font-bold tracking-[-0.02em] break-keep sm:order-none sm:w-auto sm:flex-1 sm:truncate sm:text-[20px]">
          {(() => {
            const match = /^(.*?)(\s*\([^()]+\))$/.exec(site.name);
            if (!match) return site.name;
            return (
              <>
                <span>{match[1]}</span>
                <span className="text-[13px] font-medium tracking-normal text-ink-muted">{match[2]}</span>
              </>
            );
          })()}
        </h2>

        <div className="ml-auto flex shrink-0 items-center gap-2">
          <div className="hidden w-[10rem] shrink-0 justify-end lg:flex">
            {primaryAction && (
              <Link
                href={primaryAction.href}
                className="btn btn-primary tap-target min-h-10"
              >
                {primaryAction.label}
              </Link>
            )}
          </div>
          {statusBadge}
          {settingsMenu}
        </div>
      </div>

      {/* 현장 업무 메뉴 — 제품 전체에서 같은 밑줄 탭 문법. 현재 영역은
          aria-current와 밑줄로 밝히고, 좁은 화면에서는 가로 스크롤로
          두 줄로 깨지지 않게 한다. */}
      <nav
        className="mx-auto flex w-full max-w-[1440px] gap-1 overflow-x-auto px-3 sm:px-5 lg:hidden"
        aria-label="현장 업무 메뉴"
      >
        {headerTabs.map((option) => (
          <Link
            key={option.key}
            href={withVisual(hrefWith(site.siteId, current, { section: option.key }, scope))}
            aria-current={option.key === activeTab ? "page" : undefined}
            className={`tap-target relative flex min-h-11 shrink-0 items-center border-b-2 px-3 text-[13px] whitespace-nowrap transition-colors ${
              option.key === activeTab
                ? "border-ink-1 font-bold text-ink-1"
                : "border-transparent text-ink-2 hover:border-line-strong hover:text-ink-1"
            }`}
          >
            {option.label}
          </Link>
        ))}
      </nav>
    </header>
  );
}
