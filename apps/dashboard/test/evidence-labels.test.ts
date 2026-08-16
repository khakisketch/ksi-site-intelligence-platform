import { describe, expect, it } from "vitest";

import { evidenceDeviceBoundLabel } from "@/lib/core-api/labels";

// EvidenceSummary.deviceBound 는 CRITICAL 확정용 증거의 자격 요건이다(types.ts 주석).
// 화면이 이 값을 라벨로 옮기지 못하면 운영자는 확정을 시도한 뒤 서버 거부로만
// 그 사실을 알게 된다 — 그 회귀를 여기서 고정한다.
describe("evidenceDeviceBoundLabel", () => {
  it("장비 신원이 대조된 증거는 긍정 톤으로 표시한다", () => {
    const result = evidenceDeviceBoundLabel(true);
    expect(result.tone).toBe("positive");
    expect(result.label.length).toBeGreaterThan(0);
  });

  it("[핵심] 장비 신원이 대조되지 않은 증거는 다른 라벨·다른 톤으로 구분한다", () => {
    const bound = evidenceDeviceBoundLabel(true);
    const unbound = evidenceDeviceBoundLabel(false);
    expect(unbound.label).not.toBe(bound.label);
    expect(unbound.tone).not.toBe(bound.tone);
    // neutral/positive 로 뭉개면 CRITICAL 확정 화면에서 "그냥 증거 하나"로 보인다 —
    // 주의를 끌어야 하므로 안전 상태색 계열(caution/warning) 이어야 한다.
    expect(["caution", "warning"]).toContain(unbound.tone);
  });
});
