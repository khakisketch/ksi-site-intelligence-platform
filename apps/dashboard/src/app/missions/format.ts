// 임무 목록/상세 공통 표시 포맷터.

export function formatDateTime(iso: string): string {
  return new Intl.DateTimeFormat("ko-KR", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(iso));
}

export function formatCoverageRatio(ratio: number | null): string {
  if (ratio === null) return "—";
  return `${(ratio * 100).toFixed(1)}%`;
}

export function formatNullable(value: string | number | null): string {
  if (value === null) return "—";
  return String(value);
}
