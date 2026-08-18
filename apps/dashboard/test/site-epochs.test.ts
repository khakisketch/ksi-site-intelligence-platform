/** 현장 상세의 **시점 선택 · 탭** 판정 회귀(Console v2 §3).
 *
 * 여기서 고정하는 것은 셋이다: 이력 줄이 실패한 시점을 감추지 않는가 · 순서가
 * 서버 응답 순서에 휘둘리지 않는가 · URL 로 들어온 낯선 값에 화면이 깨지지 않는가.
 */

import { describe, expect, it } from "vitest";

import {
  SITE_TABS,
  findEpoch,
  normalizeSiteTab,
  resolveEpochId,
  toSiteEpochs,
} from "../src/lib/site-epochs";
import type { SiteProcessingJobSummary } from "../src/lib/core-api/types";

function job(
  overrides: Partial<SiteProcessingJobSummary> & Pick<SiteProcessingJobSummary, "jobId">,
): SiteProcessingJobSummary {
  return {
    missionId: "M-1",
    siteId: "S-1",
    status: "SUCCEEDED",
    issuedAt: "2026-08-01T00:00:00Z",
    detail: null,
    artifacts: [],
    ...overrides,
  };
}

describe("조사 기록 시점", () => {
  it("서버가 어떤 순서로 주든 최신이 앞이다", () => {
    const epochs = toSiteEpochs([
      job({ jobId: "old", issuedAt: "2026-07-01T00:00:00Z" }),
      job({ jobId: "new", issuedAt: "2026-08-10T00:00:00Z" }),
      job({ jobId: "mid", issuedAt: "2026-08-01T00:00:00Z" }),
    ]);
    expect(epochs.map((e) => e.jobId)).toEqual(["new", "mid", "old"]);
  });

  it("성공하지 않은 시점도 남긴다 — 그 날짜의 결과가 왜 없는지가 사라지면 안 된다", () => {
    const epochs = toSiteEpochs([
      job({ jobId: "failed", status: "FAILED" }),
      job({ jobId: "running", status: "RUNNING", issuedAt: "2026-08-02T00:00:00Z" }),
    ]);
    expect(epochs.map((e) => e.status).sort()).toEqual(["FAILED", "RUNNING"]);
  });

  it("산출물 종류를 그대로 옮긴다 — 없으면 빈 배열이다", () => {
    const epochs = toSiteEpochs([
      job({ jobId: "a", artifacts: [{ artifactId: "x", kind: "dsm" }, { artifactId: "y", kind: "ortho" }] }),
      job({ jobId: "b", issuedAt: "2026-07-01T00:00:00Z" }),
    ]);
    expect(epochs[0].artifactKinds).toEqual(["dsm", "ortho"]);
    expect(epochs[1].artifactKinds).toEqual([]);
  });
});

describe("URL 의 시점 값", () => {
  const epochs = toSiteEpochs([
    job({ jobId: "new", issuedAt: "2026-08-10T00:00:00Z" }),
    job({ jobId: "old", issuedAt: "2026-07-01T00:00:00Z" }),
  ]);

  it("실재하는 시점이면 그대로 고른다", () => {
    expect(resolveEpochId(epochs, "old")).toBe("old");
  });

  it("모르는 값·빈 값은 최신으로 되돌린다 — 빈 화면을 내지 않는다", () => {
    expect(resolveEpochId(epochs, "지워진작업")).toBe("new");
    expect(resolveEpochId(epochs, undefined)).toBe("new");
    expect(resolveEpochId(epochs, "")).toBe("new");
  });

  it("시점이 하나도 없으면 null 이다 — 아무거나 고르지 않는다", () => {
    expect(resolveEpochId([], "무엇이든")).toBeNull();
    expect(findEpoch([], null)).toBeNull();
    expect(findEpoch(epochs, "없는id")).toBeNull();
  });
});

describe("탭", () => {
  it("네 갈래다", () => {
    expect(SITE_TABS.map((t) => t.key)).toEqual(["overview", "volume", "design", "records"]);
  });

  it("모르는 탭 값은 개요로 되돌린다", () => {
    expect(normalizeSiteTab("volume")).toBe("volume");
    expect(normalizeSiteTab("없는탭")).toBe("overview");
    expect(normalizeSiteTab(undefined)).toBe("overview");
  });
});
