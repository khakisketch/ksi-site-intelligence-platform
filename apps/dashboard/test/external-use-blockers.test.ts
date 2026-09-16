import { describe, expect, it } from "vitest";

import { explainExternalUseDecision } from "@/lib/external-use-blockers";

describe("explainExternalUseDecision", () => {
  it("explains a known reason and its remediation in Korean", () => {
    const guide = explainExternalUseDecision(
      ["EVIDENCE_INDEPENDENCE_UNATTESTED"],
      ["ATTEST_INDEPENDENT_EVIDENCE"],
    );
    expect(guide.known).toBe(true);
    expect(guide.title).toBe("체크포인트 증거에 독립성 확인이 없습니다");
    expect(guide.step).toContain("독립 측량 확인");
    expect(guide.owner).toBe("ADMIN");
    expect(guide.ownerLabel).toBe("관리자");
    expect(guide.target).toBe("EVIDENCE");
    expect(guide.codes).toEqual(["EVIDENCE_INDEPENDENCE_UNATTESTED", "ATTEST_INDEPENDENT_EVIDENCE"]);
  });

  it("falls back without crashing on an unknown code and keeps the raw codes", () => {
    const guide = explainExternalUseDecision(["SOMETHING_NEW"], []);
    expect(guide.known).toBe(false);
    expect(guide.title).toBe("판정이 막혔습니다");
    expect(guide.step).toContain("운영자");
    expect(guide.codes).toEqual(["SOMETHING_NEW"]);
  });

  it("uses the first known reason when several are reported", () => {
    const guide = explainExternalUseDecision(
      ["POLICY_UNAVAILABLE", "SUBJECT_NOT_SEALED"],
      ["AUTHORIZE_POLICY"],
    );
    expect(guide.target).toBe("POLICY");
  });
});
