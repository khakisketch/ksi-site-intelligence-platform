// Phase 3/4 표시 라벨·표현 규칙 — 판정이 아니라 **말로 옮기는 것**만 여기 둔다.
// (mission-labels.ts / triage.ts 와 같은 자리)

import type { EquipmentSupportLevel } from "./types";

/**
 * 장비 지원단계 라벨.
 *
 * `PRODUCTION_SUPPORTED` 만 "상용 지원"이라 부른다 — 나머지는 전부 검증 단계
 * 이름이고, 그 사실이 라벨에서부터 드러나야 한다(`docs/00_READ_FIRST.md` 구현
 * 금지 "미검증 장비를 상용지원으로 표시", REQ-MODEL-101).
 *
 * **이 표로 지원 여부를 판단하지 않는다.** 그 판정은 서버의 `productionSupported`
 * 파생값이다 — 여기 라벨은 사람이 읽는 이름일 뿐이라, 단계가 추가돼도 판정이
 * 흔들리지 않게 둘을 분리한다.
 */
export const SUPPORT_LEVEL_LABEL: Record<EquipmentSupportLevel, string> = {
  DATASET_AVAILABLE: "데이터셋 확보",
  BASELINE_DETECTION: "기본 탐지 검증",
  FIELD_VALIDATED: "현장 검증",
  GEO_VALIDATED: "측위 검증",
  RISK_VALIDATED: "위험판단 검증",
  // 단계명과 지원 배지가 둘 다 "상용 지원"이면 표에서 같은 말이 나란히 찍혀
  // 어느 쪽이 판정인지 눈으로 구분되지 않는다(2026-08-08 렌더 확인). 단계는
  // "무엇을 마쳤나", 배지는 "지금 지원하는가" — 다른 질문이므로 다른 말을 쓴다.
  PRODUCTION_SUPPORTED: "상용 지원 승인",
};

/** 승급 사다리 순서 — 화면이 "지금 어디까지 왔나"를 진행 막대로 보여줄 때 쓴다. */
export const SUPPORT_LEVEL_ORDER: EquipmentSupportLevel[] = [
  "DATASET_AVAILABLE",
  "BASELINE_DETECTION",
  "FIELD_VALIDATED",
  "GEO_VALIDATED",
  "RISK_VALIDATED",
  "PRODUCTION_SUPPORTED",
];

/**
 * TTC 표시 — `null` 은 "위험 없음"이 아니다.
 *
 * 서버 계약이 명시한다: `null` 은 **"이 지평선 안에서는 확인되지 않음"**이다
 * (`cpa_ttc.time_to_collision`). 화면이 이걸 "안전"이나 "—"로 뭉개면 운영자가
 * 확인되지 않은 것을 확인된 안전으로 읽는다.
 */
export function formatTimeToCollision(
  timeToCollisionS: number | null,
  horizonS: number,
): string {
  if (timeToCollisionS === null) return `${horizonS}초 지평선 내 미확인`;
  if (timeToCollisionS === 0) return "이미 반경 안";
  return `${timeToCollisionS.toFixed(1)}초`;
}

/** 위치 불확실성 — 미터 단위 한 자리. 값 자체가 신뢰도라 반올림을 숨기지 않는다. */
export function formatUncertainty(meters: number): string {
  return `± ${meters.toFixed(1)} m`;
}

export function formatRatioPercent(ratio: number): string {
  return `${(ratio * 100).toFixed(1)}%`;
}
