import { describe, expect, it } from "vitest";

import { manualDispatchRejectionWarning } from "@/components/missions/ManualDispatchButton";

describe("수동 이관 신고 버튼의 거부 경고 문구", () => {
  it("실행 상태를 아직 모르면 경고하지 않는다", () => {
    expect(manualDispatchRejectionWarning(null)).toBeNull();
  });

  it("ISSUED 는 정상 경로이므로 경고하지 않는다", () => {
    expect(manualDispatchRejectionWarning("ISSUED")).toBeNull();
  });

  it("CANCELLED 는 '이미 전달됨'이 아니라 비행 금지로 경고한다", () => {
    const warning = manualDispatchRejectionWarning("CANCELLED");
    expect(warning).not.toBeNull();
    expect(warning).toContain("취소");
    expect(warning).not.toContain("이미 전달");
  });

  it("그 외 이미 진행된 상태는 '이미 전달됨'으로 경고한다", () => {
    for (const status of ["DISPATCHED", "ACTIVATED", "COMPLETED", "ENDED_INCOMPLETE"] as const) {
      const warning = manualDispatchRejectionWarning(status);
      expect(warning).toContain("이미 전달");
    }
  });
});
