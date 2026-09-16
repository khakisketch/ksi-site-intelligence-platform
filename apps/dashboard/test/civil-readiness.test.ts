import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { presentCivilReadiness } from "@/lib/civil-readiness";
import type { CivilReadinessView } from "@/lib/core-api/types";

function readiness(overrides: Partial<CivilReadinessView> = {}): CivilReadinessView {
  return {
    schemaVersion: "1.0",
    siteId: "site-1",
    status: "PAIR_COMPATIBLE",
    succeededEpochCount: 2,
    pair: {
      baselineJobId: "job-baseline",
      currentJobId: "job-current",
      compatible: true,
      reason: null,
      detail: "두 최신 처리 시점의 evidence·profile·lineage·CRS·수직기준이 일치합니다.",
    },
    designSurface: {
      status: "VERIFIED_AVAILABLE",
      totalSurfaceCount: 1,
      verifiedSurfaceCount: 1,
      detail: "검증된 설계 기준면이 있습니다.",
    },
    nextAction: {
      label: "두 시점 비교 열기",
      href: "/missions/mission-current",
      reason: "선택한 입력을 Core가 다시 검증합니다.",
    },
    limitations: ["OPERATIONAL_RELATIVE_QUANTITY_ONLY", "FIELD_ACCEPTANCE_NOT_INCLUDED"],
    ...overrides,
  };
}

describe("presentCivilReadiness", () => {
  it("fails closed when the site projection cannot be read, with one line and one next step", () => {
    const presentation = presentCivilReadiness(null);

    expect(presentation.label).toBe("토목 준비 상태 확인 불가");
    expect(presentation.tone).toBe("warning");
    // States what is missing plus one next step — not a stack of independent
    // negative sentences on top of the already-negative badge/label (F07).
    expect(presentation.detail).toBe(
      "처리·설계 원장을 지금 읽을 수 없습니다. 새로고침해서 다시 확인하세요.",
    );
    expect(presentation.detail.split(".").filter((sentence) => sentence.trim()).length).toBeLessThanOrEqual(2);
  });

  it("shows one missing first epoch as setup work, not a comparison result", () => {
    const presentation = presentCivilReadiness(
      readiness({
        status: "FIRST_EPOCH_REQUIRED",
        succeededEpochCount: 0,
        pair: {
          baselineJobId: null,
          currentJobId: null,
          compatible: false,
          reason: "FIRST_EPOCH_REQUIRED",
          detail: "완료된 처리 시점이 없어 첫 조사 원본의 봉인·처리가 필요합니다.",
        },
      }),
    );

    expect(presentation.label).toBe("첫 조사 시점 필요");
    expect(presentation.tone).toBe("neutral");
    expect(presentation.pairLabel).toBe("완료된 처리 시점 없음");
  });

  it("keeps a compatible pair as a candidate rather than field acceptance", () => {
    const presentation = presentCivilReadiness(readiness());

    expect(presentation.label).toBe("두 시점 비교 후보 준비");
    expect(presentation.tone).toBe("positive");
    expect(presentation.detail).toContain("다시 검증");
    expect(presentation.detail).not.toContain("현장 수용");
  });

  it("turns the shared typed preflight blocker into an operator-facing next step", () => {
    const presentation = presentCivilReadiness(
      readiness({
        status: "PAIR_BLOCKED",
        pair: {
          baselineJobId: "job-baseline",
          currentJobId: "job-current",
          compatible: false,
          reason: "PROCESSING_PROFILE_MISMATCH",
          detail: "두 epoch의 processingProfileDigest가 다릅니다.",
        },
      }),
    );

    expect(presentation.label).toBe("두 시점 비교 차단");
    expect(presentation.tone).toBe("warning");
    expect(presentation.pairLabel).toContain("PROCESSING_PROFILE_MISMATCH");
    expect(presentation.detail).toContain("고정 처리 프로필");
  });

  it("does not call a registered or sealed design surface verified", () => {
    const presentation = presentCivilReadiness(
      readiness({
        designSurface: {
          status: "VERIFICATION_REQUIRED",
          totalSurfaceCount: 1,
          verifiedSurfaceCount: 0,
          detail: "등록된 설계 기준면은 있지만 VERIFIED 관측 근거가 없습니다.",
        },
      }),
    );

    expect(presentation.label).toBe("두 시점 확인 · 설계면 검증 대기");
    expect(presentation.tone).toBe("caution");
    expect(presentation.designSurfaceLabel).toBe("설계 기준면 검증 대기");
  });
});

describe("civil readiness Console wiring", () => {
  it("keeps the read-only candidate on the existing Site data tab with explicit limits", () => {
    const page = readFileSync(join(process.cwd(), "src/app/sites/[siteId]/page.tsx"), "utf8");
    const card = readFileSync(join(process.cwd(), "src/components/site/CivilReadinessCard.tsx"), "utf8");
    const client = readFileSync(join(process.cwd(), "src/lib/core-api/civil-readiness.ts"), "utf8");

    expect(page).toContain("getCivilReadiness(site.siteId)");
    expect(page).toContain("<CivilReadinessCard");
    expect(client).toContain("/civil-readiness");
    expect(card).toContain("현장 수용·측량 정확도·정산 수량·비행 또는 장비 상태를 뜻하지 않습니다.");
    expect(card).not.toMatch(/method=\"POST\"|method=\"PUT\"|method=\"PATCH\"/);
  });
});
