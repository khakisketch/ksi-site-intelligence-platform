/**
 * 화면 표시 이동·확대 도구 띠 — 이미 해독·검증된 버퍼의 CSS 표시만 바꾼다.
 *
 * - 7개 모두 44×44 고정, 한 줄, 2px 간격(320px)이라 390 첫 화면에 둔다.
 * - 아이콘은 Console stroke 토큰(viewBox 24, currentColor, round)과 같은 결이며,
 *   이름 없는 장식이 아니라 aria-label·title을 함께 둔다.
 * - 네트워크·준비 요청을 모른다. 호출자가 같은 표시 뷰 규칙에 태운다.
 */

function ControlSvg({ children }: { children: React.ReactNode }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      className="size-5"
    >
      {children}
    </svg>
  );
}

const ICONS: Record<DisplayControlAction, React.ReactNode> = {
  "pan-left": (
    <ControlSvg><path d="M19 12H5" /><path d="m11 6-6 6 6 6" /></ControlSvg>
  ),
  "pan-right": (
    <ControlSvg><path d="M5 12h14" /><path d="m13 6 6 6-6 6" /></ControlSvg>
  ),
  "pan-up": (
    <ControlSvg><path d="M12 19V5" /><path d="m6 11 6-6 6 6" /></ControlSvg>
  ),
  "pan-down": (
    <ControlSvg><path d="M12 5v14" /><path d="m6 13 6 6 6-6" /></ControlSvg>
  ),
  "zoom-in": (
    <ControlSvg><path d="M12 5v14M5 12h14" /></ControlSvg>
  ),
  "zoom-out": (
    <ControlSvg><path d="M5 12h14" /></ControlSvg>
  ),
  reset: (
    <ControlSvg><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" /></ControlSvg>
  ),
};

export type DisplayControlAction =
  | "pan-left"
  | "pan-right"
  | "pan-up"
  | "pan-down"
  | "zoom-in"
  | "zoom-out"
  | "reset";

const LABELS: Record<DisplayControlAction, string> = {
  "pan-left": "왼쪽으로 이동",
  "pan-right": "오른쪽으로 이동",
  "pan-up": "위쪽으로 이동",
  "pan-down": "아래쪽으로 이동",
  "zoom-in": "확대",
  "zoom-out": "축소",
  reset: "전체 보기",
};

/**
 * 일곱 도구를 한 줄에 둔다. 호출자는 onAction 하나로 받아 같은 표시 뷰
 * 규칙(pan/zoom/reset)으로 처리한다. 개별 비활성화는 전체 보기 등에서만 쓴다.
 */
export function DisplayControlStrip({
  groupLabel,
  onAction,
  zoomInDisabled = false,
  zoomOutDisabled = false,
}: {
  groupLabel: string;
  onAction: (action: DisplayControlAction) => void;
  zoomInDisabled?: boolean;
  zoomOutDisabled?: boolean;
}) {
  const actions: ReadonlyArray<{ action: DisplayControlAction; disabled?: boolean }> = [
    { action: "pan-left" },
    { action: "pan-right" },
    { action: "pan-up" },
    { action: "pan-down" },
    { action: "zoom-in", disabled: zoomInDisabled },
    { action: "zoom-out", disabled: zoomOutDisabled },
    { action: "reset" },
  ];
  return (
    <div
      className="sticky bottom-[calc(var(--mobile-bottom-nav-clearance)+0.25rem)] z-10 flex w-fit flex-nowrap items-center gap-0.5 rounded-md border border-line bg-surface lg:static"
      role="group"
      aria-label={groupLabel}
    >
      {actions.map((item) => (
        <button
          key={item.action}
          type="button"
          className="btn tap-target h-11 w-11 shrink-0 p-0"
          aria-label={LABELS[item.action]}
          title={LABELS[item.action]}
          disabled={item.disabled}
          onClick={() => onAction(item.action)}
        >
          {ICONS[item.action]}
        </button>
      ))}
    </div>
  );
}
