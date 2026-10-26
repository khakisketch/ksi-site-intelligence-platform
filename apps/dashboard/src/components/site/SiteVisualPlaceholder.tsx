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
  const toneClass = tone === "refused"
    ? "border-crit/50 bg-crit-bg/90 text-crit-ink"
    : tone === "unknown"
      ? "border-high/50 bg-high-bg/90 text-high-ink"
      : "border-white/15 bg-black/45 text-sidebar-text";
  const sizeClass = size === "banner" ? "h-[184px] sm:h-[214px]" : "aspect-[16/9] min-h-[132px]";
  if (size === "mini") {
    return (
      <div
        role="img"
        aria-label={`${siteName} 기본 현장 표지. 실제 영상 미리보기가 아닙니다.`}
        data-site-visual-placeholder="mini"
        className={`site-visual-placeholder grid size-10 flex-none place-items-center rounded-md border border-line bg-sidebar text-[11px] font-bold text-sidebar-text ${className}`}
      >
        {mark}
      </div>
    );
  }
  return (
    <div
      role="img"
      aria-label={`${siteName} ${label}. 실제 영상 미리보기가 아닙니다.${note ? ` ${note}` : ""}`}
      data-site-visual-placeholder={tone}
      className={`site-visual-placeholder relative ${sizeClass} overflow-hidden bg-sidebar text-sidebar-text ${className}`}
    >
      <span aria-hidden="true" className="absolute inset-[11%] rounded-sm border border-dashed border-white/15" />
      <span aria-hidden="true" className="absolute left-[11%] top-[11%] size-3 border-l border-t border-white/35" />
      <span aria-hidden="true" className="absolute bottom-[11%] right-[11%] size-3 border-b border-r border-white/35" />
      <div className="absolute inset-0 flex flex-col justify-between gap-3 p-4">
        <div className="flex items-start justify-between gap-3">
          <span className={`rounded border px-2 py-1 font-mono text-[9.5px] tracking-[0.02em] ${toneClass} ${tone === "loading" ? "animate-pulse" : ""}`}>
            {showLabel ? label : "등록 범위"}
          </span>
          <span aria-hidden="true" className="grid size-8 flex-none place-items-center rounded-md bg-white/[0.09] text-[11px] font-bold ring-1 ring-white/10">
            {mark}
          </span>
        </div>
        <div className="min-w-0">
          <p className="line-clamp-2 text-[10.5px] leading-4 text-sidebar-muted">
            실제 영상 아님 · 자료·영역은 현장에서 확인
          </p>
        </div>
      </div>
    </div>
  );
}
