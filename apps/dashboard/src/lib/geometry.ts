import type { AoiVertex } from "@/lib/core-api/types";

// lawnmower(매핑) 패턴은 볼록 AOI 에서만 전체 커버를 보증한다 — 서버가 비볼록을
// NON_CONVEX_AOI 로 거부한다(packages/mission-planning/src/ksi_mission_planning/coverage.py).
// 미리 걸러 "그려보고서야 발급 실패"를 막는다(§7 구현 노트와 동일한 정신).
export function isConvexPolygon(vertices: AoiVertex[]): boolean {
  if (vertices.length < 3) return false;
  let sign = 0;
  const n = vertices.length;
  for (let i = 0; i < n; i++) {
    const a = vertices[i];
    const b = vertices[(i + 1) % n];
    const c = vertices[(i + 2) % n];
    const cross =
      (b.lonDeg - a.lonDeg) * (c.latDeg - b.latDeg) - (b.latDeg - a.latDeg) * (c.lonDeg - b.lonDeg);
    if (Math.abs(cross) < 1e-12) continue; // 거의 일직선 — 부호 판정 보류
    const currentSign = cross > 0 ? 1 : -1;
    if (sign === 0) {
      sign = currentSign;
    } else if (currentSign !== sign) {
      return false;
    }
  }
  // 모든 변이 거의 일직선(면적 0에 수렴)이면 부호가 한 번도 정해지지 않는다 — 이런
  // 퇴화 폴리곤을 볼록으로 통과시키지 않는다(독립 재검토 2차 B-4).
  return sign !== 0;
}
