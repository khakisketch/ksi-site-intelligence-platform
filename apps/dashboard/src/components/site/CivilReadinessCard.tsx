import Link from "next/link";

import { StateBadge } from "@/components/ui/StatusBadge";
import { presentCivilReadiness } from "@/lib/civil-readiness";
import type { CivilReadinessView } from "@/lib/core-api/types";

/**
 * A navigation-only summary for the existing civil safety gates.
 *
 * It contains no mutation, device state, field acceptance, accuracy claim, or
 * comparison result. The linked flow repeats Core's exact selected-input
 * preflight before any quantitative request can be created.
 */
export function CivilReadinessCard({
  readiness,
}: {
  readiness: CivilReadinessView | null;
}) {
  const presentation = presentCivilReadiness(readiness);
  const nextAction = readiness?.nextAction ?? null;

  return (
    <section
      aria-labelledby="civil-readiness-title"
      className="overflow-hidden rounded-lg border border-line bg-surface"
    >
      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 border-b border-line px-4 py-2.5">
        <h2 id="civil-readiness-title" className="text-[13.5px] font-bold tracking-tight break-keep">
          토목 시계열 준비
        </h2>
        <span className="text-[11.5px] break-keep text-ink-muted">운영관리용 상대 물량</span>
        <StateBadge label={presentation.label} tone={presentation.tone} />
      </div>
      <div className="px-4 py-3">
        <p className="text-[13px] leading-5 break-keep text-ink-2">{presentation.detail}</p>
        <dl className="mt-3 grid gap-x-4 gap-y-2 border-t border-line pt-2.5 text-[12px] sm:grid-cols-2">
          <div className="grid grid-cols-[92px_minmax(0,1fr)] gap-2">
            <dt className="break-keep text-ink-muted">처리 시점</dt>
            <dd className="num break-token">
              {readiness ? `${readiness.succeededEpochCount}개 완료` : "확인 불가"}
            </dd>
          </div>
          <div className="grid grid-cols-[92px_minmax(0,1fr)] gap-2">
            <dt className="break-keep text-ink-muted">두 시점 판정</dt>
            <dd className="break-keep">{presentation.pairLabel}</dd>
          </div>
          <div className="grid grid-cols-[92px_minmax(0,1fr)] gap-2 sm:col-span-2">
            <dt className="break-keep text-ink-muted">설계 기준면</dt>
            <dd className="break-keep">{presentation.designSurfaceLabel}</dd>
          </div>
        </dl>
      </div>
      <div className="border-t border-line bg-sunk px-4 py-2.5 text-[11.5px] leading-5 font-medium break-keep text-ink-2">
        이 상태는 현장 수용·측량 정확도·정산 수량·비행 또는 장비 상태를 뜻하지 않습니다.
      </div>
      {nextAction?.href && (
        <div className="border-t border-line px-4 py-2.5">
          <Link
            href={nextAction.href}
            className="tap-target inline-flex items-center text-[12px] font-semibold break-keep text-accent-text hover:underline"
          >
            {nextAction.label}
          </Link>
          <p className="mt-1 text-[11.5px] leading-5 break-keep text-ink-muted">{nextAction.reason}</p>
        </div>
      )}
    </section>
  );
}
