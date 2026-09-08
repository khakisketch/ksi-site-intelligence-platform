export const RESPONSIVE_ACTIONS = [
  "READ",
  "EVENTS_TRIAGE",
  "ANALYSIS_REVIEW",
  "COPILOT_QUERY",
  "REPORT_ACCESS",
  "WORK_ORDERS_WRITE",
  "REOBSERVATION_APPROVE",
  "MISSIONS_ISSUE",
  "SITE_DEVICE_TRANSITION",
  "MISSION_EXECUTION",
  "SOURCE_MEDIA_MUTATION",
  "RECOVERY_ACTION",
  "EXTERNAL_RECONSTRUCTION_MUTATION",
] as const;

export type ResponsiveAction = (typeof RESPONSIVE_ACTIONS)[number];

const COMPACT_ALLOWED_ACTIONS = new Set<ResponsiveAction>([
  "READ",
  "EVENTS_TRIAGE",
  "ANALYSIS_REVIEW",
  "COPILOT_QUERY",
  "REPORT_ACCESS",
]);

/**
 * 1024px 미만 Operations Console에서 제공하는 UX 범위다.
 *
 * 이 함수는 권한 판정이 아니다. Core RBAC가 모든 API 요청의 보안 경계를 계속 소유한다.
 */
export function isCompactActionAllowed(action: ResponsiveAction): boolean {
  return COMPACT_ALLOWED_ACTIONS.has(action);
}
