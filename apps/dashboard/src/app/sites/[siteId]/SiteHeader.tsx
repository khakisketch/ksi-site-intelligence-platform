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


/** 링크를 유지한 채 한 파라미터만 바꾼다 — 탭을 옮겨도 고른 시점을 잃지 않는다. */
function hrefWith(
  siteId: string,
  current: { section?: string; epoch?: string },
  patch: { section?: string; epoch?: string },
): string {
  const merged = { ...current, ...patch };
  const params = new URLSearchParams();
  if (merged.section && merged.section !== "observations") params.set("section", merged.section);
  if (merged.epoch) params.set("epoch", merged.epoch);
  const search = params.toString();
  const base = `/sites/${encodeURIComponent(siteId)}`;
  return search ? `${base}?${search}` : base;
}

/**
 * 현장 상세 머리 — 정체(상태·식별자)·행동·시간축·탭이 스크롤 위에 함께 있는 자리.
 *
 * 시안의 "조사 주기" 선택과 "내 현장 고정"은 넣지 않았다. 이 시스템에 조사 주기라는
 * 값은 없고(현장이 가진 것은 모델 노후 판정 기준일 뿐이라 주기로 바꿔 부르면 없는
 * 약속을 만든다), 고정은 저장할 곳이 없어 새로고침하면 사라지는 버튼이 된다.
 */
export function SiteHeader({
  site,
  selectedEpochId,
  tab,
  latestObservationAt,
  latestObservationKnown,
  canCreateWorkOrder,
  canEditAoi,
}: {
  site: SiteView;
  selectedEpochId: string | null;
  tab: SiteTabKey;
  latestObservationAt: string | null;
  latestObservationKnown: boolean;
  canCreateWorkOrder: boolean;
  canEditAoi: boolean;
}) {
  const status = SITE_STATUS_LABEL[site.status];
  const current = { section: tab, epoch: selectedEpochId ?? undefined };
  const preparationAction = resolveSiteOperatorNextAction(site, {
    canEditSite: canEditAoi,
    canCreateWorkOrder,
  }, { includeRoutineSurvey: true });
  // The observations panel owns this same action on its default tab; keep one
  // entry point there while the mobile panel remains the direct action surface.
  const primaryAction = tab === "observations" ? null : preparationAction;
  return (
    <header className="flex flex-col gap-3 border-b border-line bg-surface px-4 pt-3 sm:px-5">
      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-2">
        {/* 앱 셸의 sr-only h1이 현재 위치를 유일하게 소유한다. 여기 대상명은 그 하위
            맥락이므로 h2다 — 같은 상세 화면에서 h1이 두 번 읽히지 않게 한다. */}
        <h2 className="text-[17px] font-bold tracking-tight break-keep">{site.name}</h2>
        <StateBadge label={status.label} tone={status.tone} />
        <span className="text-[11.5px] break-keep text-ink-2">
          최신 관측{" "}
          {!latestObservationKnown
            ? "알 수 없음"
            : latestObservationAt
              ? formatKoreanDate(latestObservationAt)
              : "아직 없음"}
        </span>
        {site.resumeTarget && (
          <span className="text-[11.5px] break-keep text-ink-2">
            복귀 예정 상태 {SITE_STATUS_LABEL[site.resumeTarget].label}
          </span>
        )}

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

      <details className="-mb-px lg:hidden">
        <summary className="tap-target flex cursor-pointer items-center justify-between border-t border-line py-2 text-[13px] font-semibold">
          현장 메뉴 · {SITE_TABS.find((option) => option.key === tab)?.label}
          <span className="text-[11.5px] font-normal text-ink-muted">열기</span>
        </summary>
        <nav className="grid grid-cols-2 gap-1 pb-2" aria-label="현장 메뉴">
          {SITE_TABS.map((option) => (
            <Link
              key={option.key}
              href={hrefWith(site.siteId, current, { section: option.key })}
              aria-current={option.key === tab ? "page" : undefined}
              className={`tap-target flex items-center rounded-md px-3 text-[13px] ${option.key === tab ? "bg-sunk font-bold" : "text-ink-2"}`}
            >
              {option.label}
            </Link>
          ))}
        </nav>
      </details>

      <nav className="-mb-px hidden gap-0.5 lg:flex" aria-label="현장 상세 화면">
        {SITE_TABS.map((option) => {
          const active = option.key === tab;
          return (
            <Link
              key={option.key}
              href={hrefWith(site.siteId, current, { section: option.key })}
              aria-current={active ? "page" : undefined}
              className={`tap-target inline-flex items-center border-b-2 px-3 text-[13px] break-keep transition-colors ${
                active
                  ? "border-b-ink-1 font-bold"
                  : "border-b-transparent text-ink-2 hover:text-ink-1"
              }`}
            >
              {option.label}
            </Link>
          );
        })}
      </nav>
    </header>
  );
}
