/** 현장 상세의 **시점 선택 · 탭** 판정 회귀(Console v2 §3).
 *
 * 여기서 고정하는 것은 셋이다: 이력 줄이 실패한 시점을 감추지 않는가 · 순서가
 * 서버 응답 순서에 휘둘리지 않는가 · URL 로 들어온 낯선 값에 화면이 깨지지 않는가.
 */

import { describe, expect, it } from "vitest";

import {
  SITE_TABS,
  ambiguousEpochDays,
  epochDayKey,
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
    captureWindow: overrides.captureWindow ?? {
      status: "INCOMPLETE", capturedFrom: null, capturedTo: null,
    },
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

describe("같은 날 겹치는 시점", () => {
  it("한 날짜에 둘 이상이면 그 날짜를 집어낸다", () => {
    // 실데이터 확인(2026-08-18)에서 드러난 문제 — 같은 날 두 번 처리하면 칩이
    // 둘 다 "8. 18."로 찍혀 눈으로 구분되지 않았다.
    const epochs = toSiteEpochs([
      job({ jobId: "a", issuedAt: "2026-08-18T06:06:52Z" }),
      job({ jobId: "b", issuedAt: "2026-08-18T06:06:53Z" }),
      job({ jobId: "c", issuedAt: "2026-08-10T06:00:00Z" }),
    ]);
    expect([...ambiguousEpochDays(epochs)]).toEqual(["2026-08-18"]);
  });

  it("날짜가 겹치지 않으면 아무것도 집어내지 않는다 — 전부 시각을 붙이지 않는다", () => {
    const epochs = toSiteEpochs([
      job({ jobId: "a", issuedAt: "2026-08-18T06:00:00Z" }),
      job({ jobId: "b", issuedAt: "2026-08-10T06:00:00Z" }),
    ]);
    expect(ambiguousEpochDays(epochs).size).toBe(0);
  });

  it("날짜 판정은 서울 기준이다 — UTC 자정 근처에서 날이 갈린다", () => {
    // 2026-08-17T16:00Z = 서울 8월 18일 01:00. UTC 로 읽으면 다른 날이 된다.
    expect(epochDayKey("2026-08-17T16:00:00Z")).toBe("2026-08-18");
    expect(epochDayKey("2026-08-17T14:00:00Z")).toBe("2026-08-17");
  });

  it("파싱할 수 없는 값도 키를 만든다 — 그 칩만 스스로와 같아진다", () => {
    expect(epochDayKey("언제인지모름")).toBe("언제인지모름");
  });
});

describe("탭", () => {
  it("현장 업무 다섯 갈래다", () => {
    expect(SITE_TABS.map((t) => t.key)).toEqual([
      "briefing",
      "data",
      "review-items",
      "work",
      "reports",
    ]);
  });

  it("모르는 값은 브리핑으로, 기존 탭은 대응 영역으로 되돌린다", () => {
    expect(normalizeSiteTab("data")).toBe("data");
    expect(normalizeSiteTab("volume")).toBe("data");
    expect(normalizeSiteTab("records")).toBe("work");
    expect(normalizeSiteTab("없는탭")).toBe("briefing");
    expect(normalizeSiteTab(undefined)).toBe("briefing");
  });
});
