/**
 * 한국 시각 표기 — **서버 로컬 시간대에 기대지 않는다.**
 *
 * 현장은 한국이고 서버는 어디서든 돌 수 있다(이 저장소의 배포 구성은 컨테이너
 * 시간대를 고정하지 않는다, `deploy/`에 `TZ=` 선언이 없다). `Date.toLocaleString`을
 * `timeZone` 없이 부르면 그 값은 **서버가 도는 시간대**로 나온다 — 서버가 UTC로
 * 뜨면(흔한 컨테이너 기본값) 화면에 찍히는 시각이 실제 한국 시각과 9시간
 * 어긋난다. 자정 근처에서는 **날짜 자체**가 바뀐다(예: 한국 시각 08:30 계산이
 * UTC 서버에서는 "전날 23:30"으로 찍힌다) — "기준 시점이 언제였는지"가 이
 * 화면(M4-C 진척)의 핵심 주장이라 이 어긋남은 사소하지 않다.
 *
 * `TopBar.tsx`가 이미 이 문제를 알고 `Asia/Seoul`을 명시해 왔다(오늘 날짜
 * 표시). 이 모듈은 그 규율을 한 곳으로 모아, 계산 시각을 찍는 다른 화면들
 * (진척·설계면·비교 제출·설계 대비 잔량)이 매번 새로 알아내지 않게 한다.
 */

export const SEOUL_TIME_ZONE = "Asia/Seoul";

/**
 * ISO 문자열을 한국 시간대의 사람이 읽는 문자열로. 파싱할 수 없으면 원문을
 * 그대로 돌려준다(빈 값보다 원문이 디버깅에 낫다 — 기존 formatMoment 관용구).
 */
export function formatKoreanDateTime(
  iso: string,
  options?: Intl.DateTimeFormatOptions,
): string {
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return iso;
  return when.toLocaleString("ko-KR", { ...options, timeZone: SEOUL_TIME_ZONE });
}
