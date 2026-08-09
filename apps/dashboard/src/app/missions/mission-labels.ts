// 임무 화면 전용 마이크로카피 — MISSION_TYPE_LABEL 은 화면 간 분기(§4 SSOT 원칙 위반)를
// 막기 위해 lib/core-api/labels.ts 로 옮겨졌다. 여기서는 재노출만 한다(기존 import 경로
// 호환용). routePattern/artifactKind/coverage 는 missions/ 스코프 전용이라 그대로 둔다.

import type { Tone } from "@/lib/core-api/labels";
import type { CompletionState, CoverageCellState } from "@/lib/core-api/types";

export { MISSION_TYPE_LABEL } from "@/lib/core-api/labels";

export const ROUTE_PATTERN_LABEL: Record<"lawnmower" | "perimeter", string> = {
  lawnmower: "격자(매핑)",
  perimeter: "외곽(순찰)",
};

export const ARTIFACT_KIND_LABEL: Record<"pair" | "contract", string> = {
  pair: "경로+계약 짝",
  contract: "계약 단독",
};

// 비행 후 CoverageReport 의 completionState → 한국어(INV-010, PRD §15.5).
// 서버가 이미 판정한 값이다 — 대시보드는 라벨만 입힌다.
export const COMPLETION_STATE_LABEL: Record<CompletionState, { label: string; tone: Tone }> = {
  COMPLETED: { label: "완료", tone: "positive" },
  COMPLETED_WITH_GAPS: { label: "공백 있는 완료", tone: "caution" },
  ABORTED_SAFE: { label: "안전 중단", tone: "warning" },
  FAILED: { label: "실패", tone: "warning" },
};

// 아직 보고가 도착하지 않은 임무(coverageCompletionState === null) — "—" 로 조용히
// 넘어가지 않고 이 상태 자체를 라벨로 보여준다.
export const COVERAGE_NOT_REPORTED_LABEL: { label: string; tone: Tone } = {
  label: "비행 보고 없음",
  tone: "neutral",
};

// CoverageCell.state → 한국어(coverage-report.v1.1.json 11종 그대로).
export const CELL_STATE_LABEL: Record<CoverageCellState, string> = {
  OBSERVED_HIGH_CONFIDENCE: "고신뢰 관찰",
  OBSERVED_PARTIAL: "부분 관찰",
  RECONSTRUCTION_READY: "재구성 가능",
  EVENT_INSPECTED: "이벤트 확인됨",
  OCCLUDED: "가려짐",
  UNREACHABLE: "접근 불가",
  NOT_OBSERVED: "미관찰(사유 없음)",
  UNSAFE: "안전상 제외",
  SENSOR_LIMITED: "센서 한계",
  TIME_LIMITED: "시간 한계",
  BATTERY_LIMITED: "배터리 한계",
};
