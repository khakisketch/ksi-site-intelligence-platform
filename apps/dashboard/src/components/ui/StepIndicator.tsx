/**
 * 순서가 정보인 작업의 단계 표시 — 등록 3단계, 작업 진행 단계 등.
 *
 * `current`를 주지 않으면 순서만 보여 준다(진행 사실을 말하지 않는다). 주면 그
 * 단계를 현재로, 앞 단계를 지난 것으로 표시한다. 완료·성공 판정은 호출자가 가진
 * 기록에서만 온다 — 이 부품은 받은 값을 그릴 뿐 상태를 추측하지 않는다.
 * 색이 아니라 굵기·채움·`aria-current`로 구분한다.
 */
export function StepIndicator({
  steps,
  current,
  label,
  align = "center",
  className = "",
}: {
  steps: readonly string[];
  /** 0부터 세는 현재 단계. 생략하면 순서만 표시한다. */
  current?: number;
  /** 접근성 이름 — 무엇의 순서인지. */
  label: string;
  align?: "center" | "start";
  className?: string;
}) {
  return (
    <ol
      aria-label={label}
      className={`flex flex-wrap items-center gap-x-3 gap-y-1.5 text-caption text-ink-2 sm:gap-x-2 ${align === "center" ? "justify-center" : "justify-start"} ${className}`}
    >
      {steps.map((step, index) => {
        const isCurrent = current === index;
        const isPast = current !== undefined && index < current;
        return (
          <li key={step} aria-current={isCurrent ? "step" : undefined} className="flex items-center gap-2">
            {index > 0 && <span aria-hidden="true" className="hidden h-px w-4 bg-line-strong sm:block" />}
            <span
              className={`tabular grid size-5 flex-none place-items-center rounded-full border text-micro font-semibold ${
                isCurrent
                  ? "border-accent bg-accent text-accent-on"
                  : isPast
                    ? "border-line-strong bg-sunk text-ink-2"
                    : "border-line-strong text-ink-1"
              }`}
            >
              {index + 1}
            </span>
            <span className={`whitespace-nowrap ${isCurrent ? "font-semibold text-ink-1" : ""}`}>
              {step}
              {isPast && <span className="sr-only"> (지난 단계)</span>}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
