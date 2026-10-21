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
  return siteTabHref(siteId, merged.section ?? "overview", { epoch: merged.epoch }, scope);
}

/**
 * 현장 상세 머리 — 정체(상태·식별자)·행동·시간축·메뉴가 스크롤 위에 함께 있는 자리.
 *
 * 현장 안의 화면들(현황·자료·분석·검토·작업·관리)이 같은 머리를 쓴다. 그래서
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
}) {
  const status = SITE_STATUS_LABEL[site.status];
  const current = { section: tab, epoch: selectedEpochId ?? undefined };
  const scope: SiteHeaderScope = {
    workAreaId: scopedWorkAreaId ?? null,
    assetRef: scopedAssetRef ?? null,
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
  // The overview panel owns this same action on its default tab; keep one
  // entry point there while the mobile panel remains the direct action surface.
  const primaryAction = tab === "overview" ? null : scopedPreparationAction;
  return (
    <header className="flex flex-col gap-1.5 border-b border-line bg-surface px-4 pt-2.5 sm:px-5">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        {/* 앱 셸의 sr-only h1이 현재 위치를 유일하게 소유한다. 여기 대상명은 그 하위
            맥락이므로 h2다 — 같은 상세 화면에서 h1이 두 번 읽히지 않게 한다.
            현장명은 한 번만 보인다. 앞의 "현장명" 라벨과 별도 큰 머리글은 두지 않는다. */}
        <h2 className="text-[16px] font-bold tracking-tight break-keep">{site.name}</h2>
        {site.status === "SUSPENDED" && <StateBadge label={status.label} tone={status.tone} />}
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
        현장 업무 메뉴 — 다섯 영역을 한 곳에서 여닫는다. 데스크톱·모바일 구분 없이
        같은 disclosure를 쓰므로, 다섯 영역 바와 공간 작업 방식이 동시에 나열돼
        서로 경쟁하지 않는다. label 없는 아이콘-only 진입은 두지 않으며, 현재
        영역은 aria-current로 밝힌다. 키보드 Enter/Space로 여닫고 види focus를 둔다.
        펼침 안의 nav가 잘리지 않도록 조상에는 overflow hidden을 두지 않는다.
      */}
      <details className="-mb-px">
        <summary className="tap-target flex cursor-pointer items-center justify-between gap-2 border-t border-line py-1.5 text-[13px] font-semibold focus-visible:outline-2 focus-visible:outline-offset-2">
          <span>현장 메뉴 · {SITE_TABS.find((option) => option.key === tab)?.label}</span>
          <span className="text-[11.5px] font-normal text-ink-muted">열기</span>
        </summary>
        <nav className="grid grid-cols-2 gap-1 pb-2 sm:grid-cols-3 lg:grid-cols-5" aria-label="현장 업무 메뉴">
          {SITE_TABS.map((option) => (
            <Link
              key={option.key}
              href={hrefWith(site.siteId, current, { section: option.key }, scope)}
              aria-current={option.key === tab ? "page" : undefined}
              className={`tap-target flex items-center rounded-md px-3 text-[13px] focus-visible:outline-2 focus-visible:outline-offset-2 ${option.key === tab ? "bg-sunk font-bold" : "text-ink-2"}`}
            >
              {option.label}
            </Link>
          ))}
        </nav>
      </details>
    </header>
  );
}
