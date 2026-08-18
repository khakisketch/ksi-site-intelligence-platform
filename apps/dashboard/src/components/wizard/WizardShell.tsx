"use client";

import Link from "next/link";

/**
 * 위저드 껍데기 — 왼쪽 단계 레일 · 가운데 입력 · 오른쪽 요약(Console v2 §6).
 *
 * ── 왜 가로 스테퍼에서 세로 레일로 ───────────────────────────────────────
 * 가로 스테퍼는 단계 이름만 겨우 들어가서, 각 단계가 무엇을 묻는지는 그 단계에
 * 도착해야 알 수 있었다. 세로 레일은 같은 폭으로 **이름 + 한 줄 설명**을 담고,
 * 8단계짜리 구성에서도 줄여 쓰지 않아도 된다.
 *
 * **단계를 눌러 건너뛰게 만들지 않는다.** 시안의 레일은 버튼처럼 생겼지만, 이
 * 위저드들은 앞 단계 입력으로 뒤 단계의 선택지를 좁힌다(예: 목적 → 허용 경로
 * 패턴). 임의 이동을 열면 그 전제가 깨진 채로 마지막 발급까지 갈 수 있다. 레일은
 * 현재 위치를 보여주는 자리이고, 이동은 아래 이전/다음 단추만 한다.
 *
 * 좁은 화면에서는 레일 대신 기존 축약형(현재 단계 + 진행 막대)으로 접힌다 — 이
 * 제품의 1급 기기가 태블릿이라 세로 레일이 본문 폭을 먹으면 입력이 좁아진다.
 */
export function WizardShell({
  title,
  stepLabels,
  stepHints,
  currentStep,
  children,
  onBack,
  onNext,
  nextLabel = "다음",
  nextDisabled = false,
  nextPending = false,
  error,
  /** 이 위저드가 어디에서 시작됐는지(예: 재관측 제안) — 레일 위에 붙는다. */
  origin,
  /** 오른쪽 요약 열. 넘기지 않으면 그 열 자체가 없다. */
  aside,
  /** 목록으로 돌아가는 경로. 입력은 sessionStorage 초안으로 이미 자동 저장되므로
   * 확인 다이얼로그 없이 바로 나가도 된다(useDraftState). */
  exitHref,
  exitLabel = "목록으로",
}: {
  title: string;
  stepLabels: string[];
  stepHints?: string[];
  currentStep: number;
  children: React.ReactNode;
  onBack?: () => void;
  onNext: () => void;
  nextLabel?: string;
  nextDisabled?: boolean;
  nextPending?: boolean;
  error?: React.ReactNode;
  origin?: React.ReactNode;
  aside?: React.ReactNode;
  exitHref?: string;
  exitLabel?: string;
}) {
  const totalSteps = stepLabels.length;

  return (
    <div className="flex w-full flex-col gap-4 p-4 sm:p-5 lg:grid lg:grid-cols-[230px_minmax(0,1fr)] lg:items-start xl:grid-cols-[230px_minmax(0,1fr)_320px]">
      {/* ── 좁은 화면용 축약 진행 표시 ─────────────────────────────────── */}
      <div className="flex flex-col gap-2 lg:hidden">
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
          <p className="text-[10.5px] font-bold tracking-[0.1em] break-keep text-ink-muted uppercase">
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
        <div className="flex items-center gap-3">
          <span className="num ring-accent/15 flex size-[26px] shrink-0 items-center justify-center rounded-full border-[1.5px] border-accent bg-accent-tint text-[12px] font-bold text-accent-ink ring-3">
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
        {origin}
      </div>

      {/* ── 넓은 화면용 세로 레일 ──────────────────────────────────────── */}
      <aside className="hidden flex-col gap-3 rounded-lg border border-line bg-surface p-3.5 lg:flex">
        {/* 초안 자동 저장은 이미 동작하지만 **말해 준 적이 없었다** — 여러 단계를
            채우는 화면에서 "나가면 날아가나"는 실제로 사람을 붙잡아 두는 불안이다. */}
        <p className="flex items-center gap-2 rounded-md border border-line bg-sunk px-2.5 py-2 text-[11.5px] break-keep text-ink-2">
          <span aria-hidden="true" className="size-1.5 flex-none rounded-full bg-safe" />
          임시저장됨 · 지금 나가도 입력이 남습니다
        </p>

        <div>
          <p className="text-[10.5px] font-bold tracking-[0.1em] break-keep text-ink-muted uppercase">
            {title}
          </p>
        </div>

        {origin}

        <ol className="flex flex-col gap-0.5" aria-label="진행 단계">
          {stepLabels.map((label, index) => {
            const done = index < currentStep;
            const current = index === currentStep;
            return (
              <li
                key={label}
                aria-current={current ? "step" : undefined}
                className={`grid grid-cols-[22px_minmax(0,1fr)] items-start gap-2.5 rounded-md px-1.5 py-1.5 ${
                  current ? "bg-sunk" : ""
                }`}
              >
                <span
                  aria-hidden="true"
                  className={`num grid size-[22px] place-items-center rounded-full border-[1.5px] text-[10.5px] font-bold ${
                    done
                      ? "border-accent bg-accent text-accent-on"
                      : current
                        ? "border-accent bg-accent-tint text-accent-ink"
                        : "border-line-strong bg-surface text-ink-muted"
                  }`}
                >
                  {done ? "✓" : index + 1}
                </span>
                <span className="min-w-0 pt-px">
                  <span
                    className={`block text-[12.5px] break-keep ${
                      current ? "font-bold text-ink-1" : done ? "text-ink-2" : "text-ink-muted"
                    }`}
                  >
                    {label}
                  </span>
                  {stepHints?.[index] && (
                    <span className="mt-px block text-[11px] break-keep text-ink-muted">
                      {stepHints[index]}
                    </span>
                  )}
                </span>
              </li>
            );
          })}
        </ol>

        {exitHref && (
          <Link
            href={exitHref}
            className="tap-target mt-auto inline-flex items-center text-[12.5px] font-semibold break-keep text-ink-2 underline-offset-2 hover:text-ink-1 hover:underline"
          >
            {exitLabel}
          </Link>
        )}
      </aside>

      {/* ── 입력 ───────────────────────────────────────────────────────── */}
      <div className="min-w-0 overflow-hidden rounded-lg border border-line bg-surface">
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

      {/* ── 요약 ───────────────────────────────────────────────────────── */}
      {aside && <div className="min-w-0 xl:sticky xl:top-4">{aside}</div>}
    </div>
  );
}
