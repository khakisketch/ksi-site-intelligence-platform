import type { MissionType, ReobservationGrade, SpatialRefreshDraftResponse } from "./types";

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

/** 재관측 촬영 등급의 한국어 라벨·설명(ADR-KSI-019 G5) — 내부 상태값을 화면에 그대로 내지 않는다. */
export const REOBSERVATION_GRADE_LABEL: Record<
  ReobservationGrade,
  { label: string; description: string }
> = {
  STANDARD: { label: "직전과 동일", description: "변화가 뚜렷해서 지난번과 같은 조건으로 확인할 수 있습니다." },
  DETAILED: { label: "더 자세히", description: "변화가 작아서 더 낮게 날아 더 선명하게 찍습니다." },
  INTENSIVE: {
    label: "자세히 + 촘촘히",
    description: "지난번에 못 본 부분이 많아 더 낮게, 더 겹쳐서 찍습니다.",
  },
};

/** `captureUnavailableReason` 코드를 한국어 문장으로 — 코드를 화면에 그대로 내지 않는다. */
export function describeCaptureUnavailableReason(reason: string | null): string | null {
  switch (reason) {
    case "BASELINE_CAPTURE_UNKNOWN":
      return "직전 촬영 조건을 알 수 없어 값을 제안하지 못했습니다. 아래에서 직접 정해주세요.";
    case "CAPTURE_DERIVATION_FAILED":
      return "촬영 조건을 계산하지 못했습니다. 아래에서 직접 정해주세요.";
    default:
      return null;
  }
}

/**
 * 재관측 초안(``spatial-refresh-draft``)에서 위저드가 쓸 값만 좁힌다.
 *
 * ``null`` 을 반환하는 경우: 초안 자체가 없거나(AOI 미발급) 응답이 실패
 * 형태다 — 그때는 위저드가 빈 상태로 시작한다(기존 동작 그대로).
 *
 * **값을 지어내지 않는다** — 서버가 준 숫자를 그대로 옮기고, 검증은 여전히
 * 서버 발급 게이트(비행 봉투·중복도 하한)가 한다. 이 함수는 표시·초기값
 * 용도이지 클라이언트 검증이 아니다.
 */
export function resolveReobservationCapturePreset(
  draft: SpatialRefreshDraftResponse,
): {
  altitudeM: number | null;
  frontOverlap: number | null;
  sideOverlap: number | null;
  captureIntervalM: number | null;
  grade: ReobservationGrade | null;
  rationale: string[];
  unavailableReason: string | null;
} | null {
  if (draft.verdict !== "DRAFT_READY" || !draft.aoi) return null;
  return {
    altitudeM: draft.captureAltitudeM,
    frontOverlap: draft.captureFrontOverlap,
    sideOverlap: draft.captureSideOverlap,
    captureIntervalM: draft.captureIntervalM,
    grade: draft.captureGrade,
    rationale: draft.captureRationale,
    unavailableReason: draft.captureUnavailableReason,
  };
}
