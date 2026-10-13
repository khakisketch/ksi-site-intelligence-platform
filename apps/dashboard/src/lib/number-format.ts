/**
 * 숫자 표기 SSOT — 컴포넌트·유틸이 `toLocaleString` 을 직접 부르지 않는다.
 *
 * 여기 모으는 이유는 체적 라벨(`phase34-labels.formatVolumeM3`)의 `-0` 규칙과 같은
 * 부류의 사고를 막기 위해서다: 집계가 한쪽 부호뿐인 구역에서 음의 0 을 내는 것은
 * 정상이고, 화면의 "-0 m³"/"-0 bytes" 는 사람이 읽는 값이 아니다. 표기 규칙이
 * 파일마다 갈라지면 그 한 줄이 다시 사라진다.
 */

/** 소수 자리만 자르고 `-0` 은 `0` 으로 눕힌다. */
export function formatNumberKo(value: number, maximumFractionDigits = 1): string {
  const shown = value === 0 ? 0 : value;
  return shown.toLocaleString("ko-KR", { maximumFractionDigits });
}

/** 유효숫자 기준 — 정밀도가 앞자리에 걸리는 값(예: m 단위 GSD)에 쓴다. */
export function formatSignificantKo(value: number, maximumSignificantDigits = 3): string {
  const shown = value === 0 ? 0 : value;
  return shown.toLocaleString("ko-KR", { maximumSignificantDigits });
}

/** 정수 개수(셀·픽셀 등) — 소수점 없이 묶음 표기. */
export function formatCountKo(value: number): string {
  return formatNumberKo(value, 0);
}

/** 바이트 크기 — 정수 묶음 + `bytes` 단위(기술 단위 표기는 영문 유지). */
export function formatBytesKo(value: number): string {
  return `${formatCountKo(value)} bytes`;
}
