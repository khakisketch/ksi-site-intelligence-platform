// 마이크로카피 SSOT — docs/architecture/03_DASHBOARD_UX_GOALS.md §4 그대로 상수화.
// 다른 곳에서 이 표를 우회해 새 라벨을 만들지 않는다.

import type {
  DesignSurfaceRejectionReason,
  DesignSurfaceStatus,
  EventSeverity,
  EventStatus,
  MissionExecutionStatus,
  MissionType,
  Role,
  SiteStatus,
  SpatialModelState,
  TriageStatus,
} from "./types";

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

/**
 * 임무 실행 생애주기 라벨(ADR-KSI-019 G2). 내부 상태값을 화면에 그대로 내지 않는다 —
 * 운영자가 읽는 것은 "기체로 전달됨"이지 "DISPATCHED" 가 아니다.
 */
export const MISSION_EXECUTION_STATUS_LABEL: Record<
  MissionExecutionStatus,
  { label: string; tone: Tone }
> = {
  ISSUED: { label: "발급됨", tone: "neutral" },
  DISPATCHED: { label: "기체로 전달됨", tone: "progress" },
  ACTIVATED: { label: "기체가 확인함", tone: "progress" },
  COMPLETED: { label: "완료 보고됨", tone: "positive" },
  ENDED_INCOMPLETE: { label: "완료되지 않고 끝남", tone: "warning" },
  CANCELLED: { label: "취소됨", tone: "neutral" },
};

/**
 * 공간모델 상태 요약 — 결론 한 줄과 그 근거 한 줄.
 *
 * **미선언을 "최신"으로 표시하지 않는다.** "판정하지 않았다"와 "판정했더니 최신이다"는
 * 다른 사실이고, 전자를 후자로 보여주면 화면이 근거 없는 안심을 준다(ADR-KSI-019 G1).
 * 현장 상태와 모델 유무가 어긋나면(`siteStatusMatchesModel === false`) 그 모순이
 * 결론보다 먼저 읽혀야 한다 — 순찰 준비인데 모델이 없는 현장이 정상으로 보이면 안 된다.
 */
export function spatialModelSummary(input: {
  state: SpatialModelState;
  ageDays: number | null;
  maxAgeDays: number | null;
  siteStatusMatchesModel: boolean;
}): { label: string; detail: string; tone: Tone } {
  if (!input.siteStatusMatchesModel) {
    return {
      label: "현장 상태와 어긋남",
      detail: "현장은 모델이 있는 단계로 표시돼 있는데 실제 공간모델이 없습니다. 확인이 필요합니다.",
      tone: "warning",
    };
  }
  const age = input.ageDays === null ? null : Math.floor(input.ageDays);
  switch (input.state) {
    case "ABSENT":
      return {
        label: "공간모델 없음",
        detail: "아직 이 현장의 3차원 모델이 만들어지지 않았습니다.",
        tone: "neutral",
      };
    case "FRESH":
      return {
        label: "최신",
        detail: `마지막 재구성이 ${age}일 전입니다(기준 ${input.maxAgeDays}일 이내).`,
        tone: "positive",
      };
    case "STALE":
      return {
        label: "오래됨",
        detail: `마지막 재구성이 ${age}일 전으로 기준 ${input.maxAgeDays}일을 넘겼습니다.`,
        tone: "warning",
      };
    case "AGE_POLICY_UNDECLARED":
      return {
        label: "판정 안 함",
        detail: "며칠이면 오래된 것으로 볼지 기준이 정해지지 않아 최신도를 판정하지 않았습니다.",
        tone: "caution",
      };
  }
}

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

// ADR-KSI-015 D1 Role(3역할) → TopBar/로그인 표시용 한글 라벨.
export const ROLE_LABEL: Record<Role, string> = {
  ADMIN: "관리자",
  FIELD_OPERATOR: "현장운영자",
  VIEWER: "열람자",
};

// ── 설계 기준면(M4-A) ──────────────────────────────────────────────────────
//
// 정본은 `ksi_event_contracts.design_surface.DesignSurfaceStatus` 와
// `ksi_core.design_surfaces.DesignSurfaceRejectionReason` 이고 여기는 그 미러다
// (tests/contract/test_design_surface_dashboard_sync.py 가 값 집합을 강제한다).
//
// **라벨 문구가 이 기능의 안전장치다.** `SEALED` 를 "업로드 완료"라고 부르면
// 사용자는 파일이 확인됐다고 읽는다 — 그 시점에 Core 가 아는 것은 "클라이언트가
// 다 올렸다고 말했다"뿐이고, 파일은 아무도 열어보지 않았다. 그래서 여기서는
// 브라우저에서 일어난 일(로컬 사건)과 서버가 확인한 사실(durable)을 다른 말로
// 부른다: 업로드가 끝나도 durable 상태는 "검증 대기"다.
export const DESIGN_SURFACE_STATUS_LABEL: Record<
  DesignSurfaceStatus,
  { label: string; tone: Tone; description: string }
> = {
  REGISTERED: {
    label: "등록됨(파일 없음)",
    tone: "neutral",
    description: "선언 내용만 기록됐습니다 — 파일은 아직 올라오지 않았습니다.",
  },
  SEALED: {
    label: "검증 대기",
    tone: "progress",
    description:
      "업로드를 마쳤다고 이 브라우저가 알렸고 서버가 그 주장을 기록했습니다 — " +
      "아직 아무도 파일을 열어보지 않았습니다. 서버가 파일을 읽어 확인하는 중입니다.",
  },
  VERIFIED: {
    label: "검증 완료",
    tone: "positive",
    description:
      "서버가 파일을 직접 열어 재고, 적어 낸 내용과 전부 일치했습니다 — " +
      "이제 이 설계면으로 잔량을 계산할 수 있습니다.",
  },
  REJECTED: {
    label: "검증 실패",
    tone: "warning",
    description:
      "파일 내용이 적어 낸 내용과 맞지 않습니다 — 되돌릴 수 없으므로 고친 뒤 " +
      "새 개정판으로 다시 올리세요.",
  },
};

/** 거부 사유 8종 → 사람 말 + 무엇을 고쳐야 하는지. */
export const DESIGN_SURFACE_REJECTION_LABEL: Record<DesignSurfaceRejectionReason, string> = {
  DIGEST_MISMATCH:
    "올라온 파일이 적어 낸 파일과 다릅니다 — 다른 파일을 올렸거나 전송 중 손상됐습니다. 같은 파일을 새 개정판으로 다시 올리세요.",
  CRS_DECLARATION_MISMATCH:
    "파일이 들고 있는 좌표계가 적어 낸 좌표계와 다릅니다 — 파일의 실제 좌표계를 확인해 다시 적어 올리세요.",
  UNSUPPORTED_CRS:
    "이 제품이 지원하지 않는 좌표계입니다 — 현행 국가 평면직각좌표계(중부·서부·동부·동해)로 다시 만들어 올리세요.",
  UNSUPPORTED_UNIT:
    "평면 길이 단위가 미터가 아닙니다 — 피트 단위 도면은 받지 않습니다(부피가 조용히 35배 틀립니다).",
  UNSUPPORTED_BAND_COUNT:
    "높이 자료가 아닙니다 — 밴드가 여러 개인 것으로 보아 정사영상 같은 그림 파일을 올린 것 같습니다.",
  NO_FINITE_CELLS:
    "유효한 높이 값이 하나도 없습니다 — 전부 빈 값이거나 내용이 없는 파일입니다.",
  VERTICAL_DECLARATION_CONTRADICTED:
    "파일이 들고 있는 높이 기준이 적어 낸 기준과 맞지 않거나 해석할 수 없습니다 — 타원체 기준 높이와 해발 높이를 섞으면 20~30 m 가 조용히 틀립니다.",
  UNREADABLE_RASTER:
    "파일을 열지 못했습니다 — GeoTIFF 가 아니거나 손상됐습니다.",
};

/**
 * 거부 사유를 사람 말로 — 모르는 코드는 **숨기지 않고** 원문을 보여준다.
 *
 * 서버에 사유가 하나 늘고 이 표가 안 따라간 순간, 사용자에게 빈 칸을 보여주는
 * 것이 가장 나쁜 결과다(왜 막혔는지 알 길이 사라진다).
 */
export function humanizeDesignSurfaceRejection(reason: string | null): string {
  if (!reason) return "사유가 기록되지 않았습니다.";
  const known = DESIGN_SURFACE_REJECTION_LABEL[reason as DesignSurfaceRejectionReason];
  return known ?? `검증에 실패했습니다. (${reason})`;
}

/**
 * 수직 기준을 사람 말로 — 국내에서 두 기준의 차이는 20~30 m 다.
 *
 * 모르는 값은 원문 그대로 보여준다(라벨 누락이 "기준 없음"처럼 보이지 않게).
 */
export const VERTICAL_DATUM_LABEL: Record<string, string> = {
  ellipsoidal: "타원체 기준 높이",
  ellipsoidal_native: "타원체 기준 높이(지오이드 미적용)",
  orthometric_kngeoid2018: "해발 높이(KNGeoid2018)",
  orthometric_kngeoid2024: "해발 높이(KNGeoid2024)",
};

export function humanizeVerticalDatum(datum: string): string {
  return VERTICAL_DATUM_LABEL[datum] ?? datum;
}

// §3.4 에러 마이크로카피 — API verdict 코드를 사람 말로.
export const API_ERROR_MESSAGE: Record<string, string> = {
  DUPLICATE_SITE_ID: "이미 등록된 현장 ID입니다. 다른 ID를 사용하세요.",
  ILLEGAL_TRANSITION: "현재 상태에서는 이 전이를 할 수 없습니다.",
  STALE_EVENT_VIEW: "화면에 표시된 뒤 사건 내용이 갱신되었습니다. 새로고침 후 다시 시도하세요.",
  MISSION_ID_CONFLICT: "이미 사용 중인 임무 ID입니다.",
  UNKNOWN_SITE: "등록되지 않은 현장입니다.",
  SITE_FRAME_MISMATCH: "요청한 좌표계가 등록된 현장과 다릅니다.",
  // INV-052(ADR-KSI-014) — 현재 현장 상태에서 이 임무 목적은 발급할 수 없다.
  // Wizard가 missionSiteGate.ts 로 발급 전에 미리 막으므로 정상 동선에서는
  // 거의 노출되지 않는다(방어 심층 — 다른 클라이언트·표 drift 대비).
  MISSION_TYPE_SITE_STATUS_MISMATCH: "현재 현장 상태에서는 이 임무 목적을 발급할 수 없습니다.",
  COVERAGE_BELOW_CONTRACT_PROMISE:
    "계획 단계의 커버리지가 임무가 요구하는 값에 못 미칩니다. 격자·촬영 간격을 좁히세요.",
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
  // 원본 사진 업로드 · 재구성 발행(M3, B1/B2) — source_media.py/processing_jobs.py verdict.
  BUNDLE_SEALED: "이미 봉인된 번들입니다. 추가 사진을 올리려면 새 임무를 발급하세요.",
  EMPTY_BUNDLE: "등록된 사진이 없어 봉인할 수 없습니다. 먼저 사진을 올리세요.",
  BUNDLE_NOT_SEALED: "번들이 아직 봉인되지 않았습니다 — 업로드를 마치고 봉인한 뒤 다시 시도하세요.",
  ACTIVE_JOB_EXISTS: "이미 처리 중인 작업이 있습니다. 완료 후 다시 시도하세요.",
  EGRESS_NOT_ALLOWED: "이 현장은 데이터 반출이 허용되지 않아 벤더 클라우드 처리를 만들 수 없습니다.",
  // 두 시점 비교 제출(W2) — comparison_requests.ComparisonRequestVerdict. 정상 동선에서는
  // ComparisonSubmitPanel 이 대부분 미리 막지만(selectableEpochs·currentMissionEpochs·
  // comparisonEligibility), 다른 탭에서 원장이 바뀌는 등 레이스로는 여전히 도달할 수 있다
  // — 도달했을 때 내부 필드명이 그대로 섞인 서버 원문이 화면에 뜨지 않게 한다.
  UNKNOWN_JOB: "선택한 재구성 결과를 찾을 수 없습니다. 목록을 새로고침한 뒤 다시 고르세요.",
  JOB_NOT_SUCCEEDED: "아직 완료되지 않은 재구성입니다. 완료된 결과만 비교할 수 있습니다.",
  SELF_COMPARISON: "같은 결과끼리는 비교할 수 없습니다. 서로 다른 두 시점을 고르세요.",
  SITE_MISMATCH: "다른 현장의 결과끼리는 비교할 수 없습니다.",
  MISSION_MISMATCH: "비교 시점(이후)은 이 임무에서 만든 결과여야 합니다. 목록을 새로고침한 뒤 다시 고르세요.",
  NOTHING_TO_COMPARE: "고른 두 결과에 비교할 자료(점군·높이자료)가 없습니다.",
  // 설계 기준면 등록·봉인(M4-A) — design_surfaces.py verdict.
  DECLARATION_CONFLICT:
    "같은 이름·개정으로 다른 내용이 이미 등록돼 있습니다. 개정 표기를 바꿔서 올리세요.",
  UNKNOWN_DESIGN_SURFACE: "등록되지 않은 설계 기준면입니다.",
  ALREADY_JUDGED:
    "이미 검증 판정이 끝난 설계 기준면입니다 — 되돌릴 수 없습니다. 고친 파일을 새 개정판으로 올리세요.",
  NOT_SEALED: "아직 봉인되지 않았습니다 — 업로드를 마치고 봉인한 뒤 다시 시도하세요.",
  // 설계 대비 잔량 요청(M4-A) — design_conformance_requests.py verdict. 정상
  // 동선에서는 패널이 VERIFIED 설계면만 고르게 하지만, 다른 탭에서 원장이 바뀌는
  // 레이스로는 여전히 도달한다.
  DESIGN_SURFACE_NOT_VERIFIED:
    "아직 검증되지 않은 설계 기준면입니다 — 검증이 끝난 것만 비교에 쓸 수 있습니다.",
  NO_DSM_ARTIFACT: "고른 재구성 결과에 높이자료(DSM)가 없습니다.",
  ZONES_REQUIRED:
    "구역을 확정해야 합니다 — 설계 대비 잔량은 '어느 범위의' 잔량인지 없이는 답이 되지 않습니다.",
  VERTICAL_REFERENCE_UNKNOWN:
    "이 재구성 결과는 높이 기준이 기록되기 전에 만들어졌습니다 — 다시 재구성하면 비교할 수 있습니다.",
  VERTICAL_DATUM_INCOMPATIBLE:
    "설계 기준면과 현재 지형의 높이 기준 계열이 다릅니다 — 변환 없이 비교하면 20~30 m 가 틀리므로 계산하지 않습니다.",
  // 작업구역(M4-C) — work_areas.py · design_conformance_requests.py verdict.
  WORK_AREA_UNUSABLE:
    "고른 작업구역을 쓸 수 없습니다 — 다른 현장 소속이거나 보관된 구역일 수 있습니다.",
  UNKNOWN_WORK_AREA: "등록된 적 없는 작업구역입니다.",
  SUPERSEDES_NOT_FOUND: "대체하려는 작업구역을 찾을 수 없습니다.",
  SUPERSEDES_OTHER_SITE: "대체 대상이 다른 현장 소속입니다.",
  ALREADY_ARCHIVED: "이미 보관된 작업구역입니다.",
  TOO_MANY_ACTIVE:
    "이 현장의 작업구역이 상한에 도달했습니다 — 쓰지 않는 구역을 먼저 보관하세요.",
  INVALID_WORK_AREA: "작업구역 폴리곤 형식이 올바르지 않습니다.",
  UNKNOWN_REPORT: "그 설계 대비 잔량 리포트를 찾을 수 없습니다.",
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

/** 실패 응답 본문에서 읽어낼 수 있는 자리들 — 경로마다 모양이 다르다(아래 주석). */
export interface ApiErrorBodyShape {
  /** 성공 경로의 판정값. `coreApiErrorResponse` 가 만든 실패 응답에는 없다. */
  verdict?: string;
  /** `coreApiErrorResponse` 가 붙이는 Core verdict 코드. */
  code?: string;
  /** `coreApiErrorResponse` 가 이미 `humanizeApiError`로 옮겨 둔 문구. */
  message?: string;
  /** Core 원문 — 내부 어휘가 섞여 있어 **마지막 수단**이다. 성공 응답에서는 null 이 온다. */
  detail?: string | null;
}

/**
 * 실패 사유를 사람 말로 — **본문 모양이 경로마다 다르다는 것이 요점**이다.
 *
 * 성공 응답은 `{verdict, ...}`, `coreApiErrorResponse` 가 만든 Core 오류는
 * `{message, code, detail}`, 출처 가드(403)는 `{message}` 뿐이다. 예전에는 각 화면이
 * `verdict`와 `detail`만 읽어서, 오류 응답에는 `verdict`가 아예 없으니 늘 `detail`
 * (Core 원문)로 떨어졌다 — 저장소 점검 중이면 사용자에게 "journal 봉인됨 — 재시작
 * 필요" 같은 내부 문구가 그대로 보였다. 이미 사람 말로 옮겨 둔 `message`는 한 번도
 * 쓰이지 않았다. 화면마다 이 로직을 각자 새로 짜면 같은 실수가 반복된다 — 한 곳에서만
 * 정의한다.
 *
 * 우선순위: 우리가 아는 코드의 문구 → 서버가 옮겨 준 문구 → 원문 → 기본값.
 */
export function readableApiError(body: ApiErrorBodyShape, fallback: string): string {
  const code = body.verdict ?? body.code;
  if (code && code in API_ERROR_MESSAGE) {
    return API_ERROR_MESSAGE[code as keyof typeof API_ERROR_MESSAGE];
  }
  // `??` 로는 빈 문자열이 통과해 사용자에게 빈 오류가 보인다 — 내용이 있는 것만 고른다.
  return [body.message, body.detail].find((text) => text) ?? fallback;
}
