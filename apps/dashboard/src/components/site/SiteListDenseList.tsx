import Link from "next/link";

import { SITE_STATUS_LABEL } from "@/lib/core-api/labels";
import { formatKoreanDate } from "@/lib/datetime";
import { SiteIdentityDetails } from "@/components/site/SiteIdentityDetails";
import { SitePreviewThumb } from "@/components/site/SitePreviewThumb";
import { SiteProgressBar } from "@/components/site/SiteProgressBar";
import { StateBadge } from "@/components/ui/StatusBadge";
import { TableAction, TableRow, TableShell } from "@/components/ui/TableShell";

import type { SiteListRow } from "./SiteListDesktopCards";

// 이름 180 + 상태 100 + 관리 88 + 갱신 100 + 다음 112 + 바로가기 100
// + 간격(10×5) + 좌우 여백(32) = 762. 1024 뷰포트 본문(~780)에 스크롤 없이 든다.
const DENSE_COLUMNS = "minmax(180px,1.6fr) 100px 88px 100px 112px 100px";
const DENSE_MIN_WIDTH = 762;

/**
 * 데스크톱 밀도 표(≥1024px) — 장식 미리보기 없는 텍스트 전용 대비표.
 *
 * 예전 64px 썸네일 열을 없애고 그 폭을 현장 이름에 돌렸다. 이름·상태·
 * 관리·갱신·다음 할 일을 같은 열에서 비교하고, 행 동작은 열람 하나만
 * 둔다(F08 — 다음 행동 CTA는 현장 상세 헤더가 이미 1차로 보여준다).
 */
export function SiteListDenseList({
  rows,
  meta,
  sameNameSites,
}: {
  rows: readonly SiteListRow[];
  meta: string;
  sameNameSites: ReadonlySet<string>;
}) {
  return (
    <TableShell title="현장 상태" meta={meta}>
      <TableRow columns={DENSE_COLUMNS} minWidth={DENSE_MIN_WIDTH} head>
        <span>현장</span>
        <span>상태</span>
        <span>관리 단계</span>
        <span>갱신</span>
        <span>다음 할 일</span>
        <span className="text-right">바로가기</span>
      </TableRow>

      {rows.map(({ site, next, primaryAction }) => {
        const statusLabel = SITE_STATUS_LABEL[site.status];
        return (
          <TableRow key={site.siteId} columns={DENSE_COLUMNS} minWidth={DENSE_MIN_WIDTH}>
            <div className="flex min-w-0 items-start gap-2">
              <SitePreviewThumb siteId={site.siteId} size="row" />
              <div className="min-w-0 flex-1">
              <Link
                href={`/sites/${encodeURIComponent(site.siteId)}`}
                className="block break-words text-[13.5px] font-semibold hover:underline"
              >
                {site.name}
              </Link>
              {sameNameSites.has(site.name) && <SiteIdentityDetails site={site} sameName />}
              </div>
            </div>

            <span>
              <StateBadge label={statusLabel.label} tone={statusLabel.tone} />
            </span>

            <SiteProgressBar status={site.status} />

            <span className="num text-[11.5px] whitespace-nowrap text-ink-2">
              {formatKoreanDate(site.updatedAt)}
            </span>

            <span
              className={`text-[11.5px] break-keep ${
                next.actionable ? "font-semibold" : "text-ink-muted"
              }`}
            >
              {primaryAction?.label ?? next.label}
            </span>

            {/* 현장별 다음 행동 CTA는 SiteHeader.tsx가 현장 상세에서 이미 1차
                액션으로 보여준다(primaryAction/preparationAction) — 표 행에
                같은 버튼을 또 두면 좁은 열에서 줄바꿈된다(F08). 이 열은
                열람 동작 하나만 남긴다. */}
            <span className="flex justify-end">
              <TableAction
                href={`/sites/${encodeURIComponent(site.siteId)}`}
                label="현장 열기"
                primary
              />
            </span>
          </TableRow>
        );
      })}
    </TableShell>
  );
}
