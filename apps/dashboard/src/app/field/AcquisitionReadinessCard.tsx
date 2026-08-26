import { StateBadge } from "@/components/ui/StatusBadge";
import type { AcquisitionProgressView, AcquisitionReadinessView } from "@/lib/core-api/types";

import { presentAcquisitionReadiness } from "./acquisition-readiness";

export function AcquisitionReadinessCard({
  readiness,
  progress = null,
}: {
  readiness: AcquisitionReadinessView | null;
  progress?: AcquisitionProgressView | null;
}) {
  const presentation = presentAcquisitionReadiness(readiness, progress);
  return (
    <section className="flex flex-col gap-3 rounded-xl border border-line bg-surface p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-[12px] font-semibold text-ink-muted">장비·연결 상세</p>
          <h2 className="mt-1 text-[17px] font-bold tracking-tight">RC-first Connected Edge</h2>
        </div>
        <StateBadge label={presentation.label} tone={presentation.tone} />
      </div>
      <p className="text-[13px] leading-5 break-keep text-ink-2">{presentation.detail}</p>
      <dl className="grid gap-2 sm:grid-cols-2">
        {presentation.rows.map((row) => (
          <div
            key={row.label}
            className="flex min-h-11 items-center justify-between gap-3 rounded-lg border border-line px-3 py-2"
          >
            <dt className="text-[12px] text-ink-2">{row.label}</dt>
            <dd>
              <StateBadge label={row.value} tone={row.tone} />
            </dd>
          </div>
        ))}
      </dl>
      <p className="text-[11.5px] leading-5 text-ink-muted">
        비행 중 인터넷이 끊겨도 이미 활성화된 계약은 만료 전까지 유효합니다.
      </p>
    </section>
  );
}
