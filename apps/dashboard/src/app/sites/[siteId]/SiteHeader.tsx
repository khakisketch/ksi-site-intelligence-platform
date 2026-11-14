import Link from "next/link";

import { MobileSiteSwitcher } from "@/components/nav/MobileSiteSwitcher";
import { siteSettingsHref } from "@/components/nav/site-context";
import { StateBadge } from "@/components/ui/StatusBadge";
import { SITE_STATUS_LABEL } from "@/lib/core-api/labels";
import { SITE_TABS, type SiteRouteSection } from "@/lib/site-epochs";
import type { SiteView } from "@/lib/core-api/types";
import { siteTabHref, type SiteHeaderScope } from "@/lib/operator-journey";

export function SiteHeader({
  site,
  selectedEpochId,
  tab,
  scopedWorkAreaId = null,
  scopedAssetRef = null,
  visualContext = null,
}: {
  site: SiteView;
  selectedEpochId: string | null;
  tab: SiteRouteSection;
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
  const activeTab = tab === "work-orders" ? "space" : tab;
  const scope: SiteHeaderScope = {
    workAreaId: scopedWorkAreaId,
    assetRef: scopedAssetRef,
  };
  const tabHref = (key: (typeof SITE_TABS)[number]["key"]): string => {
    const href = siteTabHref(site.siteId, key, { epoch: selectedEpochId ?? undefined }, scope);
    if (!visualContext || !scope.workAreaId || visualContext.workAreaId !== scope.workAreaId) return href;
    const params = new URLSearchParams({
      visualAAssetRef: visualContext.visualAAssetRef,
      visualBAssetRef: visualContext.visualBAssetRef,
    });
    return `${href}${href.includes("?") ? "&" : "?"}${params}`;
  };

  return (
    <header
      className="border-b border-line bg-surface"
      data-site-header="true"
      // 서버 확인 범위의 읽기 전용 브리지 — 팔레트가 열릴 때 같은 목적지를
      // 가리키게 한다. URL 쿼리에는 없는 bare deep link(분석 기록 직접 연결 등)의
      // 실제 구역을 헤더가 이미 알고 있을 때만 싣는다. 판정이 아니라 힌트이며,
      // 받는 화면이 서버 목록과 재대조한다. 빈 값은 없음으로 읽는다.
      data-site-nav="true"
      data-site-id={site.siteId}
      data-work-area-id={scopedWorkAreaId ?? ""}
      data-asset-ref={scopedAssetRef ?? ""}
    >
      <div className="mx-auto flex w-full max-w-[1440px] flex-wrap items-center gap-x-2 gap-y-1.5 px-4 py-2 sm:flex-nowrap sm:gap-3 sm:px-6">
        <Link
          href="/sites"
          className="tap-target inline-flex shrink-0 items-center gap-1 text-caption font-semibold text-ink-muted transition-colors hover:text-ink-1"
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
        <h2 className="order-3 w-full min-w-0 text-title font-bold tracking-[-0.02em] break-keep sm:order-none sm:w-auto sm:flex-1 sm:truncate">
          {(() => {
            const match = /^(.*?)(\s*\([^()]+\))$/.exec(site.name);
            if (!match) return site.name;
            return (
              <>
                <span>{match[1]}</span>
                <span className="text-body font-medium tracking-normal text-ink-muted">{match[2]}</span>
              </>
            );
          })()}
        </h2>

        <div className="ml-auto flex shrink-0 items-center gap-2">
          <MobileSiteSwitcher siteId={site.siteId} section={activeTab === "analysis" ? "analysis" : "space"} />
          <StateBadge label={status.label} tone={status.tone} />
          <Link
            href={siteSettingsHref(site.siteId)}
            aria-label="현장 설정"
            aria-current={activeTab === "manage" ? "page" : undefined}
            className="btn btn-quiet btn-sm tap-target lg:hidden"
          >
            설정
          </Link>
        </div>
      </div>

      {/* 현장 메뉴 — 제품 전체에서 같은 밑줄 탭 문법. 현재 영역은
          aria-current와 밑줄로 밝히고, 좁은 화면에서는 가로 스크롤로
          두 줄로 깨지지 않게 한다. */}
      <nav
        className="mx-auto flex w-full max-w-[1440px] gap-1 overflow-x-auto px-3 sm:px-5 lg:hidden"
        aria-label="현장 영역 메뉴"
      >
        {SITE_TABS.map((option) => (
          <Link
            key={option.key}
            href={tabHref(option.key)}
            aria-current={option.key === activeTab ? "page" : undefined}
            className={`tap-target relative flex min-h-11 shrink-0 items-center border-b-2 px-3 text-body whitespace-nowrap transition-colors ${
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
