// 정본: packages/domain/src/ksi_domain/mission_gating.py (INV-052,
// MISSION_TYPE_ALLOWED_SITE_STATUSES) — 이 표를 그대로 미러링한다. 서버가
// 최종 권위이고(409 MISSION_TYPE_SITE_STATUS_MISMATCH는 여전히 서버가 검사한다),
// 이 파일은 새 현장조사 Wizard가 발급 전에 미리 보여주기 위한 것뿐이다.
// 서버 표가 바뀌면 이 파일도 같이 고쳐야 한다(ADR-KSI-014 D4 — 알려진
// 이중유지 리스크, 자동 대조 게이트는 아직 없다).
//
// 각 결정의 근거(문서 인용 vs. 보수적 추론 구분 포함)는 mission_gating.py
// 모듈 docstring이 SSOT다 — 여기 복제하지 않는다.

import type { MissionType, SiteStatus } from "./types";
import { SITE_STATUS_LABEL } from "./labels";

const MAPPING_FROM_SCRATCH: readonly SiteStatus[] = ["UNMAPPED", "REMAP_REQUIRED"];

const REFRESH_EXISTING_MODEL: readonly SiteStatus[] = [
  "PROVISIONAL_AUTONOMY",
  "PATROL_READY",
  "PATROL_ACTIVE",
  "MODEL_STALE",
];

const AUTONOMOUS_READY: readonly SiteStatus[] = [
  "PROVISIONAL_AUTONOMY",
  "PATROL_READY",
  "PATROL_ACTIVE",
];

const ALL_EXCEPT_SUSPENDED: readonly SiteStatus[] = [
  "UNMAPPED",
  "BASELINE_MAPPING",
  "MODEL_PROCESSING",
  "MODEL_VALIDATION",
  "PROVISIONAL_AUTONOMY",
  "PATROL_READY",
  "PATROL_ACTIVE",
  "MODEL_STALE",
  "REMAP_REQUIRED",
];

export const MISSION_TYPE_ALLOWED_SITE_STATUSES: Record<MissionType, readonly SiteStatus[]> = {
  BASELINE_MAPPING: MAPPING_FROM_SCRATCH,
  SURVEY_GRADE_MAPPING: MAPPING_FROM_SCRATCH,
  SPATIAL_REFRESH: REFRESH_EXISTING_MODEL,
  PROGRESS_CAPTURE: REFRESH_EXISTING_MODEL,
  AUTONOMOUS_PATROL: AUTONOMOUS_READY,
  ASSET_INSPECTION: AUTONOMOUS_READY,
  UNIFIED_SITE_SURVEY: [...MAPPING_FROM_SCRATCH, ...REFRESH_EXISTING_MODEL],
  INCIDENT_SURVEY: ALL_EXCEPT_SUSPENDED,
};

export function isMissionTypeAllowedAtSiteStatus(
  missionType: MissionType,
  siteStatus: SiteStatus,
): boolean {
  return MISSION_TYPE_ALLOWED_SITE_STATUSES[missionType].includes(siteStatus);
}

/** 발급 불가 사유 — 현재 상태 + 발급 가능한 상태 목록을 사람 말로. */
export function missionTypeDisabledReason(missionType: MissionType, siteStatus: SiteStatus): string {
  const current = SITE_STATUS_LABEL[siteStatus].label;
  const allowedLabels = MISSION_TYPE_ALLOWED_SITE_STATUSES[missionType].map(
    (status) => SITE_STATUS_LABEL[status].label,
  );
  return `현재 현장 상태(${current})에서는 발급할 수 없습니다. 발급 가능 상태: ${allowedLabels.join(" · ")}.`;
}
