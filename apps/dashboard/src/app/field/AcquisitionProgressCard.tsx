import { StateBadge } from "@/components/ui/StatusBadge";
import type { AcquisitionProgressView } from "@/lib/core-api/types";

import { presentAcquisitionProgress } from "./acquisition-progress";

export function AcquisitionProgressCard({
  progress,
}: {
  progress: AcquisitionProgressView | null;
}) {
  const view = presentAcquisitionProgress(progress);
  return (
    <section className="flex flex-col gap-4 rounded-xl border border-line bg-surface p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex flex-col gap-1">
          <p className="text-[12px] font-semibold text-ink-muted">Acquisition progress</p>
          <h2 className="text-[18px] font-bold tracking-tight">{view.label}</h2>
        </div>
        <StateBadge label={view.label} tone={view.tone} />
      </div>

      <ol aria-label="취득 진행 단계" className="grid grid-cols-6 gap-1.5">
        {view.groups.map((label, index) => {
          const step = index + 1;
          const reached = step <= view.currentGroup;
          const current = step === view.currentGroup;
          return (
            <li key={label} aria-current={current ? "step" : undefined} className="min-w-0">
              <span
                aria-hidden="true"
                className={`block h-2 rounded-full ${reached ? "bg-accent" : "bg-line-strong"}`}
              />
              <span
                className={`mt-1 block text-center text-[10px] leading-4 break-keep ${
                  current ? "font-semibold text-ink" : "text-ink-muted"
                }`}
              >
                {label}
              </span>
            </li>
          );
        })}
      </ol>

      <p className="text-[14px] leading-6 break-keep text-ink-2">{view.detail}</p>
      <div className="flex min-h-11 items-center justify-between gap-3 rounded-lg border border-line px-3 py-2">
        <span className="text-[12px] text-ink-2">분석 준비</span>
        <span className="flex max-w-[75%] items-end gap-2 text-right">
          <span className="min-w-0 text-[11px] leading-4 text-ink-muted">{view.analysisDetail}</span>
          <StateBadge label={view.analysisLabel} tone={view.analysisTone} />
        </span>
      </div>
      <div className="flex min-h-11 items-center justify-between gap-3 rounded-lg border border-line px-3 py-2">
        <span className="text-[12px] text-ink-2">전송 확인</span>
        <span className="text-right text-[12px] font-semibold text-ink">
          {view.gatewayReceiptSummary}
        </span>
      </div>
      {view.activeContractOfflineWarning && (
        <p role="status" className="rounded-lg bg-high-bg px-3 py-2 text-[13px] text-high-ink">
          {view.activeContractOfflineWarning}
        </p>
      )}
    </section>
  );
}
