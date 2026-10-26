import { useId, type ReactNode } from "react";

import type { OperatorNextAction } from "@/lib/operator-next-action";
import type { SiteNextAction } from "@/lib/core-api/site-progress";
import type { SiteView } from "@/lib/core-api/types";
import { SiteDirectoryCard } from "./SiteDirectoryCard";

/** 현장 목록 한 행의 projection — 카드·밀도표가 같은 값을 쓴다. */
export interface SiteListRow {
  site: SiteView;
  next: SiteNextAction;
  primaryAction: OperatorNextAction | null;
}

/**
 * 데스크톱 갤러리(≥1024px) — 실제 준비된 출력 미리보기 + 간결 텍스트 카드의 격자.
 *
 * 표지는 합성·플레이스홑더가 아니라 현재 허용된 준비된 출력의 실제 픽셀이다.
 * 표시할 미리보기가 없으면 큰 빈 칸을 두지 않는다(카드가 텍스트로 접힌다).
 * 현장명·실제 상태·갱신일·다음 할 일은 카드 본문이 맡는다.
 *
 * 칸은 최대 폭을 제한한 2열/아주 넓은 화면 3열이다. 본문 높이는 자연 그대로
 * 두고 버튼 줄만 아래에 맞춘다(mt-auto).
 */
export function SiteListDesktopCards({
  rows,
  meta,
  sameNameSites,
  trailing,
}: {
  rows: readonly SiteListRow[];
  /** 서버가 준 실제 건수 — 칩의 전체 수와 헷갈리지 않게 걸린 만큼만 말한다. */
  meta: string;
  sameNameSites: ReadonlySet<string>;
  /** 마지막 줄 유틸리티(새 현장 추가) — 개수·정렬·페이지 계산 밖이다. */
  trailing?: ReactNode;
}) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className="flex min-w-0 flex-col gap-2">
      <div className="flex items-baseline gap-2 px-1">
        <h2 id={headingId} className="sr-only">
          현장
        </h2>
        <span className="text-[11.5px] text-ink-muted">{meta}</span>
      </div>
      <div className="grid w-full gap-4 lg:grid-cols-2 2xl:grid-cols-3">
      {rows.map((row) => <SiteDirectoryCard key={row.site.siteId} row={row} sameName={sameNameSites.has(row.site.name)} />)}
      {trailing}
      </div>
    </section>
  );
}
