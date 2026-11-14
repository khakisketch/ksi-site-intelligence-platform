import type { AnalysisListItem } from "@/lib/core-api/analysis";
import type { SpatialAssetCatalogPage } from "@/lib/core-api/spatial-assets";

export type SiteSpatialAssetsState =
  | { status: "ready"; page: SpatialAssetCatalogPage }
  | { status: "denied" }
  | { status: "unavailable" }
  | { status: "not-requested" };

/** 서버 상태 코드를 사람 말로만 옮긴다 — 원 코드를 바꾸거나 판정하지 않는다. */
export function analysisStateLabel(item: Pick<AnalysisListItem, "executionState" | "suitabilityState">): string {
  if (item.executionState === "FAILED") return "처리 실패";
  if (item.executionState === "RUNNING") return "처리 중";
  if (item.executionState === "QUEUED") return "처리 대기 중";
  if (item.executionState === "NOT_STARTED") return "처리 시작 전";
  switch (item.suitabilityState) {
    case "EVALUATED": return "분석 조건 확인 결과 있음";
    case "BLOCKED": return "분석을 진행할 수 없음";
    case "REMEDIATION_REQUIRED": return "자료 보완 필요";
    case "PROVISIONAL_ACCURACY_UNVERIFIED": return "정확도 미확인";
    case "REASSESSMENT_REQUIRED": return "사용 조건 재확인 필요";
    default: return "분석 조건 확인 필요";
  }
}
