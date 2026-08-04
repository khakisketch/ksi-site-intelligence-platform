// 마이크로카피 SSOT — docs/architecture/03_DASHBOARD_UX_GOALS.md §4 그대로 상수화.
// 다른 곳에서 이 표를 우회해 새 라벨을 만들지 않는다.

import type { EventSeverity, EventStatus, MissionType, Role, SiteStatus, TriageStatus } from "./types";

export type Tone = "neutral" | "progress" | "caution" | "positive" | "warning";

export const SITE_STATUS_LABEL: Record<SiteStatus, { label: string; tone: Tone }> = {
  UNMAPPED: { label: "미매핑", tone: "neutral" },
  BASELINE_MAPPING: { label: "초기 매핑 중", tone: "progress" },
  MODEL_PROCESSING: { label: "모델 처리 중", tone: "progress" },
  MODEL_VALIDATION: { label: "모델 검증 중", tone: "progress" },
  PROVISIONAL_AUTONOMY: { label: "임시 자율운영", tone: "caution" },
  PATROL_READY: { label: "순찰 준비 완료", tone: "positive" },
  PATROL_ACTIVE: { label: "순찰 중", tone: "progress" },
  MODEL_STALE: { label: "모델 최신도 낮음", tone: "warning" },
  REMAP_REQUIRED: { label: "재매핑 필요", tone: "warning" },
  SUSPENDED: { label: "운영 중단", tone: "warning" },
};

export const EVENT_STATUS_LABEL: Record<EventStatus, { label: string; tone: Tone }> = {
  OBSERVATION: { label: "관측됨", tone: "neutral" },
  CANDIDATE: { label: "후보", tone: "neutral" },
  EVIDENCE_COLLECTION: { label: "증거 수집 중", tone: "progress" },
  FINDING: { label: "소견", tone: "caution" },
  CONFIRMED_EVENT: { label: "확정", tone: "warning" },
  DISMISSED: { label: "오탐 처리", tone: "neutral" },
  UNRESOLVED: { label: "미해결", tone: "caution" },
};

export const EVENT_SEVERITY_LABEL: Record<EventSeverity, { label: string; tone: Tone }> = {
  CANDIDATE: { label: "후보", tone: "neutral" },
  MEDIUM: { label: "중간", tone: "caution" },
  HIGH: { label: "높음", tone: "warning" },
  CRITICAL: { label: "위험", tone: "warning" },
};

// 심각도가 아직 매겨지지 않은 이벤트(OBSERVATION 단계)를 목록에서 어떻게 부를 것인가.
// 배지를 비워두지 않는 이유: '아직 분류되지 않았다'는 것 자체가 운영자에게 필요한 정보다
// (누락인지 판정 전인지 구분되지 않으면 대기열을 신뢰할 수 없다).
export const SEVERITY_UNSET_LABEL = { label: "심각도 미판정", tone: "neutral" as Tone };

// 무슨 일이 일어났는가 — EventBundle.event_type → 한국어.
//
// 서버 계약상 자유 문자열이고, 지금 인지 파이프라인이 실제로 발행하는 값은
// PERSON_PRESENT 하나뿐이다(packages/perception DEFAULT_EVENT_POLICY — 실제 Solution
// Pack 정책은 Core 소유로 Phase 2+ 예정). 여기 없는 값은 숨기지 않고 원문을 보여준다
// — 새 이벤트 종류가 라벨 누락 때문에 목록에서 조용히 사라지는 편이 훨씬 나쁘다.
export const EVENT_TYPE_LABEL: Record<string, string> = {
  PERSON_PRESENT: "사람 감지",
};

export function humanizeEventType(eventType: string | null): string {
  if (!eventType) return "종류 미분류";
  return EVENT_TYPE_LABEL[eventType] ?? eventType;
}

// 정본: services/core/src/ksi_core/mission_plans.py 미션타입→경로패턴 제약
// (docs/architecture/03_DASHBOARD_UX_GOALS.md §7). 화면마다 별도 라벨을 만들지 않는다 —
// 홈·현장 상세·임무 목록 전부 이 표 하나를 참조한다.
export const MISSION_TYPE_LABEL: Record<MissionType, string> = {
  UNIFIED_SITE_SURVEY: "통합 현장조사",
  BASELINE_MAPPING: "초기 매핑",
  SPATIAL_REFRESH: "공간 갱신",
  AUTONOMOUS_PATROL: "자율 순찰",
  ASSET_INSPECTION: "자산 점검",
  PROGRESS_CAPTURE: "공정 기록",
  INCIDENT_SURVEY: "사고 조사",
  SURVEY_GRADE_MAPPING: "정밀 매핑",
};

export const TRIAGE_STATUS_LABEL: Record<TriageStatus, { label: string; tone: Tone }> = {
  NONE: { label: "미배정", tone: "neutral" },
  ASSIGNED: { label: "배정됨", tone: "progress" },
  ACTION_IN_PROGRESS: { label: "조치 중", tone: "progress" },
  REINSPECTION_REQUESTED: { label: "재점검 요청", tone: "caution" },
  RESOLVED: { label: "해결됨", tone: "positive" },
  CLOSED: { label: "종료", tone: "neutral" },
};

// ADR-KSI-008 §2 Role → TopBar/로그인 표시용 한글 라벨.
export const ROLE_LABEL: Record<Role, string> = {
  ADMIN: "관리자",
  SITE_MANAGER: "현장소장",
  SAFETY_MANAGER: "안전관리자",
  DRONE_OPERATOR: "조종사",
  VIEWER: "열람자",
};

// §3.4 에러 마이크로카피 — API verdict 코드를 사람 말로.
export const API_ERROR_MESSAGE: Record<string, string> = {
  DUPLICATE_SITE_ID: "이미 등록된 현장 ID입니다. 다른 ID를 사용하세요.",
  ILLEGAL_TRANSITION: "현재 상태에서는 이 전이를 할 수 없습니다.",
  STALE_EVENT_VIEW: "화면에 표시된 뒤 사건 내용이 갱신되었습니다. 새로고침 후 다시 시도하세요.",
  MISSION_ID_CONFLICT: "이미 사용 중인 임무 ID입니다.",
  UNKNOWN_SITE: "등록되지 않은 현장입니다.",
  SITE_FRAME_MISMATCH: "요청한 좌표계가 등록된 현장과 다릅니다.",
  COVERAGE_BELOW_CONTRACT_PROMISE: "계획된 커버리지가 약속한 값보다 낮습니다. 경로를 다시 검토하세요.",
  EVIDENCE_INCOMPLETE: "이 확정 등급에 필요한 증거가 아직 부족합니다.",
  STORE_UNAVAILABLE: "서버 저장소 점검 중입니다. 잠시 후 다시 시도하세요.",
  // 증거 경로(ADR-KSI-010 §1). ALREADY_TOMBSTONED 는 '없음'이 아니라 '폐기됨'이라고
  // 말한다 — 사고 조사에서 그 둘은 다른 사실이다.
  DUPLICATE_ARTIFACT: "같은 이름의 증거가 이미 등록돼 있습니다. 파일명을 바꿔 다시 올리세요.",
  UNSUPPORTED_CONTENT_TYPE: "지원하지 않는 파일 형식입니다. 사진(JPEG·PNG·WebP)이나 영상(MP4·WebM)만 올릴 수 있습니다.",
  INVALID_ARTIFACT_ID: "파일 이름에 쓸 수 없는 문자가 있습니다.",
  ALREADY_TOMBSTONED: "보관 기간이 지나 폐기된 증거입니다.",
  EVIDENCE_STORAGE_UNAVAILABLE: "증거 저장소에 연결하지 못했습니다. 잠시 후 다시 시도하세요.",
  INVALID_SITE: "입력한 현장 정보가 올바르지 않습니다.",
  INVALID_REQUEST: "요청 내용이 올바르지 않습니다. 입력값을 확인하세요.",
  INVALID_EVENT_IDENTITY: "이벤트 식별자 형식이 올바르지 않습니다.",
  INVALID_EVENT_TIMESTAMP: "이벤트 발생 시각 형식이 올바르지 않습니다.",
  INVALID_MISSION_IDENTITY: "임무 식별자 형식이 올바르지 않습니다.",
  INVALID_TEXT_ENCODING: "입력한 텍스트에 처리할 수 없는 문자가 포함되어 있습니다.",
  EMPTY_ALLOWED_VOLUMES: "허용 비행 구역이 비어 있어 경로를 만들 수 없습니다. 고급 설정에서 허용 구역을 지정하세요.",
  NON_CONVEX_AOI: "이 조사 방식은 오목한(L자 등) 외곽을 지원하지 않습니다. AOI를 볼록 다각형으로 다시 그리세요.",
  // COVERAGE_BELOW_MINIMUM(경로 생성기 하한 95%)과 COVERAGE_BELOW_CONTRACT_PROMISE(계약이
  // 약속한 값)는 서로 다른 임계값 — 별개 코드로 유지한다(§7 SSOT 정신).
  COVERAGE_BELOW_MINIMUM:
    "실제 촬영 범위가 최소 기준(95%)에 못 미칩니다. 간격을 줄이거나 구역을 나눠 다시 시도하세요.",
  TAKEOFF_HEIGHT_BELOW_MINIMUM: "이륙 안전 고도가 너무 낮습니다(최소 1.2m).",
  TAKEOFF_HEIGHT_EXCEEDS_ENVELOPE: "이륙 안전 고도가 비행 고도 상한을 초과합니다.",
};

export function humanizeApiError(
  code: string | undefined,
  status: number,
  serverMessage?: string,
): string {
  if (code && API_ERROR_MESSAGE[code]) return API_ERROR_MESSAGE[code];
  if (status === 401) return "세션이 만료되었습니다. 다시 로그인하세요.";
  if (status === 403) return "이 작업을 수행할 권한이 없습니다.";
  if (status === 404) return "대상을 찾을 수 없습니다.";
  if (status === 503) return "서버 저장소 점검 중입니다. 잠시 후 다시 시도하세요.";
  // 등록되지 않은 verdict 라도 서버가 준 설명 문장이 있으면 그걸 보여준다(raw 코드값보다 낫다).
  if (serverMessage) return serverMessage;
  return code ? `요청을 처리하지 못했습니다. (${code})` : "요청을 처리하지 못했습니다.";
}
