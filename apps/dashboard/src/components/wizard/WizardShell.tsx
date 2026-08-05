"use client";

import Link from "next/link";

export function WizardShell({
  title,
  stepLabels,
  currentStep,
  children,
  onBack,
  onNext,
  nextLabel = "다음",
  nextDisabled = false,
  nextPending = false,
  error,
  /** 목록으로 돌아가는 경로. 입력은 sessionStorage 초안으로 이미 자동 저장되므로
   * 확인 다이얼로그 없이 바로 나가도 된다(useDraftState). */
  exitHref,
  exitLabel = "목록으로",
}: {
  title: string;
  stepLabels: string[];
  currentStep: number;
  children: React.ReactNode;
  onBack?: () => void;
  onNext: () => void;
  nextLabel?: string;
  nextDisabled?: boolean;
  nextPending?: boolean;
  error?: React.ReactNode;
  exitHref?: string;
  exitLabel?: string;
}) {
  const totalSteps = stepLabels.length;
  // 8단계(SiteRegistrationWizard)까지 dot+line 전체 라벨을 늘어놓으면 1024px 에서
  // 넘친다 — 라벨 총량이 많은 구성(5단계 초과)에서는 현재 단계 중심 축약형으로 바꾼다.
  const isCompact = totalSteps > 5;

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 p-4 sm:p-5">
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
          <p className="text-[10.5px] font-bold tracking-[0.1em] text-ink-muted uppercase break-keep">
            {title}
          </p>
          {exitHref && (
            <Link
              href={exitHref}
              className="text-[12.5px] font-semibold break-keep text-ink-2 underline-offset-2 hover:text-ink-1 hover:underline"
            >
              {exitLabel}
            </Link>
          )}
        </div>

        {isCompact ? (
          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-3">
              <span className="num ring-accent/15 flex h-[26px] w-[26px] shrink-0 items-center justify-center rounded-full border-[1.5px] border-accent bg-accent-tint text-[12px] font-bold text-accent-ink ring-3">
                {currentStep + 1}
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-[13px] font-semibold break-keep text-ink-1">
                  {stepLabels[currentStep]}
                </p>
                {currentStep + 1 < totalSteps && (
                  <p className="truncate text-[11.5px] break-keep text-ink-muted">
                    다음: {stepLabels[currentStep + 1]}
                  </p>
                )}
              </div>
              <span className="num shrink-0 text-[12px] text-ink-muted">
                {currentStep + 1} / {totalSteps}
              </span>
            </div>
            <div
              className="h-1.5 w-full overflow-hidden rounded-full bg-line"
              role="progressbar"
              aria-valuenow={currentStep + 1}
              aria-valuemin={1}
              aria-valuemax={totalSteps}
              aria-label="진행률"
            >
              <div
                className="h-full rounded-full bg-accent transition-[width]"
                style={{ width: `${((currentStep + 1) / totalSteps) * 100}%` }}
              />
            </div>
          </div>
        ) : (
          <ol className="flex items-center" aria-label="진행 단계">
            {stepLabels.map((label, i) => (
              <li key={label} className="flex min-w-0 flex-1 items-center last:flex-none">
                <span className="flex min-w-0 items-center gap-2">
                  <span
                    aria-hidden
                    className={`num flex h-[26px] w-[26px] shrink-0 items-center justify-center rounded-full border-[1.5px] text-[12px] font-bold ${
                      i < currentStep
                        ? "border-accent bg-accent text-accent-on"
                        : i === currentStep
                          ? "ring-accent/15 border-accent bg-accent-tint text-accent-ink ring-3"
                          : "border-line-strong bg-surface text-ink-muted"
                    }`}
                  >
                    {i + 1}
                  </span>
                  <span
                    className={`hidden truncate text-[13px] font-semibold break-keep sm:inline ${
                      i === currentStep
                        ? "text-ink-1"
                        : i < currentStep
                          ? "text-ink-2"
                          : "text-ink-muted"
                    }`}
                  >
                    {label}
                  </span>
                </span>
                {i < stepLabels.length - 1 && (
                  <span
                    aria-hidden
                    className={`mx-3 h-[1.5px] min-w-5 flex-1 ${i < currentStep ? "bg-accent" : "bg-line-strong"}`}
                  />
                )}
              </li>
            ))}
          </ol>
        )}
      </div>

      <div className="overflow-hidden rounded-lg border border-line bg-surface">
        <div className="grid grid-cols-1 gap-4 p-4 sm:grid-cols-2 sm:p-5">{children}</div>

        {error && <div className="px-4 pb-4 sm:px-5">{error}</div>}

        <div className="flex flex-wrap items-center gap-3 border-t border-line bg-page px-4 py-3 sm:px-5">
          <button type="button" onClick={onBack} disabled={!onBack} className="btn disabled:invisible">
            이전
          </button>
          <span className="text-[12px] break-keep text-ink-muted">
            {totalSteps}단계 중 {currentStep + 1}단계 · 입력 내용은 자동 저장됩니다
          </span>
          <button
            type="button"
            onClick={onNext}
            disabled={nextDisabled || nextPending}
            className="btn btn-primary ml-auto"
          >
            {nextPending ? "처리 중…" : nextLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
