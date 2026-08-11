import type { MissionType } from "./types";

/**
 * `/sites/[siteId]/surveys/new?purpose=...` 진입 시 목적을 미리 채울 수 있는
 * 임무타입 화이트리스트 — 지금은 M2 폐루프(변화탐지 재방문 권고 → SPATIAL_REFRESH
 * 초안, `/reports` 화면의 CTA)만 이 진입점을 쓴다.
 *
 * `purpose` 는 사용자가 URL 을 직접 편집할 수 있는 신뢰 경계 밖 입력이다 — 화이트리스트
 * 밖 값을 임무타입으로 그대로 믿지 않는다(다른 값은 조용히 무시하고 빈 위저드로
 * 시작한다, 오류를 내지 않는다).
 */
const PRESETTABLE_MISSION_TYPES: readonly MissionType[] = ["SPATIAL_REFRESH"];

export function resolveInitialMissionType(purpose: string | undefined): MissionType | null {
  return PRESETTABLE_MISSION_TYPES.find((type) => type === purpose) ?? null;
}
