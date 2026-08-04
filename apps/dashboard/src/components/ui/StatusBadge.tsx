import type { Tone } from "@/lib/core-api/labels";

// AA 대비 + 색맹 고려 — 색만으로 구분하지 않고 라벨 텍스트를 항상 병기한다(UX 목표 §5).
//
// 값은 Tailwind 팔레트가 아니라 globals.css 의 안전 상태 토큰을 쓴다. 브랜드 액센트가
// 무채색이라 이 배지들이 화면에서 색을 가진 거의 유일한 요소이고, 그래서 라이트/다크
// 양쪽 대비를 한 곳(토큰)에서 관리해야 한다 — `dark:` 변형이 사라진 이유다.
//
// ── 두 계열로 나누는 이유 ────────────────────────────────────────────────
// 시안은 `.badge` 와 `.state` 를 **다른 모양**으로 둔다. 한 행에 심각도·상태·트리아지
// 배지가 나란히 붙는 화면에서 셋이 같은 알약이면, 운영자는 "후보 · 후보 · 미배정"을 보고
// 어느 것이 심각도인지 매번 다시 읽어야 한다(§4.2 상태 CANDIDATE 와 §4.3 심각도
// CANDIDATE 가 실제로 같은 '후보'다).
//
//   badge — **무엇인가**. 심각도·판정 결과처럼 사건 자체의 속성. 각진 모서리 + 채운 배경
//            + 점 인디케이터. 눈에 먼저 들어와야 하는 쪽.
//   state — **어디까지 왔나**. 트리아지·워크플로 진행 상태. 알약 + 외곽선, 기본은 비워 둔다.
//            채워지는 건 주의가 필요한 상태(미배정 등)뿐이다.
const TONE_CLASSES: Record<Tone, string> = {
  neutral: "bg-idle-bg text-idle-ink",
  progress: "bg-mid-bg text-mid-ink",
  caution: "bg-high-bg text-high-ink",
  positive: "bg-safe-bg text-safe-ink",
  warning: "bg-crit-bg text-crit-ink",
};

// state 계열은 기본이 아웃라인이다 — 진행 상태 전부에 색을 칠하면 화면에서 색이
// 흔해지고, 그 순간 안전 상태색이 신호이기를 그만둔다.
const STATE_TONE_CLASSES: Record<Tone, string> = {
  neutral: "border-line-strong text-ink-2 bg-surface",
  progress: "border-mid text-mid-ink bg-mid-bg",
  caution: "border-high text-high-ink bg-high-bg",
  positive: "border-safe text-safe-ink bg-safe-bg",
  warning: "border-crit text-crit-ink bg-crit-bg font-semibold",
};

/** 사건 자체의 속성 — 심각도·판정 결과. */
export function StatusBadge({ label, tone }: { label: string; tone: Tone }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-[4px] px-2 py-0.5 text-[11.5px] font-bold break-keep whitespace-nowrap ${TONE_CLASSES[tone]}`}
    >
      <span aria-hidden="true" className="size-1.5 rounded-full bg-current" />
      {label}
    </span>
  );
}

/** 워크플로 진행 상태 — 트리아지·현장 단계. */
export function StateBadge({ label, tone }: { label: string; tone: Tone }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11.5px] break-keep whitespace-nowrap ${STATE_TONE_CLASSES[tone]}`}
    >
      {label}
    </span>
  );
}
