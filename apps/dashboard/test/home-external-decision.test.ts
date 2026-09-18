import { describe, expect, it } from "vitest";

import type { ExternalPendingDecision } from "@/lib/core-api/external-decisions";
import { externalDecisionCardText } from "@/lib/home-external-decision";

const decision = (overrides: Partial<ExternalPendingDecision> = {}): ExternalPendingDecision => ({
  siteId: "site a",
  reportRef: "report/1",
  kind: "EXTERNAL_RELATIVE_VOLUME",
  stage: "AWAITING_REVIEW",
  reportedAt: "2026-09-18T01:00:00Z",
  netM3: 12.5,
  uncertaintyM3: 3,
  workAreaId: "zone-1",
  ...overrides,
});

describe("Home external decision card (AX-4)", () => {
  it("shows the review wait with signed net volume and uncertainty, linking to the report", () => {
    expect(externalDecisionCardText(decision())).toEqual({
      label: "외부 결과 · 검토 대기",
      title: "순 체적 +12.5 m³ · 불확도 ±3 m³",
      detail: "측정 결과와 근거를 검토하고 사용 여부를 결정하세요.",
      href: "/sites/site%20a/observations/report%2F1",
      actionLabel: "결과와 근거 보기",
    });
  });

  it("names the approval wait and a missing uncertainty without inventing one", () => {
    const text = externalDecisionCardText(decision({ stage: "AWAITING_APPROVAL", uncertaintyM3: null, netM3: -4 }));
    expect(text.label).toBe("외부 결과 · 승인 대기");
    expect(text.title).toBe("순 체적 -4 m³ · 불확도 미산출");
    expect(text.detail).toBe("검토한 결과로 만든 재관측 제안이 승인을 기다립니다.");
  });

  it("never renders a negative zero", () => {
    expect(externalDecisionCardText(decision({ netM3: -0 })).title).toBe("순 체적 0 m³ · 불확도 ±3 m³");
  });
});
