/**
 * Default site cover used when no real prepared preview exists.
 *
 * This is deliberately not a synthetic landscape or a map fragment. It is a
 * neutral, labelled visual surface that keeps site cards the same size and
 * gives the portfolio a visual rhythm without claiming registered extent,
 * imagery, or accuracy. Real prepared pixels always win when available.
 */
export function SiteVisualPlaceholder({
  siteName,
  label,
  note = null,
  tone = "empty",
  size = "card",
  showLabel = true,
  className = "",
}: {
  siteName: string;
  label: string;
  note?: string | null;
  tone?: "empty" | "loading" | "unknown" | "refused";
  /** `card` keeps the 16:9 site-card cover; `banner` is the shorter Home hero strip. */
  size?: "card" | "banner" | "mini";
  /** Site cards show the state label; Home already prints it in the card body. */
  showLabel?: boolean;
  className?: string;
}) {
  const mark = siteName.trim().charAt(0) || "현";
  // 거부·미확인은 의미색을 유지한다. 빈 상태는 어두운 면이 아니라 밝은
  // 측량 용지 면으로 둔다 — 카드 크기의 검정 박스는 고장난 영상으로 읽힌다.
  const toneClass = tone === "refused"
    ? "border-crit/50 bg-crit-bg/90 text-crit-ink"
    : tone === "unknown"
      ? "border-high/50 bg-high-bg/90 text-high-ink"
      : "border-line-strong bg-surface text-ink-2";
  if (size === "mini") {
    return (
      <div
        role="img"
        aria-label={`${siteName} 기본 현장 표지. 실제 영상 미리보기가 아닙니다.`}
        data-site-visual-placeholder="mini"
        className={`site-visual-placeholder grid size-10 flex-none place-items-center rounded-md border border-line bg-sidebar text-micro font-bold text-sidebar-text ${className}`}
      >
        {mark}
      </div>
    );
  }
  // 미리보기가 없는 표지는 카드 높이를 차지하지 않는다. 16:9 빈 면은 고장난
  // 영상처럼 읽히고 목록의 절반을 비워 두므로, 상태를 말하는 한 줄 띠로 접는다.
  // `card`와 `banner`는 같은 띠를 쓴다 — 실제 픽셀이 있을 때만 표지가 커진다.
  return (
    <div
      role="img"
      aria-label={`${siteName} ${label}. 실제 영상 미리보기가 아닙니다.${note ? ` ${note}` : ""}`}
      data-site-visual-placeholder={tone}
      data-site-visual-size={size}
      className={`flex min-w-0 items-center gap-3 bg-sunk px-4 py-2.5 text-ink-2 ${className}`}
    >
      <span aria-hidden="true" className="grid size-8 flex-none place-items-center rounded-md bg-sidebar text-micro font-bold text-sidebar-text">
        {mark}
      </span>
      <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-2 gap-y-1">
        <span className={`rounded border px-1.5 py-0.5 text-micro font-semibold ${toneClass} ${tone === "loading" ? "animate-pulse" : ""}`}>
          {showLabel ? label : "기본 표지"}
        </span>
        <p className="min-w-0 text-micro leading-4 text-ink-muted">
          실제 영상 아님 · 자료·영역은 현장에서 확인
        </p>
      </div>
    </div>
  );
}
