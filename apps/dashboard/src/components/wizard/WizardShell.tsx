"use client";

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
}) {
  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6 p-4 sm:p-6">
      <div>
        <p className="text-foreground/60 text-sm break-keep">{title}</p>
        <ol className="mt-2 flex flex-wrap gap-x-1 gap-y-2 text-xs">
          {stepLabels.map((label, i) => (
            <li
              key={label}
              className={`flex items-center gap-1 rounded-full px-2.5 py-1 break-keep ${
                i === currentStep
                  ? "bg-foreground text-background font-medium"
                  : i < currentStep
                    ? "bg-foreground/15 text-foreground"
                    : "text-foreground/50"
              }`}
            >
              <span aria-hidden>{i + 1}.</span> {label}
            </li>
          ))}
        </ol>
      </div>

      <div className="flex flex-col gap-4">{children}</div>

      {error}

      <div className="flex justify-between gap-3 pt-2">
        <button
          type="button"
          onClick={onBack}
          disabled={!onBack}
          className="border-foreground/30 min-h-11 min-w-11 rounded-md border px-4 text-sm disabled:opacity-0"
        >
          이전
        </button>
        <button
          type="button"
          onClick={onNext}
          disabled={nextDisabled || nextPending}
          className="bg-foreground text-background min-h-11 min-w-11 rounded-md px-6 text-sm font-medium disabled:opacity-40"
        >
          {nextPending ? "처리 중…" : nextLabel}
        </button>
      </div>
    </div>
  );
}
