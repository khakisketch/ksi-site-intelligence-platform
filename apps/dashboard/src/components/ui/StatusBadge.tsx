import type { Tone } from "@/lib/core-api/labels";

// AA 대비 + 색맹 고려 — 색만으로 구분하지 않고 라벨 텍스트를 항상 병기한다(UX 목표 §5).
const TONE_CLASSES: Record<Tone, string> = {
  neutral: "bg-black/5 text-foreground dark:bg-white/10",
  progress: "bg-blue-100 text-blue-900 dark:bg-blue-900/40 dark:text-blue-100",
  caution: "bg-amber-100 text-amber-900 dark:bg-amber-900/40 dark:text-amber-100",
  positive: "bg-emerald-100 text-emerald-900 dark:bg-emerald-900/40 dark:text-emerald-100",
  warning: "bg-red-100 text-red-900 dark:bg-red-900/40 dark:text-red-100",
};

export function StatusBadge({ label, tone }: { label: string; tone: Tone }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium break-keep whitespace-nowrap ${TONE_CLASSES[tone]}`}
    >
      {label}
    </span>
  );
}
