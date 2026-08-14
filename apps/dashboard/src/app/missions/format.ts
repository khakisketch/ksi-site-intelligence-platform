// 임무 목록/상세 공통 표시 포맷터.
//
// 날짜/시각 표시는 여기서 만들지 않는다 — @/lib/datetime 의 formatKoreanDateTime 을
// 쓴다. 서버 컨테이너가 어느 시간대로 뜨든 항상 서울 기준으로 찍히게 하기 위한
// 이 저장소의 표준 경로다(risk dashboard-mission-format-bypasses-seoul-timezone,
// 이 파일이 그 규율을 안 따르고 timeZone 없는 Intl.DateTimeFormat 을 직접 써서
// 서버가 UTC 로 뜨면 9시간 어긋나던 것을 해소).

/** 순수 비율→퍼센트 포맷터(계획/실측 공용) — 어떤 비율인지의 의미는 호출부가 말한다. */
export function formatRatio(ratio: number): string {
  return `${(ratio * 100).toFixed(1)}%`;
}

/**
 * **비행 전 계획 추정치**를 표시한다 — 실제로 무엇을 관찰했는지가 아니다.
 * 실측 커버는 비행 후 기체가 올리는 CoverageReport 가 판정한다(PRD §15.5).
 * 라벨에 "계획"을 붙여 쓰는 이유다.
 */
export function formatCoverageRatio(ratio: number | null): string {
  if (ratio === null) return "—";
  return formatRatio(ratio);
}

export function formatNullable(value: string | number | null): string {
  if (value === null) return "—";
  return String(value);
}
