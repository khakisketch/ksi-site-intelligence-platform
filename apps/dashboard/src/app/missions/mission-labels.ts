// 임무 화면 전용 마이크로카피 — MISSION_TYPE_LABEL 은 화면 간 분기(§4 SSOT 원칙 위반)를
// 막기 위해 lib/core-api/labels.ts 로 옮겨졌다. 여기서는 재노출만 한다(기존 import 경로
// 호환용). routePattern/artifactKind 는 missions/ 스코프 전용이라 그대로 둔다.

export { MISSION_TYPE_LABEL } from "@/lib/core-api/labels";

export const ROUTE_PATTERN_LABEL: Record<"lawnmower" | "perimeter", string> = {
  lawnmower: "격자(매핑)",
  perimeter: "외곽(순찰)",
};

export const ARTIFACT_KIND_LABEL: Record<"pair" | "contract", string> = {
  pair: "경로+계약 짝",
  contract: "계약 단독",
};
