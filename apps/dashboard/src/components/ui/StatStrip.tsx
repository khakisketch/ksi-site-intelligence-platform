import Link from "next/link";

/** 지표 한 칸. `href` 가 있으면 눌러서 그 수치의 근거 목록으로 간다. */
export interface StatStripItem {
  key: string;
  label: string;
  /** 값 자체. 못 구한 값은 0 이 아니라 "—" 를 넘긴다(INV-040: 모르는 것을 0 으로 말하지 않는다). */
  value: React.ReactNode;
  /** 값 뒤에 붙는 단위(건·곳 등) — 값과 다른 크기로 찍어 숫자가 먼저 읽히게 한다. */
  unit?: string;
  note?: string;
  href?: string;
  /** 안전 상태색은 **주의가 필요할 때만** 쓴다 — 평상시 수치까지 색을 칠하면 색이 신호이길 그만둔다. */
  tone?: "crit";
  /**
   * 이 칸이 **지금 걸린 필터**인가(이벤트 대기열처럼 띠가 필터로도 쓰이는 자리).
   *
   * `aria-pressed` 가 아니라 `aria-current` 를 쓴다 — 이 칸은 누르면 URL 이 바뀌는
   * 링크라 role 이 link 이고, `aria-pressed` 는 button 계열 전용이라 링크에서는
   * 그냥 무시된다(axe-core aria-allowed-attr / WCAG 4.1.2). 시각 차이가 배경색뿐이라
   * 이게 없으면 보조기술 사용자에게 선택 상태를 전할 경로가 아예 없다.
   */
  active?: boolean;
}

/**
 * 지표 띠 — 화면 맨 위에서 "지금 몇 건인가"에 답하는 가로 한 줄(Console v2 §1).
 *
 * 카드 여러 장이 아니라 **한 장을 나눠 쓰는** 이유는 이 수치들이 서로 비교되는
 * 값이기 때문이다. 카드 사이가 벌어지면 눈이 각각을 따로 읽지만, 한 판에 붙어
 * 있으면 "미조치 3 중 SLA 초과 1" 처럼 관계로 읽힌다.
 *
 * 칸 수를 고정하지 않고 flex 로 접는다 — 태블릿 세로에서 3칸이 한 줄에 들어가지
 * 않으면 억지로 좁히는 대신 두 줄로 접히는 쪽이 읽힌다(이 제품의 1급 기기가
 * 태블릿이다).
 */
export function StatStrip({ items }: { items: StatStripItem[] }) {
  return (
    <section className="flex flex-wrap overflow-hidden rounded-lg border border-line bg-surface">
      {items.map((item, index) => {
        const body = (
          <>
            <span className="block truncate text-[11.5px] font-semibold text-ink-2">
              {item.label}
            </span>
            <span className="mt-0.5 flex items-baseline gap-1.5">
              <span
                className={`num text-[22px] leading-none font-bold tracking-tight ${
                  item.tone === "crit" ? "text-crit" : ""
                }`}
              >
                {item.value}
              </span>
              {item.unit && (
                <span className="text-[11px] whitespace-nowrap text-ink-muted">{item.unit}</span>
              )}
            </span>
            {item.note && (
              <span className="mt-0.5 block truncate text-[11px] text-ink-muted">{item.note}</span>
            )}
          </>
        );

        // 칸 사이 구분선은 첫 칸만 빼고 왼쪽에 긋는다. 접혀서 두 번째 줄로 내려간
        // 칸에도 선이 남지만, 없는 것보다 칸 경계가 분명하다.
        const shell = `min-w-[150px] flex-1 px-4 py-2.5 ${index > 0 ? "border-l border-line" : ""}`;

        return item.href ? (
          <Link
            key={item.key}
            href={item.href}
            aria-current={item.active ? "true" : undefined}
            className={`${shell} transition-colors ${item.active ? "bg-accent-tint" : "hover:bg-sunk"}`}
          >
            {body}
          </Link>
        ) : (
          <div key={item.key} className={shell}>
            {body}
          </div>
        );
      })}
    </section>
  );
}
