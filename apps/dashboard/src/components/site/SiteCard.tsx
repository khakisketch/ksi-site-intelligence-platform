import Link from "next/link";

import { SITE_STATUS_LABEL } from "@/lib/core-api/labels";
import type { SiteView } from "@/lib/core-api/types";
import { StateBadge } from "@/components/ui/StatusBadge";

/** 카드 바닥에 가로로 붙는 사실 한 쌍. 값이 없으면 호출부가 아예 넘기지 않는다. */
export interface SiteFact {
  key: string;
  value: string;
  /** 수치·날짜처럼 계측값이면 mono+tabular 를 건다. */
  numeric?: boolean;
  /** 이 현장에서 다음에 할 일 — 액센트 텍스트로 눈에 띄게. */
  emphasis?: boolean;
}

/**
 * 현장 카드 — 홈 현황판과 현장 목록이 **같은 컴포넌트**를 쓴다.
 *
 * 같은 대상이 화면마다 다른 모양이면 운영자는 두 번 학습한다. 특히 현장은 이 제품에서
 * 모든 것이 매달리는 축이라, 홈에서 본 카드와 목록에서 본 행이 달라 보이면 "같은 곳인가"를
 * 매번 확인하게 된다.
 *
 * 사실 줄이 항상 바닥에 붙는 게 중요하다(`mt-auto`) — 설명이 있는 카드와 없는 카드가
 * 그리드에 섞여도 눈이 훑는 가로줄이 어긋나지 않는다.
 */
export function SiteCard({
  site,
  facts = [],
  todoMessage,
  riskSlot,
}: {
  site: SiteView;
  facts?: SiteFact[];
  /** 순찰이 아예 불가능한 상태의 안내. 있으면 카드가 '할 일' 모양(점선+가라앉은 배경)이 된다. */
  todoMessage?: string;
  /** 위험 건수 배지 등 상태 배지 옆에 붙일 것. */
  riskSlot?: React.ReactNode;
}) {
  const status = SITE_STATUS_LABEL[site.status];
  const isTodo = Boolean(todoMessage);

  return (
    <Link
      href={`/sites/${encodeURIComponent(site.siteId)}`}
      className={`flex flex-col gap-2.5 rounded-lg border p-4 transition-colors ${
        isTodo
          ? "border-dashed border-line-strong bg-sunk hover:border-ink-muted"
          : "border-line bg-surface hover:border-line-strong"
      }`}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <span className="min-w-0">
          <span className="block text-[14.5px] font-bold tracking-tight break-keep">
            {site.name}
          </span>
          <span className="num mt-0.5 block text-[11.5px] break-token text-ink-muted">
            {site.siteId}
          </span>
        </span>
        <span className="flex flex-wrap items-center gap-1.5">
          {riskSlot}
          <StateBadge label={status.label} tone={status.tone} />
        </span>
      </div>

      {todoMessage && (
        <p className="text-[12.5px] break-keep text-ink-2">{todoMessage}</p>
      )}

      {facts.length > 0 && (
        <div className="mt-auto flex flex-wrap gap-x-4 gap-y-2 border-t border-line pt-2.5">
          {facts.map((fact) => (
            <span key={fact.key} className="flex flex-col gap-px">
              <span className="text-[10.5px] text-ink-muted">{fact.key}</span>
              <span
                className={`text-[13px] font-semibold break-keep ${fact.numeric ? "num" : ""} ${
                  fact.emphasis ? "text-accent-text" : ""
                }`}
              >
                {fact.value}
              </span>
            </span>
          ))}
        </div>
      )}
    </Link>
  );
}
