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
 * 현장 상세 머리 — 정체(상태·식별자)·행동·시간축·메뉴가 스크롤 위에 함께 있는 자리.
 *
 * 현장 안의 화면들(작업공간·자료·결과·관측 작업·관리)이 같은 머리를 쓴다. 그래서
 * 자료·분석 화면에 들어가도 현장과 구역, 그리고 다른 영역으로 가는 길이 사라지지
 * 않는다. 시안의 "조사 주기" 선택과 "내 현장 고정"은 넣지 않았다 — 이 시스템에
 * 조사 주기라는 값은 없고(현장이 가진 것은 모델 노후 판정 기준일 뿐이라 주기로
 * 바꿔 부르면 없는 약속을 만든다), 고정은 저장할 곳이 없어 새로고침하면 사라지는
 * 버튼이 된다.
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
  /** 탐색 중이던 시각 쌍 맥락 — 현황·분석 이동에 그대로 싣고 받는 화면이 재대조한다. */
  visualContext?: {
    workAreaId: string;
    visualAAssetRef: string;
    visualBAssetRef: string;
    hintBaseline?: { workOrderId: string; submissionRef: string; revision: number };
    hintCurrent?: { workOrderId: string; submissionRef: string; revision: number };
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
  const visualScope = visualContext && scope.workAreaId && visualContext.workAreaId === scope.workAreaId
    ? visualContext
    : null;
  const withVisual = (href: string, includeHints = false): string => {
    if (!visualScope) return href;
    const separator = href.includes("?") ? "&" : "?";
    let suffix = `visualAAssetRef=${encodeURIComponent(visualScope.visualAAssetRef)}&visualBAssetRef=${encodeURIComponent(visualScope.visualBAssetRef)}`;
    if (includeHints && visualScope.hintBaseline && visualScope.hintCurrent) {
      suffix += `&hintBaselineWorkOrderId=${encodeURIComponent(visualScope.hintBaseline.workOrderId)}`
        + `&hintBaselineSubmissionRef=${encodeURIComponent(visualScope.hintBaseline.submissionRef)}`
        + `&hintBaselineRevision=${encodeURIComponent(String(visualScope.hintBaseline.revision))}`
        + `&hintCurrentWorkOrderId=${encodeURIComponent(visualScope.hintCurrent.workOrderId)}`
        + `&hintCurrentSubmissionRef=${encodeURIComponent(visualScope.hintCurrent.submissionRef)}`
        + `&hintCurrentRevision=${encodeURIComponent(String(visualScope.hintCurrent.revision))}`;
    }
    const target = `${href}${separator}${suffix}`;
    return includeHints && visualScope.hintBaseline && visualScope.hintCurrent
      ? `${target}#new-analysis-request` : target;
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
  const workOrdersTab = SITE_TABS.find((option) => option.key === "work-orders");
  const showRecordsContext = tab === "materials" || tab === "work-orders";
  const activeTab = tab === "work-orders" ? "materials" : tab;
  return (
    <header
      className="flex flex-col gap-1.5 border-b border-line bg-surface px-4 pt-2.5 sm:px-5"
      // 서버 확인 범위의 읽기 전용 브리지 — 팔레트가 열릴 때 같은 목적지를
      // 가리키게 한다. URL 쿼리에는 없는 bare deep link(분석 기록 직접 연결 등)의
      // 실제 구역을 헤더가 이미 알고 있을 때만 싣는다. 판정이 아니라 힌트이며,
      // 받는 화면이 서버 목록과 재대조한다. 빈 값은 없음으로 읽는다.
      data-site-nav="true"
      data-site-id={site.siteId}
      data-work-area-id={scopedWorkAreaId ?? ""}
      data-asset-ref={scopedAssetRef ?? ""}
    >
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        {/* 앱 셸의 sr-only h1이 현재 위치를 유일하게 소유한다. 여기 대상명은 그 하위
            맥락이므로 h2다 — 같은 상세 화면에서 h1이 두 번 읽히지 않게 한다.
            현장명은 한 번만 보인다. 앞의 "현장명" 라벨과 별도 큰 머리글은 두지 않는다. */}
        <h2 className="text-[16px] font-bold tracking-tight break-keep">{site.name}</h2>
        <StateBadge label={status.label} tone={status.tone} />
        <details className="text-[12px] text-ink-2">
          <summary className="tap-target cursor-pointer underline decoration-dotted">현장 정보·범위</summary>
          <dl className="my-1.5 grid gap-1">
            <div><dt className="font-semibold">현장 관리 상태</dt><dd>{status.label}</dd></div>
            <div><dt className="font-semibold">현장 식별자</dt><dd className="break-all font-mono">{site.siteId}</dd></div>
          </dl>
        <p>
          <Link
            href={`/sites/${encodeURIComponent(site.siteId)}?section=manage#site-aoi`}
            className="tap-target text-[11.5px] break-keep underline text-ink-2"
          >
            현장 전체 범위 보기
          </Link>
        </p>
        {latestExternalReportKnown !== undefined && (
          <p className="mt-1 text-[11.5px] break-keep text-ink-2">
            최근 외부 비교 보고{" "}
            {!latestExternalReportKnown
              ? "알 수 없음"
              : latestExternalReportAt
                ? formatKoreanDate(latestExternalReportAt)
                : "아직 없음"}
          </p>
        )}
        {site.resumeTarget && (
          <span className="mt-1 block text-[11.5px] break-keep text-ink-2">
            복귀 예정 상태 {SITE_STATUS_LABEL[site.resumeTarget].label}
          </span>
        )}
        </details>

        <span className="ml-auto hidden flex-wrap items-center gap-1.5 lg:flex">
          {primaryAction && (
            <Link
              href={primaryAction.href}
              className="btn btn-primary tap-target"
            >
              {primaryAction.label}
            </Link>
          )}
        </span>
      </div>

      {/*
        현장 업무 메뉴 — 세 영역을 펼침 없이 바로 보인다. label 없는 아이콘-only
        진입은 두지 않으며, 현재 영역은 aria-current로 밝힌다. 관측 작업 기록
        (옛 ?section=work-orders)은 최상위에 두지 않고 자료 맥락의 하위 길로
        두고, 현장 설정은 아래 설정 메뉴로 둔다. 키보드로 이동하고 포커스 표시를 둔다.
      */}
      <nav className="grid grid-cols-3 gap-1 pb-2" aria-label="현장 업무 메뉴">
        {headerTabs.map((option) => (
          <Link
            key={option.key}
            href={option.key === "results" ? withVisual(hrefWith(site.siteId, current, { section: option.key }, scope), true) : withVisual(hrefWith(site.siteId, current, { section: option.key }, scope))}
            aria-current={option.key === activeTab ? "page" : undefined}
            className={`tap-target flex items-center justify-center rounded-md px-2 text-[12.5px] whitespace-nowrap focus-visible:outline-2 focus-visible:outline-offset-2 sm:justify-start sm:px-3 sm:text-[13px] ${option.key === activeTab ? "bg-sunk font-bold" : "text-ink-2"}`}
          >
            {option.label}
          </Link>
        ))}
      </nav>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 pb-2 text-[12px] text-ink-2">
        <details className="relative">
          <summary className="tap-target cursor-pointer list-none rounded-md border border-line bg-surface px-2.5 py-1.5 font-semibold focus-visible:outline-2 focus-visible:outline-offset-2">
            설정
          </summary>
          <div className="absolute z-10 mt-1 flex min-w-44 flex-col gap-1 rounded-md border border-line bg-surface p-1.5 shadow-lg">
            <Link
              href={`/sites/${encodeURIComponent(site.siteId)}/work-areas`}
              className="tap-target rounded px-2 py-1.5 hover:bg-sunk focus-visible:outline-2 focus-visible:outline-offset-2"
            >
              작업구역 관리
            </Link>
            <Link
              href={`${hrefWith(site.siteId, current, { section: "manage" }, scope)}#site-aoi`}
              className="tap-target rounded px-2 py-1.5 hover:bg-sunk focus-visible:outline-2 focus-visible:outline-offset-2"
            >
              현장 전체 범위
            </Link>
            <Link
              href={hrefWith(site.siteId, current, { section: "manage" }, scope)}
              className="tap-target rounded px-2 py-1.5 hover:bg-sunk focus-visible:outline-2 focus-visible:outline-offset-2"
            >
              현장 상태
            </Link>
          </div>
        </details>
        {showRecordsContext && workOrdersTab ? (
          <p>
            <span>자료 · </span>
            <Link
              href={hrefWith(site.siteId, current, { section: "work-orders" }, scope)}
              aria-current={tab === "work-orders" ? "page" : undefined}
              className="tap-target underline decoration-dotted focus-visible:outline-2 focus-visible:outline-offset-2"
            >
              {workOrdersTab.label}
            </Link>
          </p>
        ) : null}
      </div>
    </header>
  );
}
